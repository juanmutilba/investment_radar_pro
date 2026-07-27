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


def _norm(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in ("is_active", "is_selected"):
        if key in out and out[key] is not None:
            out[key] = bool(int(out[key]))
    return out


# --- Business units ---


def list_business_units(*, active_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM business_units"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY unit_type, name, id"
    with connection_scope() as conn:
        rows = conn.execute(sql).fetchall()
    return [_norm(row_as_mapping(r)) for r in rows]


def get_business_unit(unit_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute("SELECT * FROM business_units WHERE id = ?", (unit_id,)).fetchone()
    return _norm(row_as_mapping(r)) if r else None


def insert_business_unit(**fields: Any) -> int:
    ts = _now_iso()
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO business_units (
              name, unit_type, currency, is_active, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(fields["name"]).strip(),
                fields["unit_type"],
                str(fields["currency"]).upper(),
                _as_bool_int(fields.get("is_active", True), 1),
                (fields.get("notes") or "").strip() or None,
                ts,
                ts,
            ),
        )
        return int(cur.lastrowid)


def update_business_unit(unit_id: int, fields: dict[str, Any]) -> bool:
    existing = get_business_unit(unit_id)
    if existing is None:
        return False
    merged = {**existing, **fields}
    with connection_scope() as conn:
        cur = conn.execute(
            """
            UPDATE business_units SET
              name=?, unit_type=?, currency=?, is_active=?, notes=?, updated_at=?
            WHERE id=?
            """,
            (
                str(merged["name"]).strip(),
                merged["unit_type"],
                str(merged["currency"]).upper(),
                _as_bool_int(merged.get("is_active", True), 1),
                (merged.get("notes") or "").strip() or None,
                _now_iso(),
                unit_id,
            ),
        )
        return cur.rowcount > 0


def deactivate_business_unit(unit_id: int) -> bool:
    return update_business_unit(unit_id, {"is_active": False})


# --- Metrics ---


def list_metrics(unit_id: int, *, limit: int = 24) -> list[dict[str, Any]]:
    with connection_scope() as conn:
        rows = conn.execute(
            """
            SELECT * FROM business_monthly_metrics
            WHERE business_unit_id = ?
            ORDER BY month DESC, id DESC
            LIMIT ?
            """,
            (unit_id, max(1, min(limit, 120))),
        ).fetchall()
    return [row_as_mapping(r) for r in rows]


def upsert_metric(**fields: Any) -> int:
    ts = _now_iso()
    revenue = float(fields.get("revenue") or 0)
    variable_costs = float(fields.get("variable_costs") or 0)
    fixed_costs = float(fields.get("fixed_costs") or 0)
    gross = fields.get("gross_profit")
    if gross is None:
        gross = revenue - variable_costs
    op = fields.get("operating_profit")
    if op is None:
        op = float(gross) - fixed_costs
    unit_id = int(fields["business_unit_id"])
    month = str(fields["month"]).strip()[:7]
    currency = str(fields["currency"]).upper()
    with connection_scope() as conn:
        existing = conn.execute(
            """
            SELECT id FROM business_monthly_metrics
            WHERE business_unit_id=? AND month=? AND currency=?
            """,
            (unit_id, month, currency),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE business_monthly_metrics SET
                  revenue=?, variable_costs=?, fixed_costs=?, gross_profit=?,
                  operating_profit=?, owner_hours=?, outsourced_hours=?,
                  units_sold=?, customers=?, notes=?, updated_at=?
                WHERE id=?
                """,
                (
                    revenue, variable_costs, fixed_costs, float(gross), float(op),
                    float(fields.get("owner_hours") or 0),
                    float(fields.get("outsourced_hours") or 0),
                    fields.get("units_sold"),
                    fields.get("customers"),
                    (fields.get("notes") or "").strip() or None,
                    ts,
                    int(existing["id"]),
                ),
            )
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO business_monthly_metrics (
              business_unit_id, month, currency, revenue, variable_costs, fixed_costs,
              gross_profit, operating_profit, owner_hours, outsourced_hours,
              units_sold, customers, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                unit_id, month, currency, revenue, variable_costs, fixed_costs,
                float(gross), float(op),
                float(fields.get("owner_hours") or 0),
                float(fields.get("outsourced_hours") or 0),
                fields.get("units_sold"),
                fields.get("customers"),
                (fields.get("notes") or "").strip() or None,
                ts, ts,
            ),
        )
        return int(cur.lastrowid)


def delete_metric(metric_id: int) -> bool:
    with connection_scope() as conn:
        cur = conn.execute("DELETE FROM business_monthly_metrics WHERE id=?", (metric_id,))
        return cur.rowcount > 0


# --- Products ---


def list_products(unit_id: int, *, active_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM business_products WHERE business_unit_id=?"
    params: list[Any] = [unit_id]
    if active_only:
        sql += " AND is_active=1"
    sql += " ORDER BY name, id"
    with connection_scope() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_norm(row_as_mapping(r)) for r in rows]


def insert_product(**fields: Any) -> int:
    ts = _now_iso()
    sale = float(fields["sale_price"])
    varc = float(fields["variable_cost"])
    margin = fields.get("gross_margin")
    if margin is None:
        margin = sale - varc
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO business_products (
              business_unit_id, name, unit, sale_price, variable_cost, gross_margin,
              is_active, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(fields["business_unit_id"]),
                str(fields["name"]).strip(),
                str(fields.get("unit") or "unit").strip(),
                sale, varc, float(margin),
                _as_bool_int(fields.get("is_active", True), 1),
                (fields.get("notes") or "").strip() or None,
                ts, ts,
            ),
        )
        return int(cur.lastrowid)


def update_product(product_id: int, fields: dict[str, Any]) -> bool:
    with connection_scope() as conn:
        existing = conn.execute(
            "SELECT * FROM business_products WHERE id=?", (product_id,)
        ).fetchone()
    if existing is None:
        return False
    merged = {**row_as_mapping(existing), **fields}
    sale = float(merged["sale_price"])
    varc = float(merged["variable_cost"])
    margin = merged.get("gross_margin")
    if "sale_price" in fields or "variable_cost" in fields or margin is None:
        margin = sale - varc
    with connection_scope() as conn:
        cur = conn.execute(
            """
            UPDATE business_products SET
              name=?, unit=?, sale_price=?, variable_cost=?, gross_margin=?,
              is_active=?, notes=?, updated_at=?
            WHERE id=?
            """,
            (
                str(merged["name"]).strip(),
                str(merged.get("unit") or "unit"),
                sale, varc, float(margin),
                _as_bool_int(merged.get("is_active", True), 1),
                (merged.get("notes") or "").strip() or None,
                _now_iso(),
                product_id,
            ),
        )
        return cur.rowcount > 0


def deactivate_product(product_id: int) -> bool:
    return update_product(product_id, {"is_active": False})


# --- Investment cases ---


def list_investment_cases(unit_id: int) -> list[dict[str, Any]]:
    with connection_scope() as conn:
        rows = conn.execute(
            """
            SELECT * FROM business_investment_cases
            WHERE business_unit_id=?
            ORDER BY id DESC
            """,
            (unit_id,),
        ).fetchall()
    return [row_as_mapping(r) for r in rows]


def compute_payback_months(investment_amount: float, monthly_profit_increment: float) -> float | None:
    if monthly_profit_increment <= 0:
        return None
    return float(investment_amount) / float(monthly_profit_increment)


def insert_investment_case(**fields: Any) -> int:
    ts = _now_iso()
    amount = float(fields["investment_amount"])
    profit_inc = float(fields.get("expected_monthly_profit_increment") or 0)
    payback = fields.get("payback_months")
    if payback is None:
        payback = compute_payback_months(amount, profit_inc)
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO business_investment_cases (
              business_unit_id, name, currency, investment_amount, investment_type,
              bottleneck, expected_monthly_revenue_increment, expected_monthly_cost_increment,
              expected_monthly_profit_increment, expected_hours_saved, expected_start_month,
              payback_months, status, assumptions, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(fields["business_unit_id"]),
                str(fields["name"]).strip(),
                str(fields["currency"]).upper(),
                amount,
                fields["investment_type"],
                fields["bottleneck"],
                float(fields.get("expected_monthly_revenue_increment") or 0),
                float(fields.get("expected_monthly_cost_increment") or 0),
                profit_inc,
                float(fields.get("expected_hours_saved") or 0),
                fields.get("expected_start_month"),
                None if payback is None else float(payback),
                fields.get("status") or "draft",
                fields.get("assumptions"),
                ts, ts,
            ),
        )
        return int(cur.lastrowid)


def update_investment_case(case_id: int, fields: dict[str, Any]) -> bool:
    with connection_scope() as conn:
        existing = conn.execute(
            "SELECT * FROM business_investment_cases WHERE id=?", (case_id,)
        ).fetchone()
    if existing is None:
        return False
    merged = {**row_as_mapping(existing), **fields}
    amount = float(merged["investment_amount"])
    profit_inc = float(merged.get("expected_monthly_profit_increment") or 0)
    if "payback_months" not in fields or fields.get("payback_months") is None:
        merged["payback_months"] = compute_payback_months(amount, profit_inc)
    with connection_scope() as conn:
        cur = conn.execute(
            """
            UPDATE business_investment_cases SET
              name=?, currency=?, investment_amount=?, investment_type=?, bottleneck=?,
              expected_monthly_revenue_increment=?, expected_monthly_cost_increment=?,
              expected_monthly_profit_increment=?, expected_hours_saved=?,
              expected_start_month=?, payback_months=?, status=?, assumptions=?, updated_at=?
            WHERE id=?
            """,
            (
                str(merged["name"]).strip(),
                str(merged["currency"]).upper(),
                amount,
                merged["investment_type"],
                merged["bottleneck"],
                float(merged.get("expected_monthly_revenue_increment") or 0),
                float(merged.get("expected_monthly_cost_increment") or 0),
                profit_inc,
                float(merged.get("expected_hours_saved") or 0),
                merged.get("expected_start_month"),
                None if merged.get("payback_months") is None else float(merged["payback_months"]),
                merged.get("status") or "draft",
                merged.get("assumptions"),
                _now_iso(),
                case_id,
            ),
        )
        return cur.rowcount > 0


def delete_investment_case(case_id: int) -> bool:
    with connection_scope() as conn:
        cur = conn.execute("DELETE FROM business_investment_cases WHERE id=?", (case_id,))
        return cur.rowcount > 0


# --- Allocation scenarios ---


def list_scenarios(*, month: str | None = None, currency: str | None = None) -> list[dict[str, Any]]:
    parts: list[str] = []
    params: list[Any] = []
    if month:
        parts.append("month=?"); params.append(month.strip()[:7])
    if currency:
        parts.append("upper(currency)=?"); params.append(currency.upper())
    sql = "SELECT * FROM capital_allocation_scenarios"
    if parts:
        sql += " WHERE " + " AND ".join(parts)
    sql += " ORDER BY id DESC"
    with connection_scope() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_norm(row_as_mapping(r)) for r in rows]


def get_scenario(scenario_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute(
            "SELECT * FROM capital_allocation_scenarios WHERE id=?", (scenario_id,)
        ).fetchone()
    return _norm(row_as_mapping(r)) if r else None


def insert_scenario(**fields: Any) -> int:
    ts = _now_iso()
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO capital_allocation_scenarios (
              name, month, currency, available_capital, destination_type, destination_id,
              allocation_amount, expected_annual_return, expected_monthly_cashflow,
              expected_payback_months, expected_hours_saved, liquidity_score, risk_score,
              confidence, assumptions, is_selected, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(fields["name"]).strip(),
                str(fields["month"]).strip()[:7],
                str(fields["currency"]).upper(),
                float(fields["available_capital"]),
                fields["destination_type"],
                fields.get("destination_id"),
                float(fields["allocation_amount"]),
                fields.get("expected_annual_return"),
                fields.get("expected_monthly_cashflow"),
                fields.get("expected_payback_months"),
                fields.get("expected_hours_saved"),
                float(fields.get("liquidity_score") if fields.get("liquidity_score") is not None else 50),
                float(fields.get("risk_score") if fields.get("risk_score") is not None else 50),
                fields.get("confidence") or "low",
                fields.get("assumptions"),
                _as_bool_int(fields.get("is_selected", False)),
                ts, ts,
            ),
        )
        return int(cur.lastrowid)


def update_scenario(scenario_id: int, fields: dict[str, Any]) -> bool:
    existing = get_scenario(scenario_id)
    if existing is None:
        return False
    merged = {**existing, **fields}
    with connection_scope() as conn:
        cur = conn.execute(
            """
            UPDATE capital_allocation_scenarios SET
              name=?, month=?, currency=?, available_capital=?, destination_type=?,
              destination_id=?, allocation_amount=?, expected_annual_return=?,
              expected_monthly_cashflow=?, expected_payback_months=?, expected_hours_saved=?,
              liquidity_score=?, risk_score=?, confidence=?, assumptions=?,
              is_selected=?, updated_at=?
            WHERE id=?
            """,
            (
                str(merged["name"]).strip(),
                str(merged["month"]).strip()[:7],
                str(merged["currency"]).upper(),
                float(merged["available_capital"]),
                merged["destination_type"],
                merged.get("destination_id"),
                float(merged["allocation_amount"]),
                merged.get("expected_annual_return"),
                merged.get("expected_monthly_cashflow"),
                merged.get("expected_payback_months"),
                merged.get("expected_hours_saved"),
                float(merged.get("liquidity_score") if merged.get("liquidity_score") is not None else 50),
                float(merged.get("risk_score") if merged.get("risk_score") is not None else 50),
                merged.get("confidence") or "low",
                merged.get("assumptions"),
                _as_bool_int(merged.get("is_selected", False)),
                _now_iso(),
                scenario_id,
            ),
        )
        return cur.rowcount > 0


def delete_scenario(scenario_id: int) -> bool:
    with connection_scope() as conn:
        cur = conn.execute(
            "DELETE FROM capital_allocation_scenarios WHERE id=?", (scenario_id,)
        )
        return cur.rowcount > 0
