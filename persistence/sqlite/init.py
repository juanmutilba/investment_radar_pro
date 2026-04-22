from __future__ import annotations

import sqlite3
from pathlib import Path

from persistence.sqlite.paths import default_db_path

# Incrementar al aplicar migraciones DDL (ver bloque _apply_schema_if_needed).
CURRENT_SCHEMA_VERSION = 2


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
    if version < 2:
        _migrate_v1_to_v2(conn)
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
