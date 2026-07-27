from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from persistence.sqlite.connection import connection_scope


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_as_mapping(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _as_bool_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    if isinstance(v, bool):
        return 1 if v else 0
    try:
        return 1 if int(v) else 0
    except (TypeError, ValueError):
        return default


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in ("generates_cashflow", "is_active", "is_mandatory", "allows_partial_prepayment"):
        if key in out and out[key] is not None:
            out[key] = bool(int(out[key]))
    return out


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


def list_assets(*, active_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM family_assets"
    params: list[Any] = []
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY currency, category, name, id"
    with connection_scope() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_normalize_row(row_as_mapping(r)) for r in rows]


def get_asset(asset_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute("SELECT * FROM family_assets WHERE id = ?", (asset_id,)).fetchone()
    return _normalize_row(row_as_mapping(r)) if r else None


def insert_asset(
    *,
    name: str,
    category: str,
    ownership_status: str,
    currency: str,
    estimated_value: float,
    valuation_date: str,
    liquidity: str,
    generates_cashflow: bool = False,
    monthly_cashflow: float = 0.0,
    notes: str | None = None,
    is_active: bool = True,
) -> int:
    ts = _now_iso()
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO family_assets (
              name, category, ownership_status, currency, estimated_value,
              valuation_date, liquidity, generates_cashflow, monthly_cashflow,
              notes, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                category,
                ownership_status,
                currency.upper(),
                float(estimated_value),
                valuation_date.strip()[:32],
                liquidity,
                _as_bool_int(generates_cashflow),
                float(monthly_cashflow or 0),
                (notes or "").strip() or None,
                _as_bool_int(is_active, 1),
                ts,
                ts,
            ),
        )
        return int(cur.lastrowid)


def update_asset(asset_id: int, fields: dict[str, Any]) -> bool:
    allowed = {
        "name",
        "category",
        "ownership_status",
        "currency",
        "estimated_value",
        "valuation_date",
        "liquidity",
        "generates_cashflow",
        "monthly_cashflow",
        "notes",
        "is_active",
    }
    cols: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed or value is None and key not in ("notes",):
            if key not in allowed:
                continue
        if key == "name" and value is not None:
            cols.append("name = ?")
            params.append(str(value).strip())
        elif key == "category" and value is not None:
            cols.append("category = ?")
            params.append(value)
        elif key == "ownership_status" and value is not None:
            cols.append("ownership_status = ?")
            params.append(value)
        elif key == "currency" and value is not None:
            cols.append("currency = ?")
            params.append(str(value).upper())
        elif key == "estimated_value" and value is not None:
            cols.append("estimated_value = ?")
            params.append(float(value))
        elif key == "valuation_date" and value is not None:
            cols.append("valuation_date = ?")
            params.append(str(value).strip()[:32])
        elif key == "liquidity" and value is not None:
            cols.append("liquidity = ?")
            params.append(value)
        elif key == "generates_cashflow" and value is not None:
            cols.append("generates_cashflow = ?")
            params.append(_as_bool_int(value))
        elif key == "monthly_cashflow" and value is not None:
            cols.append("monthly_cashflow = ?")
            params.append(float(value))
        elif key == "notes":
            cols.append("notes = ?")
            params.append((str(value).strip() if value is not None else "") or None)
        elif key == "is_active" and value is not None:
            cols.append("is_active = ?")
            params.append(_as_bool_int(value))
    if not cols:
        return False
    cols.append("updated_at = ?")
    params.append(_now_iso())
    params.append(asset_id)
    with connection_scope() as conn:
        cur = conn.execute(
            "UPDATE family_assets SET " + ", ".join(cols) + " WHERE id = ?",
            params,
        )
        return cur.rowcount > 0


def deactivate_asset(asset_id: int) -> bool:
    return update_asset(asset_id, {"is_active": False})


# ---------------------------------------------------------------------------
# Liabilities
# ---------------------------------------------------------------------------


def list_liabilities(*, active_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM family_liabilities"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY currency, liability_type, name, id"
    with connection_scope() as conn:
        rows = conn.execute(sql).fetchall()
    return [_normalize_row(row_as_mapping(r)) for r in rows]


def get_liability(liability_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute(
            "SELECT * FROM family_liabilities WHERE id = ?",
            (liability_id,),
        ).fetchone()
    return _normalize_row(row_as_mapping(r)) if r else None


def insert_liability(
    *,
    name: str,
    liability_type: str,
    currency: str,
    original_amount: float,
    outstanding_balance: float,
    installment_amount: float = 0.0,
    installments_remaining: int = 0,
    nominal_annual_rate: float = 0.0,
    effective_annual_cost: float | None = None,
    next_due_date: str | None = None,
    linked_asset_id: int | None = None,
    notes: str | None = None,
    is_active: bool = True,
    rate_type: str = "unknown",
    current_installment: float | None = None,
    total_financial_cost: float | None = None,
    prepayment_cost: float | None = None,
    allows_partial_prepayment: bool = True,
    maturity_date: str | None = None,
    priority_override: int | None = None,
) -> int:
    ts = _now_iso()
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO family_liabilities (
              name, liability_type, currency, original_amount, outstanding_balance,
              installment_amount, installments_remaining, nominal_annual_rate,
              effective_annual_cost, next_due_date, linked_asset_id,
              rate_type, current_installment, total_financial_cost, prepayment_cost,
              allows_partial_prepayment, maturity_date, priority_override,
              notes, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                liability_type,
                currency.upper(),
                float(original_amount),
                float(outstanding_balance),
                float(installment_amount or 0),
                int(installments_remaining or 0),
                float(nominal_annual_rate or 0),
                None if effective_annual_cost is None else float(effective_annual_cost),
                (next_due_date or "").strip()[:32] or None,
                linked_asset_id,
                rate_type or "unknown",
                None if current_installment is None else float(current_installment),
                None if total_financial_cost is None else float(total_financial_cost),
                None if prepayment_cost is None else float(prepayment_cost),
                _as_bool_int(allows_partial_prepayment, 1),
                (maturity_date or "").strip()[:32] or None,
                priority_override,
                (notes or "").strip() or None,
                _as_bool_int(is_active, 1),
                ts,
                ts,
            ),
        )
        return int(cur.lastrowid)


def update_liability(liability_id: int, fields: dict[str, Any]) -> bool:
    allowed = {
        "name",
        "liability_type",
        "currency",
        "original_amount",
        "outstanding_balance",
        "installment_amount",
        "installments_remaining",
        "nominal_annual_rate",
        "effective_annual_cost",
        "next_due_date",
        "linked_asset_id",
        "notes",
        "is_active",
        "rate_type",
        "current_installment",
        "total_financial_cost",
        "prepayment_cost",
        "allows_partial_prepayment",
        "maturity_date",
        "priority_override",
    }
    cols: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "name" and value is not None:
            cols.append("name = ?")
            params.append(str(value).strip())
        elif key in ("liability_type", "rate_type") and value is not None:
            cols.append(f"{key} = ?")
            params.append(value)
        elif key == "currency" and value is not None:
            cols.append("currency = ?")
            params.append(str(value).upper())
        elif key in (
            "original_amount",
            "outstanding_balance",
            "installment_amount",
            "nominal_annual_rate",
        ) and value is not None:
            cols.append(f"{key} = ?")
            params.append(float(value))
        elif key == "installments_remaining" and value is not None:
            cols.append("installments_remaining = ?")
            params.append(int(value))
        elif key in ("effective_annual_cost", "current_installment", "total_financial_cost", "prepayment_cost"):
            cols.append(f"{key} = ?")
            params.append(None if value is None else float(value))
        elif key in ("next_due_date", "maturity_date"):
            cols.append(f"{key} = ?")
            params.append((str(value).strip()[:32] if value else "") or None)
        elif key == "linked_asset_id":
            cols.append("linked_asset_id = ?")
            params.append(value)
        elif key == "priority_override":
            cols.append("priority_override = ?")
            params.append(None if value is None else int(value))
        elif key == "allows_partial_prepayment" and value is not None:
            cols.append("allows_partial_prepayment = ?")
            params.append(_as_bool_int(value))
        elif key == "notes":
            cols.append("notes = ?")
            params.append((str(value).strip() if value is not None else "") or None)
        elif key == "is_active" and value is not None:
            cols.append("is_active = ?")
            params.append(_as_bool_int(value))
    if not cols:
        return False
    cols.append("updated_at = ?")
    params.append(_now_iso())
    params.append(liability_id)
    with connection_scope() as conn:
        cur = conn.execute(
            "UPDATE family_liabilities SET " + ", ".join(cols) + " WHERE id = ?",
            params,
        )
        return cur.rowcount > 0


def deactivate_liability(liability_id: int) -> bool:
    return update_liability(liability_id, {"is_active": False})


# ---------------------------------------------------------------------------
# Capital policies
# ---------------------------------------------------------------------------


def list_policies(*, active_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM capital_policies"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY priority ASC, id ASC"
    with connection_scope() as conn:
        rows = conn.execute(sql).fetchall()
    return [_normalize_row(row_as_mapping(r)) for r in rows]


def get_policy(policy_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute("SELECT * FROM capital_policies WHERE id = ?", (policy_id,)).fetchone()
    return _normalize_row(row_as_mapping(r)) if r else None


def insert_policy(
    *,
    name: str,
    destination: str,
    minimum_monthly_amount: float | None = None,
    maximum_monthly_amount: float | None = None,
    priority: int = 0,
    is_mandatory: bool = False,
    notes: str | None = None,
    is_active: bool = True,
) -> int:
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO capital_policies (
              name, destination, minimum_monthly_amount, maximum_monthly_amount,
              priority, is_mandatory, notes, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                destination,
                None if minimum_monthly_amount is None else float(minimum_monthly_amount),
                None if maximum_monthly_amount is None else float(maximum_monthly_amount),
                int(priority),
                _as_bool_int(is_mandatory),
                (notes or "").strip() or None,
                _as_bool_int(is_active, 1),
            ),
        )
        return int(cur.lastrowid)


def update_policy(policy_id: int, fields: dict[str, Any]) -> bool:
    allowed = {
        "name",
        "destination",
        "minimum_monthly_amount",
        "maximum_monthly_amount",
        "priority",
        "is_mandatory",
        "notes",
        "is_active",
    }
    cols: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "name" and value is not None:
            cols.append("name = ?")
            params.append(str(value).strip())
        elif key == "destination" and value is not None:
            cols.append("destination = ?")
            params.append(value)
        elif key in ("minimum_monthly_amount", "maximum_monthly_amount"):
            cols.append(f"{key} = ?")
            params.append(None if value is None else float(value))
        elif key == "priority" and value is not None:
            cols.append("priority = ?")
            params.append(int(value))
        elif key == "is_mandatory" and value is not None:
            cols.append("is_mandatory = ?")
            params.append(_as_bool_int(value))
        elif key == "notes":
            cols.append("notes = ?")
            params.append((str(value).strip() if value is not None else "") or None)
        elif key == "is_active" and value is not None:
            cols.append("is_active = ?")
            params.append(_as_bool_int(value))
    if not cols:
        return False
    params.append(policy_id)
    with connection_scope() as conn:
        cur = conn.execute(
            "UPDATE capital_policies SET " + ", ".join(cols) + " WHERE id = ?",
            params,
        )
        return cur.rowcount > 0


def deactivate_policy(policy_id: int) -> bool:
    return update_policy(policy_id, {"is_active": False})


# ---------------------------------------------------------------------------
# House projects
# ---------------------------------------------------------------------------


def list_house_projects(*, active_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM house_projects"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += """
            ORDER BY
              CASE status
                WHEN 'in_progress' THEN 0
                WHEN 'approved' THEN 1
                WHEN 'planned' THEN 2
                WHEN 'paused' THEN 3
                ELSE 4
              END,
              id DESC
            """
    with connection_scope() as conn:
        rows = conn.execute(sql).fetchall()
    return [_normalize_row(row_as_mapping(r)) for r in rows]


def get_house_project(project_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute("SELECT * FROM house_projects WHERE id = ?", (project_id,)).fetchone()
    return _normalize_row(row_as_mapping(r)) if r else None


def insert_house_project(
    *,
    name: str,
    priority: str,
    estimated_cost: float,
    paid_amount: float = 0.0,
    currency: str,
    target_date: str | None = None,
    status: str = "planned",
    notes: str | None = None,
    is_active: bool = True,
) -> int:
    ts = _now_iso()
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO house_projects (
              name, priority, estimated_cost, paid_amount, currency,
              target_date, status, notes, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                priority,
                float(estimated_cost),
                float(paid_amount or 0),
                currency.upper(),
                (target_date or "").strip()[:32] or None,
                status,
                (notes or "").strip() or None,
                _as_bool_int(is_active, 1),
                ts,
                ts,
            ),
        )
        return int(cur.lastrowid)


def update_house_project(project_id: int, fields: dict[str, Any]) -> bool:
    allowed = {
        "name",
        "priority",
        "estimated_cost",
        "paid_amount",
        "currency",
        "target_date",
        "status",
        "notes",
        "is_active",
    }
    cols: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "name" and value is not None:
            cols.append("name = ?")
            params.append(str(value).strip())
        elif key in ("priority", "status") and value is not None:
            cols.append(f"{key} = ?")
            params.append(value)
        elif key in ("estimated_cost", "paid_amount") and value is not None:
            cols.append(f"{key} = ?")
            params.append(float(value))
        elif key == "currency" and value is not None:
            cols.append("currency = ?")
            params.append(str(value).upper())
        elif key == "target_date":
            cols.append("target_date = ?")
            params.append((str(value).strip()[:32] if value else "") or None)
        elif key == "notes":
            cols.append("notes = ?")
            params.append((str(value).strip() if value is not None else "") or None)
        elif key == "is_active" and value is not None:
            cols.append("is_active = ?")
            params.append(_as_bool_int(value))
    if not cols:
        return False
    cols.append("updated_at = ?")
    params.append(_now_iso())
    params.append(project_id)
    with connection_scope() as conn:
        cur = conn.execute(
            "UPDATE house_projects SET " + ", ".join(cols) + " WHERE id = ?",
            params,
        )
        return cur.rowcount > 0


def deactivate_house_project(project_id: int) -> bool:
    return update_house_project(project_id, {"is_active": False})


def delete_house_project(project_id: int) -> bool:
    """Soft-delete (is_active=0). Conservado el nombre por compatibilidad API."""
    return deactivate_house_project(project_id)


# ---------------------------------------------------------------------------
# Monthly snapshots
# ---------------------------------------------------------------------------


def list_snapshots(*, limit: int = 24) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit or 24), 120))
    with connection_scope() as conn:
        rows = conn.execute(
            """
            SELECT * FROM family_office_monthly_snapshots
            ORDER BY month DESC, currency ASC, id DESC
            LIMIT ?
            """,
            (lim,),
        ).fetchall()
    return [row_as_mapping(r) for r in rows]


def get_latest_snapshot() -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute(
            """
            SELECT * FROM family_office_monthly_snapshots
            ORDER BY month DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    return row_as_mapping(r) if r else None


def get_snapshot_by_month(month: str, currency: str | None = None) -> dict[str, Any] | None:
    m = month.strip()[:7]
    with connection_scope() as conn:
        if currency:
            r = conn.execute(
                """
                SELECT * FROM family_office_monthly_snapshots
                WHERE month = ? AND upper(currency) = ?
                """,
                (m, currency.upper()),
            ).fetchone()
        else:
            r = conn.execute(
                "SELECT * FROM family_office_monthly_snapshots WHERE month = ? ORDER BY id DESC",
                (m,),
            ).fetchone()
    return row_as_mapping(r) if r else None


def upsert_snapshot(
    *,
    month: str,
    active_income: float = 0.0,
    consulting_income: float = 0.0,
    scalable_income: float = 0.0,
    fixed_expenses: float = 0.0,
    debt_payments: float = 0.0,
    house_spending: float = 0.0,
    investment_contributions: float = 0.0,
    free_cashflow: float | None = None,
    currency: str = "ARS",
    notes: str | None = None,
) -> int:
    ts = _now_iso()
    m = month.strip()[:7]
    cur = (currency or "ARS").upper()
    computed_fcf = (
        float(active_income or 0)
        + float(consulting_income or 0)
        + float(scalable_income or 0)
        - float(fixed_expenses or 0)
        - float(debt_payments or 0)
        - float(house_spending or 0)
        - float(investment_contributions or 0)
    )
    fcf = computed_fcf if free_cashflow is None else float(free_cashflow)
    existing = get_snapshot_by_month(m, cur)
    if existing:
        with connection_scope() as conn:
            conn.execute(
                """
                UPDATE family_office_monthly_snapshots SET
                  active_income = ?, consulting_income = ?, scalable_income = ?,
                  fixed_expenses = ?, debt_payments = ?, house_spending = ?,
                  investment_contributions = ?, free_cashflow = ?, currency = ?,
                  notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    float(active_income or 0),
                    float(consulting_income or 0),
                    float(scalable_income or 0),
                    float(fixed_expenses or 0),
                    float(debt_payments or 0),
                    float(house_spending or 0),
                    float(investment_contributions or 0),
                    fcf,
                    cur,
                    (notes or "").strip() or None,
                    ts,
                    int(existing["id"]),
                ),
            )
        return int(existing["id"])
    with connection_scope() as conn:
        cur_sql = conn.execute(
            """
            INSERT INTO family_office_monthly_snapshots (
              month, active_income, consulting_income, scalable_income,
              fixed_expenses, debt_payments, house_spending,
              investment_contributions, free_cashflow, currency, notes,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m,
                float(active_income or 0),
                float(consulting_income or 0),
                float(scalable_income or 0),
                float(fixed_expenses or 0),
                float(debt_payments or 0),
                float(house_spending or 0),
                float(investment_contributions or 0),
                fcf,
                cur,
                (notes or "").strip() or None,
                ts,
                ts,
            ),
        )
        return int(cur_sql.lastrowid)
