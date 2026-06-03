from __future__ import annotations

import sqlite3
from pathlib import Path

from persistence.sqlite.paths import default_db_path

# Incrementar al aplicar migraciones DDL (ver bloque _apply_schema_if_needed).
CURRENT_SCHEMA_VERSION = 6


def _schema_sql() -> str:
    pkg = Path(__file__).resolve().parent / "schema.sql"
    return pkg.read_text(encoding="utf-8")


def _scan_metrics_column_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(scan_metrics)").fetchall()
    return {str(r[1]) for r in rows}


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Añade columnas tipadas a scan_metrics (instalaciones previas a v2)."""
    cols = _scan_metrics_column_names(conn)
    additions: list[tuple[str, str]] = [
        ("total_scan_seconds", "REAL"),
        ("usa_scan_seconds", "REAL"),
        ("arg_scan_seconds", "REAL"),
        ("cedear_scan_seconds", "REAL"),
        ("alerts_seconds", "REAL"),
        ("usa_total_activos", "INTEGER"),
        ("arg_total_activos", "INTEGER"),
        ("cedear_total_activos", "INTEGER"),
        ("usa_alertas", "INTEGER"),
        ("arg_alertas", "INTEGER"),
        ("cedear_alertas", "INTEGER"),
    ]
    for name, sql_type in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE scan_metrics ADD COLUMN {name} {sql_type}")


def _positions_column_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(positions)").fetchall()
    return {str(r[1]) for r in rows}


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Amplía positions para el módulo Cartera (compra / seguimiento / venta)."""
    cols = _positions_column_names(conn)
    additions: list[tuple[str, str]] = [
        ("asset_type", "TEXT"),
        ("buy_date", "TEXT"),
        ("buy_price_ars", "REAL"),
        ("buy_price_usd", "REAL"),
        ("buy_price_cedear_usd", "REAL"),
        ("buy_price_usa", "REAL"),
        ("buy_gap", "REAL"),
        ("score_at_buy", "REAL"),
        ("signalstate_at_buy", "TEXT"),
        ("techscore_at_buy", "REAL"),
        ("fundscore_at_buy", "REAL"),
        ("riskscore_at_buy", "REAL"),
        ("sell_date", "TEXT"),
        ("sell_price_ars", "REAL"),
        ("sell_price_usd", "REAL"),
        ("sell_notes", "TEXT"),
        ("sell_price_cedear_usd", "REAL"),
        ("sell_price_usa", "REAL"),
        ("sell_gap", "REAL"),
        ("score_at_sell", "REAL"),
        ("signalstate_at_sell", "TEXT"),
        ("techscore_at_sell", "REAL"),
        ("fundscore_at_sell", "REAL"),
        ("riskscore_at_sell", "REAL"),
        ("status", "TEXT"),
        ("realized_return_pct", "REAL"),
        ("holding_days", "INTEGER"),
    ]
    for name, sql_type in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {name} {sql_type}")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_positions_buy_date ON positions (buy_date)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_positions_status ON positions (status)")

    conn.execute(
        """
        UPDATE positions
        SET buy_date = opened_at
        WHERE (buy_date IS NULL OR trim(buy_date) = '')
          AND opened_at IS NOT NULL AND trim(opened_at) != ''
        """
    )
    conn.execute(
        """
        UPDATE positions
        SET asset_type = CASE
          WHEN upper(ifnull(market, '')) LIKE '%CEDEAR%' THEN 'CEDEAR'
          WHEN upper(ifnull(market, '')) LIKE '%ARG%' THEN 'Argentina'
          ELSE 'USA'
        END
        WHERE asset_type IS NULL AND market IS NOT NULL AND trim(market) != ''
        """
    )
    conn.execute(
        """
        UPDATE positions SET status = 'open'
        WHERE status IS NULL OR trim(status) = ''
        """
    )
    conn.execute(
        """
        UPDATE positions
        SET status = 'closed', sell_date = closed_at
        WHERE closed_at IS NOT NULL AND trim(closed_at) != ''
        """
    )


def _migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    """
    Cartera: instrument_type (stock/option/option_strategy) y campos opcionales para opciones.
    No altera asset_type (USA/Argentina/CEDEAR) ni filas existentes.
    """
    cols = _positions_column_names(conn)
    additions: list[tuple[str, str]] = [
        ("instrument_type", "TEXT DEFAULT 'stock'"),
        ("underlying_symbol", "TEXT"),
        ("strategy_type", "TEXT"),
        ("option_expiration", "TEXT"),
        ("initial_debit_credit", "REAL"),
        ("committed_capital", "REAL"),
        ("max_risk", "REAL"),
        ("max_profit", "REAL"),
        ("opening_underlying_price", "REAL"),
        ("opening_iv", "REAL"),
        ("legs_json", "TEXT"),
        ("management_events_json", "TEXT"),
    ]
    for name, sql_type in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {name} {sql_type}")
    conn.execute(
        """
        UPDATE positions
        SET instrument_type = 'stock'
        WHERE instrument_type IS NULL OR trim(instrument_type) = ''
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_positions_instrument_type ON positions (instrument_type)"
    )


def _migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    """
    Cartera: portfolio_type radar (seguimiento alertas) vs real (operaciones reales).
    Filas existentes → radar. No toca asset_type ni instrument_type.
    """
    cols = _positions_column_names(conn)
    if "portfolio_type" not in cols:
        conn.execute(
            "ALTER TABLE positions ADD COLUMN portfolio_type TEXT NOT NULL DEFAULT 'radar'"
        )
    conn.execute(
        """
        UPDATE positions
        SET portfolio_type = 'radar'
        WHERE portfolio_type IS NULL OR trim(portfolio_type) = ''
        """
    )
    conn.execute(
        """
        UPDATE positions
        SET portfolio_type = 'radar'
        WHERE lower(portfolio_type) NOT IN ('radar', 'real')
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_positions_portfolio_type ON positions (portfolio_type)"
    )


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """TC MEP por operación (compra/venta) y retorno realizado en USD (Argentina vía MEP)."""
    cols = _positions_column_names(conn)
    additions: list[tuple[str, str]] = [
        ("tc_mep_compra", "REAL"),
        ("tc_mep_venta", "REAL"),
        ("realized_return_usd_pct", "REAL"),
    ]
    for name, sql_type in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {name} {sql_type}")


def _apply_schema_if_needed(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA user_version").fetchone()
    version = int(row[0]) if row else 0
    if version >= CURRENT_SCHEMA_VERSION:
        return
    if version == 0:
        conn.executescript(_schema_sql())
        conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        conn.commit()
        return
    while version < CURRENT_SCHEMA_VERSION:
        if version < 2:
            _migrate_v1_to_v2(conn)
            version = 2
        elif version < 3:
            _migrate_v2_to_v3(conn)
            version = 3
        elif version < 4:
            _migrate_v3_to_v4(conn)
            version = 4
        elif version < 5:
            _migrate_v4_to_v5(conn)
            version = 5
        elif version < 6:
            _migrate_v5_to_v6(conn)
            version = 6
        else:
            break
    conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
    conn.commit()


def init_database(db_path: Path | None = None) -> Path:
    """
    Crea el archivo si no existe y aplica el esquema versionado (PRAGMA user_version).
    Idempotente y seguro de llamar en cada arranque de API o tests.
    """
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        _apply_schema_if_needed(conn)
    finally:
        conn.close()
    return path
