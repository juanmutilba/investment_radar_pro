from __future__ import annotations

import sqlite3
from pathlib import Path

from persistence.sqlite.paths import default_db_path

# Incrementar al aplicar migraciones DDL (ver bloque _apply_schema_if_needed).
CURRENT_SCHEMA_VERSION = 9


def _schema_sql() -> str:
    pkg = Path(__file__).resolve().parent / "schema.sql"
    return pkg.read_text(encoding="utf-8")


def _scan_metrics_column_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(scan_metrics)").fetchall()
    return {str(r[1]) for r in rows}


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """A├▒ade columnas tipadas a scan_metrics (instalaciones previas a v2)."""
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
    """Ampl├¡a positions para el m├│dulo Cartera (compra / seguimiento / venta)."""
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
    Filas existentes ÔåÆ radar. No toca asset_type ni instrument_type.
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
    """TC MEP por operaci├│n (compra/venta) y retorno realizado en USD (Argentina v├¡a MEP)."""
    cols = _positions_column_names(conn)
    additions: list[tuple[str, str]] = [
        ("tc_mep_compra", "REAL"),
        ("tc_mep_venta", "REAL"),
        ("realized_return_usd_pct", "REAL"),
    ]
    for name, sql_type in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {name} {sql_type}")


def _house_projects_column_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(house_projects)").fetchall()
    return {str(r[1]) for r in rows}

def _liabilities_column_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(family_liabilities)").fetchall()
    return {str(r[1]) for r in rows}

def _inv_cf_column_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(investment_cashflow_records)").fetchall()
    return {str(r[1]) for r in rows}

def _migrate_v6_to_v7(conn: sqlite3.Connection) -> None:
    """Family Office: activos, pasivos, pol├¡ticas, proyectos de casa y snapshots."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS family_assets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          category TEXT NOT NULL CHECK (category IN (
            'real_estate', 'vehicle', 'financial', 'business', 'cash', 'other'
          )),
          ownership_status TEXT NOT NULL CHECK (ownership_status IN (
            'owned', 'mortgaged', 'purchase_agreement', 'other'
          )),
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          estimated_value REAL NOT NULL CHECK (estimated_value >= 0),
          valuation_date TEXT NOT NULL,
          liquidity TEXT NOT NULL CHECK (liquidity IN ('high', 'medium', 'low')),
          generates_cashflow INTEGER NOT NULL DEFAULT 0 CHECK (generates_cashflow IN (0, 1)),
          monthly_cashflow REAL NOT NULL DEFAULT 0 CHECK (monthly_cashflow >= 0),
          notes TEXT,
          is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_family_assets_active_currency
        ON family_assets (is_active, currency)
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_family_assets_category ON family_assets (category)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS family_liabilities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          liability_type TEXT NOT NULL CHECK (liability_type IN (
            'mortgage_uva', 'family_debt', 'overdraft', 'vehicle_loan',
            'personal_loan', 'other'
          )),
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD', 'UVA')),
          original_amount REAL NOT NULL CHECK (original_amount >= 0),
          outstanding_balance REAL NOT NULL CHECK (outstanding_balance >= 0),
          installment_amount REAL NOT NULL DEFAULT 0 CHECK (installment_amount >= 0),
          installments_remaining INTEGER NOT NULL DEFAULT 0
            CHECK (installments_remaining >= 0),
          nominal_annual_rate REAL NOT NULL DEFAULT 0 CHECK (nominal_annual_rate >= 0),
          effective_annual_cost REAL
            CHECK (effective_annual_cost IS NULL OR effective_annual_cost >= 0),
          next_due_date TEXT,
          linked_asset_id INTEGER REFERENCES family_assets (id) ON DELETE SET NULL,
          notes TEXT,
          is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_family_liabilities_active_currency
        ON family_liabilities (is_active, currency)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_family_liabilities_type
        ON family_liabilities (liability_type)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capital_policies (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          destination TEXT NOT NULL CHECK (destination IN (
            'debt', 'investments', 'salva', 'investment_radar',
            'house', 'emergency_fund', 'other'
          )),
          minimum_monthly_amount REAL
            CHECK (minimum_monthly_amount IS NULL OR minimum_monthly_amount >= 0),
          maximum_monthly_amount REAL
            CHECK (maximum_monthly_amount IS NULL OR maximum_monthly_amount >= 0),
          priority INTEGER NOT NULL DEFAULT 0,
          is_mandatory INTEGER NOT NULL DEFAULT 0 CHECK (is_mandatory IN (0, 1)),
          notes TEXT,
          is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_capital_policies_active_priority
        ON capital_policies (is_active, priority)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS house_projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          priority TEXT NOT NULL CHECK (priority IN ('necessary', 'functional', 'aesthetic')),
          estimated_cost REAL NOT NULL CHECK (estimated_cost >= 0),
          paid_amount REAL NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          target_date TEXT,
          status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN (
            'planned', 'approved', 'in_progress', 'completed', 'paused'
          )),
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_house_projects_status ON house_projects (status)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS family_office_monthly_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          month TEXT NOT NULL UNIQUE,
          active_income REAL NOT NULL DEFAULT 0 CHECK (active_income >= 0),
          consulting_income REAL NOT NULL DEFAULT 0 CHECK (consulting_income >= 0),
          scalable_income REAL NOT NULL DEFAULT 0 CHECK (scalable_income >= 0),
          fixed_expenses REAL NOT NULL DEFAULT 0 CHECK (fixed_expenses >= 0),
          debt_payments REAL NOT NULL DEFAULT 0 CHECK (debt_payments >= 0),
          house_spending REAL NOT NULL DEFAULT 0 CHECK (house_spending >= 0),
          investment_contributions REAL NOT NULL DEFAULT 0
            CHECK (investment_contributions >= 0),
          free_cashflow REAL NOT NULL DEFAULT 0,
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fo_snapshots_month
        ON family_office_monthly_snapshots (month DESC)
        """
    )

def _migrate_v7_to_v8(conn: sqlite3.Connection) -> None:
    """Family Office etapa 2: soft-delete casa, snapshots multi-moneda, flujo y asignaci├│n."""
    cols = _house_projects_column_names(conn)
    if "is_active" not in cols:
        conn.execute(
            "ALTER TABLE house_projects ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_house_projects_active ON house_projects (is_active)"
    )
    conn.execute(
        "UPDATE house_projects SET is_active = 1 WHERE is_active IS NULL"
    )

    # Rebuild snapshots: UNIQUE(month) ÔåÆ UNIQUE(month, currency) sin perder filas.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS family_office_monthly_snapshots_v9 (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          month TEXT NOT NULL,
          active_income REAL NOT NULL DEFAULT 0 CHECK (active_income >= 0),
          consulting_income REAL NOT NULL DEFAULT 0 CHECK (consulting_income >= 0),
          scalable_income REAL NOT NULL DEFAULT 0 CHECK (scalable_income >= 0),
          fixed_expenses REAL NOT NULL DEFAULT 0 CHECK (fixed_expenses >= 0),
          debt_payments REAL NOT NULL DEFAULT 0 CHECK (debt_payments >= 0),
          house_spending REAL NOT NULL DEFAULT 0 CHECK (house_spending >= 0),
          investment_contributions REAL NOT NULL DEFAULT 0
            CHECK (investment_contributions >= 0),
          free_cashflow REAL NOT NULL DEFAULT 0,
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        INSERT INTO family_office_monthly_snapshots_v9 (
          id, month, active_income, consulting_income, scalable_income,
          fixed_expenses, debt_payments, house_spending, investment_contributions,
          free_cashflow, currency, notes, created_at, updated_at
        )
        SELECT
          id, month, active_income, consulting_income, scalable_income,
          fixed_expenses, debt_payments, house_spending, investment_contributions,
          free_cashflow, currency, notes, created_at, updated_at
        FROM family_office_monthly_snapshots
        """
    )
    conn.execute("DROP TABLE family_office_monthly_snapshots")
    conn.execute(
        "ALTER TABLE family_office_monthly_snapshots_v9 "
        "RENAME TO family_office_monthly_snapshots"
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_fo_snapshots_month_currency
        ON family_office_monthly_snapshots (month, currency)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fo_snapshots_month
        ON family_office_monthly_snapshots (month DESC)
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS family_fixed_expenses (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          category TEXT NOT NULL CHECK (category IN (
            'education', 'utilities', 'insurance', 'debt_payment', 'food',
            'transport', 'health', 'housing', 'taxes', 'other'
          )),
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          expected_monthly_amount REAL NOT NULL CHECK (expected_monthly_amount >= 0),
          priority INTEGER NOT NULL DEFAULT 0,
          coverage_order INTEGER NOT NULL DEFAULT 0,
          is_essential INTEGER NOT NULL DEFAULT 1 CHECK (is_essential IN (0, 1)),
          notes TEXT,
          is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_family_fixed_expenses_active_order
        ON family_fixed_expenses (is_active, currency, coverage_order)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS family_cashflow_entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          date TEXT NOT NULL,
          month TEXT NOT NULL,
          entry_type TEXT NOT NULL CHECK (entry_type IN ('income', 'expense')),
          category TEXT NOT NULL,
          source_unit TEXT NOT NULL CHECK (source_unit IN (
            'employment', 'consulting', 'salva', 'investment_radar',
            'investments', 'debt', 'house', 'family', 'other'
          )),
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          amount REAL NOT NULL CHECK (amount >= 0),
          description TEXT,
          fixed_expense_id INTEGER REFERENCES family_fixed_expenses (id) ON DELETE SET NULL,
          asset_id INTEGER REFERENCES family_assets (id) ON DELETE SET NULL,
          liability_id INTEGER REFERENCES family_liabilities (id) ON DELETE SET NULL,
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_family_cashflow_month_currency
        ON family_cashflow_entries (month, currency)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_family_cashflow_fixed_expense
        ON family_cashflow_entries (fixed_expense_id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS investment_cashflow_records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          month TEXT NOT NULL,
          account_name TEXT NOT NULL,
          strategy_type TEXT NOT NULL CHECK (strategy_type IN (
            'covered_call', 'dividend', 'interest', 'realized_gain',
            'realized_loss', 'other'
          )),
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          gross_income REAL NOT NULL DEFAULT 0,
          commissions REAL NOT NULL DEFAULT 0 CHECK (commissions >= 0),
          taxes REAL NOT NULL DEFAULT 0 CHECK (taxes >= 0),
          financing_cost REAL NOT NULL DEFAULT 0 CHECK (financing_cost >= 0),
          net_cashflow REAL NOT NULL DEFAULT 0,
          linked_asset_id INTEGER REFERENCES family_assets (id) ON DELETE SET NULL,
          fixed_expense_id INTEGER REFERENCES family_fixed_expenses (id) ON DELETE SET NULL,
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_inv_cf_month_currency
        ON investment_cashflow_records (month, currency)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leverage_records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          month TEXT NOT NULL,
          liability_id INTEGER REFERENCES family_liabilities (id) ON DELETE SET NULL,
          linked_asset_id INTEGER REFERENCES family_assets (id) ON DELETE SET NULL,
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD', 'UVA')),
          average_balance_used REAL NOT NULL DEFAULT 0 CHECK (average_balance_used >= 0),
          days_used INTEGER NOT NULL DEFAULT 0 CHECK (days_used >= 0),
          nominal_annual_rate REAL NOT NULL DEFAULT 0 CHECK (nominal_annual_rate >= 0),
          interest_paid REAL NOT NULL DEFAULT 0 CHECK (interest_paid >= 0),
          taxes_and_fees REAL NOT NULL DEFAULT 0 CHECK (taxes_and_fees >= 0),
          total_financing_cost REAL NOT NULL DEFAULT 0 CHECK (total_financing_cost >= 0),
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_leverage_month_currency
        ON leverage_records (month, currency)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capital_allocations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          month TEXT NOT NULL,
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          available_amount REAL NOT NULL CHECK (available_amount >= 0),
          destination TEXT NOT NULL CHECK (destination IN (
            'debt', 'investments', 'salva', 'investment_radar',
            'house', 'emergency_fund', 'cash', 'other'
          )),
          allocated_amount REAL NOT NULL CHECK (allocated_amount >= 0),
          status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN (
            'proposed', 'approved', 'executed', 'cancelled'
          )),
          policy_id INTEGER REFERENCES capital_policies (id) ON DELETE SET NULL,
          asset_id INTEGER REFERENCES family_assets (id) ON DELETE SET NULL,
          liability_id INTEGER REFERENCES family_liabilities (id) ON DELETE SET NULL,
          house_project_id INTEGER REFERENCES house_projects (id) ON DELETE SET NULL,
          rationale TEXT,
          expected_return REAL,
          expected_monthly_cashflow REAL,
          expected_hours_saved REAL,
          executed_date TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_capital_allocations_month_currency
        ON capital_allocations (month, currency, status)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS family_month_closures (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          month TEXT NOT NULL,
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          total_income REAL NOT NULL DEFAULT 0 CHECK (total_income >= 0),
          total_expenses REAL NOT NULL DEFAULT 0 CHECK (total_expenses >= 0),
          debt_service REAL NOT NULL DEFAULT 0 CHECK (debt_service >= 0),
          house_spending REAL NOT NULL DEFAULT 0 CHECK (house_spending >= 0),
          investment_contributions REAL NOT NULL DEFAULT 0
            CHECK (investment_contributions >= 0),
          scalable_income REAL NOT NULL DEFAULT 0 CHECK (scalable_income >= 0),
          free_cashflow REAL NOT NULL DEFAULT 0,
          amount_allocated REAL NOT NULL DEFAULT 0 CHECK (amount_allocated >= 0),
          unallocated_cash REAL NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'closed', 'reopened')),
          closed_at TEXT,
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE (month, currency)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_family_month_closures_month
        ON family_month_closures (month DESC, currency)
        """
    )

def _migrate_v8_to_v9(conn: sqlite3.Connection) -> None:
    """Family Office etapa 3: estados de caja, deudas, negocios, escenarios, import Cartera."""
    liab_cols = _liabilities_column_names(conn) if "family_liabilities" in {
        str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    } else set()
    for name, sql_type, default in [
        ("rate_type", "TEXT", "'unknown'"),
        ("current_installment", "REAL", "NULL"),
        ("total_financial_cost", "REAL", "NULL"),
        ("prepayment_cost", "REAL", "NULL"),
        ("allows_partial_prepayment", "INTEGER", "1"),
        ("maturity_date", "TEXT", "NULL"),
        ("priority_override", "INTEGER", "NULL"),
    ]:
        if name not in liab_cols:
            conn.execute(
                f"ALTER TABLE family_liabilities ADD COLUMN {name} {sql_type} DEFAULT {default}"
            )

    inv_cols = _inv_cf_column_names(conn)
    for name, sql_type, default in [
        ("cash_status", "TEXT", "'generated'"),
        ("generated_date", "TEXT", "NULL"),
        ("settlement_date", "TEXT", "NULL"),
        ("withdrawal_date", "TEXT", "NULL"),
        ("applied_date", "TEXT", "NULL"),
        ("source_type", "TEXT", "NULL"),
        ("source_id", "TEXT", "NULL"),
        ("imported_at", "TEXT", "NULL"),
    ]:
        if name not in inv_cols:
            conn.execute(
                f"ALTER TABLE investment_cashflow_records ADD COLUMN {name} {sql_type} DEFAULT {default}"
            )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_inv_cf_source
        ON investment_cashflow_records (source_type, source_id)
        WHERE source_type IS NOT NULL AND source_id IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_inv_cf_cash_status
        ON investment_cashflow_records (cash_status)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS investment_cashflow_status_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          investment_cashflow_id INTEGER NOT NULL
            REFERENCES investment_cashflow_records (id) ON DELETE CASCADE,
          from_status TEXT,
          to_status TEXT NOT NULL,
          changed_at TEXT NOT NULL DEFAULT (datetime('now')),
          notes TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_inv_cf_status_hist
        ON investment_cashflow_status_history (investment_cashflow_id, changed_at)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS business_units (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          unit_type TEXT NOT NULL CHECK (unit_type IN (
            'salva', 'consulting', 'investment_radar', 'other'
          )),
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_business_units_active ON business_units (is_active, unit_type)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS business_monthly_metrics (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          business_unit_id INTEGER NOT NULL REFERENCES business_units (id) ON DELETE CASCADE,
          month TEXT NOT NULL,
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          revenue REAL NOT NULL DEFAULT 0 CHECK (revenue >= 0),
          variable_costs REAL NOT NULL DEFAULT 0 CHECK (variable_costs >= 0),
          fixed_costs REAL NOT NULL DEFAULT 0 CHECK (fixed_costs >= 0),
          gross_profit REAL NOT NULL DEFAULT 0,
          operating_profit REAL NOT NULL DEFAULT 0,
          owner_hours REAL NOT NULL DEFAULT 0 CHECK (owner_hours >= 0),
          outsourced_hours REAL NOT NULL DEFAULT 0 CHECK (outsourced_hours >= 0),
          units_sold REAL,
          customers REAL,
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE (business_unit_id, month, currency)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_biz_metrics_unit_month
        ON business_monthly_metrics (business_unit_id, month DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS business_products (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          business_unit_id INTEGER NOT NULL REFERENCES business_units (id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          unit TEXT NOT NULL DEFAULT 'unit',
          sale_price REAL NOT NULL CHECK (sale_price >= 0),
          variable_cost REAL NOT NULL CHECK (variable_cost >= 0),
          gross_margin REAL NOT NULL DEFAULT 0,
          is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
          notes TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_products_unit ON business_products (business_unit_id, is_active)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS business_investment_cases (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          business_unit_id INTEGER NOT NULL REFERENCES business_units (id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          investment_amount REAL NOT NULL CHECK (investment_amount >= 0),
          investment_type TEXT NOT NULL CHECK (investment_type IN (
            'machinery', 'marketing', 'staff', 'working_capital',
            'automation', 'distribution', 'other'
          )),
          bottleneck TEXT NOT NULL CHECK (bottleneck IN (
            'production', 'sales', 'logistics', 'administration',
            'working_capital', 'founder_dependency', 'other'
          )),
          expected_monthly_revenue_increment REAL NOT NULL DEFAULT 0,
          expected_monthly_cost_increment REAL NOT NULL DEFAULT 0,
          expected_monthly_profit_increment REAL NOT NULL DEFAULT 0,
          expected_hours_saved REAL NOT NULL DEFAULT 0,
          expected_start_month TEXT,
          payback_months REAL,
          status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
            'draft', 'evaluating', 'approved', 'executed', 'rejected'
          )),
          assumptions TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_cases_unit ON business_investment_cases (business_unit_id, status)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capital_allocation_scenarios (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          month TEXT NOT NULL,
          currency TEXT NOT NULL CHECK (currency IN ('ARS', 'USD')),
          available_capital REAL NOT NULL CHECK (available_capital >= 0),
          destination_type TEXT NOT NULL CHECK (destination_type IN (
            'debt', 'portfolio', 'salva', 'investment_radar',
            'house', 'emergency_fund', 'cash'
          )),
          destination_id INTEGER,
          allocation_amount REAL NOT NULL CHECK (allocation_amount >= 0),
          expected_annual_return REAL,
          expected_monthly_cashflow REAL,
          expected_payback_months REAL,
          expected_hours_saved REAL,
          liquidity_score REAL NOT NULL DEFAULT 50
            CHECK (liquidity_score >= 0 AND liquidity_score <= 100),
          risk_score REAL NOT NULL DEFAULT 50
            CHECK (risk_score >= 0 AND risk_score <= 100),
          confidence TEXT NOT NULL DEFAULT 'low'
            CHECK (confidence IN ('low', 'medium', 'high')),
          assumptions TEXT,
          is_selected INTEGER NOT NULL DEFAULT 0 CHECK (is_selected IN (0, 1)),
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_alloc_scenarios_month
        ON capital_allocation_scenarios (month, currency)
        """
    )

def _ensure_family_office_tables(conn: sqlite3.Connection) -> None:
    """Idempotente: crea tablas FO faltantes y columna is_active en house_projects."""
    tables = {
        str(r[0])
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "family_assets" not in tables:
        _migrate_v6_to_v7(conn)
    if "family_fixed_expenses" not in tables:
        # Reutiliza la parte de tablas nuevas de v9 (tambi├®n repara snapshots/is_active).
        _migrate_v7_to_v8(conn)
    else:
        cols = _house_projects_column_names(conn) if "house_projects" in tables else set()
        if "house_projects" in tables and "is_active" not in cols:
            conn.execute(
                "ALTER TABLE house_projects ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_house_projects_active ON house_projects (is_active)"
            )
    if "business_units" not in tables:
        _migrate_v8_to_v9(conn)
    conn.commit()

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
        elif version < 7:
            _migrate_v6_to_v7(conn)
            version = 7
        elif version < 8:
            _migrate_v7_to_v8(conn)
            version = 8
        elif version < 9:
            _migrate_v8_to_v9(conn)
            version = 9
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
        _ensure_family_office_tables(conn)
        _apply_schema_if_needed(conn)
    finally:
        conn.close()
    return path
