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
    for key in ("is_active", "is_essential"):
        if key in out and out[key] is not None:
            out[key] = bool(int(out[key]))
    return out


ACTIVE_ALLOCATION_STATUSES = ("proposed", "approved", "executed")


# ---------------------------------------------------------------------------
# Fixed expenses
# ---------------------------------------------------------------------------


def list_fixed_expenses(*, active_only: bool = True, currency: str | None = None) -> list[dict[str, Any]]:
    parts: list[str] = []
    params: list[Any] = []
    if active_only:
        parts.append("is_active = 1")
    if currency:
        parts.append("upper(currency) = ?")
        params.append(currency.upper())
    sql = "SELECT * FROM family_fixed_expenses"
    if parts:
        sql += " WHERE " + " AND ".join(parts)
    sql += " ORDER BY coverage_order ASC, priority ASC, id ASC"
    with connection_scope() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_normalize_row(row_as_mapping(r)) for r in rows]


def get_fixed_expense(expense_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute(
            "SELECT * FROM family_fixed_expenses WHERE id = ?", (expense_id,)
        ).fetchone()
    return _normalize_row(row_as_mapping(r)) if r else None


def insert_fixed_expense(**fields: Any) -> int:
    ts = _now_iso()
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO family_fixed_expenses (
              name, category, currency, expected_monthly_amount, priority,
              coverage_order, is_essential, notes, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(fields["name"]).strip(),
                fields["category"],
                str(fields["currency"]).upper(),
                float(fields["expected_monthly_amount"]),
                int(fields.get("priority") or 0),
                int(fields.get("coverage_order") or 0),
                _as_bool_int(fields.get("is_essential", True), 1),
                (fields.get("notes") or "").strip() or None if fields.get("notes") is not None else None,
                _as_bool_int(fields.get("is_active", True), 1),
                ts,
                ts,
            ),
        )
        return int(cur.lastrowid)


def update_fixed_expense(expense_id: int, fields: dict[str, Any]) -> bool:
    allowed = {
        "name", "category", "currency", "expected_monthly_amount", "priority",
        "coverage_order", "is_essential", "notes", "is_active",
    }
    cols: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "name" and value is not None:
            cols.append("name = ?"); params.append(str(value).strip())
        elif key in ("category",) and value is not None:
            cols.append(f"{key} = ?"); params.append(value)
        elif key == "currency" and value is not None:
            cols.append("currency = ?"); params.append(str(value).upper())
        elif key == "expected_monthly_amount" and value is not None:
            cols.append("expected_monthly_amount = ?"); params.append(float(value))
        elif key in ("priority", "coverage_order") and value is not None:
            cols.append(f"{key} = ?"); params.append(int(value))
        elif key in ("is_essential", "is_active") and value is not None:
            cols.append(f"{key} = ?"); params.append(_as_bool_int(value))
        elif key == "notes":
            cols.append("notes = ?")
            params.append((str(value).strip() if value is not None else "") or None)
    if not cols:
        return False
    cols.append("updated_at = ?"); params.append(_now_iso()); params.append(expense_id)
    with connection_scope() as conn:
        cur = conn.execute(
            "UPDATE family_fixed_expenses SET " + ", ".join(cols) + " WHERE id = ?",
            params,
        )
        return cur.rowcount > 0


def deactivate_fixed_expense(expense_id: int) -> bool:
    return update_fixed_expense(expense_id, {"is_active": False})


# ---------------------------------------------------------------------------
# Cashflow entries
# ---------------------------------------------------------------------------


def list_cashflow_entries(
    *, month: str | None = None, currency: str | None = None
) -> list[dict[str, Any]]:
    parts: list[str] = []
    params: list[Any] = []
    if month:
        parts.append("month = ?"); params.append(month.strip()[:7])
    if currency:
        parts.append("upper(currency) = ?"); params.append(currency.upper())
    sql = "SELECT * FROM family_cashflow_entries"
    if parts:
        sql += " WHERE " + " AND ".join(parts)
    sql += " ORDER BY date DESC, id DESC"
    with connection_scope() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row_as_mapping(r) for r in rows]


def get_cashflow_entry(entry_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute(
            "SELECT * FROM family_cashflow_entries WHERE id = ?", (entry_id,)
        ).fetchone()
    return row_as_mapping(r) if r else None




def insert_cashflow_entry(**fields: Any) -> int:
    ts = _now_iso()
    date_s = str(fields["date"]).strip()[:32]
    month = (fields.get("month") or date_s[:7]).strip()[:7]
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO family_cashflow_entries (
              date, month, entry_type, category, source_unit, currency, amount,
              description, fixed_expense_id, asset_id, liability_id, notes,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                date_s,
                month,
                fields["entry_type"],
                str(fields["category"]).strip(),
                fields["source_unit"],
                str(fields["currency"]).upper(),
                float(fields["amount"]),
                (fields.get("description") or "").strip() or None,
                fields.get("fixed_expense_id"),
                fields.get("asset_id"),
                fields.get("liability_id"),
                (fields.get("notes") or "").strip() or None if fields.get("notes") is not None else None,
                ts,
                ts,
            ),
        )
        return int(cur.lastrowid)


def update_cashflow_entry(entry_id: int, fields: dict[str, Any]) -> bool:
    allowed = {
        "date", "month", "entry_type", "category", "source_unit", "currency",
        "amount", "description", "fixed_expense_id",
        "asset_id", "liability_id", "notes",
    }
    cols: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key in ("date", "month") and value is not None:
            cols.append(f"{key} = ?")
            params.append(str(value).strip()[:32] if key == "date" else str(value).strip()[:7])
        elif key in ("entry_type", "source_unit", "category") and value is not None:
            cols.append(f"{key} = ?"); params.append(value if key != "category" else str(value).strip())
        elif key == "currency" and value is not None:
            cols.append("currency = ?"); params.append(str(value).upper())
        elif key == "amount" and value is not None:
            cols.append("amount = ?"); params.append(float(value))
        elif key in ("description", "notes"):
            cols.append(f"{key} = ?")
            params.append((str(value).strip() if value is not None else "") or None)
        elif key in ("fixed_expense_id", "asset_id", "liability_id"):
            cols.append(f"{key} = ?"); params.append(value)
    if not cols:
        return False
    cols.append("updated_at = ?"); params.append(_now_iso()); params.append(entry_id)
    with connection_scope() as conn:
        cur = conn.execute(
            "UPDATE family_cashflow_entries SET " + ", ".join(cols) + " WHERE id = ?",
            params,
        )
        return cur.rowcount > 0


def delete_cashflow_entry(entry_id: int) -> bool:
    with connection_scope() as conn:
        cur = conn.execute("DELETE FROM family_cashflow_entries WHERE id = ?", (entry_id,))
        return cur.rowcount > 0

# ---------------------------------------------------------------------------
# Investment cashflow
# ---------------------------------------------------------------------------


def compute_net_cashflow(
    gross_income: float, commissions: float, taxes: float, financing_cost: float
) -> float:
    return float(gross_income or 0) - float(commissions or 0) - float(taxes or 0) - float(financing_cost or 0)


def list_investment_cashflows(
    *, month: str | None = None, currency: str | None = None
) -> list[dict[str, Any]]:
    parts: list[str] = []
    params: list[Any] = []
    if month:
        parts.append("month = ?"); params.append(month.strip()[:7])
    if currency:
        parts.append("upper(currency) = ?"); params.append(currency.upper())
    sql = "SELECT * FROM investment_cashflow_records"
    if parts:
        sql += " WHERE " + " AND ".join(parts)
    sql += " ORDER BY month DESC, id DESC"
    with connection_scope() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row_as_mapping(r) for r in rows]


def get_investment_cashflow(record_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute(
            "SELECT * FROM investment_cashflow_records WHERE id = ?", (record_id,)
        ).fetchone()
    return row_as_mapping(r) if r else None


def get_investment_cashflow_by_source(
    source_type: str, source_id: str
) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute(
            """
            SELECT * FROM investment_cashflow_records
            WHERE source_type = ? AND source_id = ?
            LIMIT 1
            """,
            (source_type, source_id),
        ).fetchone()
    return row_as_mapping(r) if r else None


def list_status_history(investment_cashflow_id: int) -> list[dict[str, Any]]:
    with connection_scope() as conn:
        rows = conn.execute(
            """
            SELECT * FROM investment_cashflow_status_history
            WHERE investment_cashflow_id = ?
            ORDER BY changed_at ASC, id ASC
            """,
            (investment_cashflow_id,),
        ).fetchall()
    return [row_as_mapping(r) for r in rows]


def _append_status_history(
    conn: sqlite3.Connection,
    *,
    record_id: int,
    from_status: str | None,
    to_status: str,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO investment_cashflow_status_history (
          investment_cashflow_id, from_status, to_status, changed_at, notes
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (record_id, from_status, to_status, _now_iso(), notes),
    )


def insert_investment_cashflow(**fields: Any) -> int:
    ts = _now_iso()
    gross = float(fields.get("gross_income") or 0)
    commissions = float(fields.get("commissions") or 0)
    taxes = float(fields.get("taxes") or 0)
    financing = float(fields.get("financing_cost") or 0)
    net = fields.get("net_cashflow")
    if net is None:
        net = compute_net_cashflow(gross, commissions, taxes, financing)
    cash_status = fields.get("cash_status") or "generated"
    source_type = fields.get("source_type")
    source_id = fields.get("source_id")
    if source_type and source_id:
        existing = get_investment_cashflow_by_source(str(source_type), str(source_id))
        if existing is not None:
            return int(existing["id"])
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO investment_cashflow_records (
              month, account_name, strategy_type, currency, gross_income,
              commissions, taxes, financing_cost, net_cashflow,
              linked_asset_id, fixed_expense_id, cash_status,
              generated_date, settlement_date, withdrawal_date, applied_date,
              source_type, source_id, imported_at, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(fields["month"]).strip()[:7],
                str(fields["account_name"]).strip(),
                fields["strategy_type"],
                str(fields["currency"]).upper(),
                gross,
                commissions,
                taxes,
                financing,
                float(net),
                fields.get("linked_asset_id"),
                fields.get("fixed_expense_id"),
                cash_status,
                fields.get("generated_date"),
                fields.get("settlement_date"),
                fields.get("withdrawal_date"),
                fields.get("applied_date"),
                source_type,
                source_id,
                fields.get("imported_at"),
                (fields.get("notes") or "").strip() or None
                if fields.get("notes") is not None
                else None,
                ts,
                ts,
            ),
        )
        rid = int(cur.lastrowid)
        _append_status_history(
            conn, record_id=rid, from_status=None, to_status=cash_status, notes="created"
        )
        return rid


def update_investment_cashflow(record_id: int, fields: dict[str, Any]) -> bool:
    existing = get_investment_cashflow(record_id)
    if existing is None:
        return False
    merged = {**existing, **fields}
    gross = float(merged.get("gross_income") or 0)
    commissions = float(merged.get("commissions") or 0)
    taxes = float(merged.get("taxes") or 0)
    financing = float(merged.get("financing_cost") or 0)
    if "net_cashflow" not in fields or fields.get("net_cashflow") is None:
        merged["net_cashflow"] = compute_net_cashflow(gross, commissions, taxes, financing)
    old_status = str(existing.get("cash_status") or "generated")
    new_status = str(merged.get("cash_status") or old_status)
    cols = [
        "month = ?", "account_name = ?", "strategy_type = ?", "currency = ?",
        "gross_income = ?", "commissions = ?", "taxes = ?", "financing_cost = ?",
        "net_cashflow = ?", "linked_asset_id = ?", "fixed_expense_id = ?",
        "cash_status = ?", "generated_date = ?", "settlement_date = ?",
        "withdrawal_date = ?", "applied_date = ?", "source_type = ?",
        "source_id = ?", "imported_at = ?", "notes = ?", "updated_at = ?",
    ]
    params = [
        str(merged["month"]).strip()[:7],
        str(merged["account_name"]).strip(),
        merged["strategy_type"],
        str(merged["currency"]).upper(),
        gross, commissions, taxes, financing,
        float(merged["net_cashflow"]),
        merged.get("linked_asset_id"),
        merged.get("fixed_expense_id"),
        new_status,
        merged.get("generated_date"),
        merged.get("settlement_date"),
        merged.get("withdrawal_date"),
        merged.get("applied_date"),
        merged.get("source_type"),
        merged.get("source_id"),
        merged.get("imported_at"),
        (merged.get("notes") or "").strip() or None if merged.get("notes") is not None else None,
        _now_iso(),
        record_id,
    ]
    with connection_scope() as conn:
        cur = conn.execute(
            "UPDATE investment_cashflow_records SET " + ", ".join(cols) + " WHERE id = ?",
            params,
        )
        if old_status != new_status and cur.rowcount > 0:
            _append_status_history(
                conn,
                record_id=record_id,
                from_status=old_status,
                to_status=new_status,
                notes=fields.get("_status_notes"),
            )
        return cur.rowcount > 0


def transition_investment_cash_status(
    record_id: int,
    *,
    to_status: str,
    fixed_expense_id: int | None = None,
    notes: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """
    Transiciones: generated → settled → withdrawn|applied.
    Solo withdrawn/applied cuentan como caja familiar.
    Solo applied cuenta como cobertura (requiere fixed_expense_id).
    """
    allowed = {"generated", "settled", "withdrawn", "applied"}
    if to_status not in allowed:
        raise ValueError(f"cash_status inválido: {to_status}")
    row = get_investment_cashflow(record_id)
    if row is None:
        raise ValueError("Registro no encontrado")
    current = str(row.get("cash_status") or "generated")
    net = float(row.get("net_cashflow") or 0)
    if to_status == "applied":
        if fixed_expense_id is None and row.get("fixed_expense_id") is None:
            raise ValueError("applied requiere fixed_expense_id")
        if net <= 0:
            raise ValueError("No se puede aplicar un net_cashflow no positivo")
    # Partial withdrawal is modeled as leaving residual in notes; full status change for stage 3.
    date_s = (as_of or _now_iso()[:10])[:10]
    fields: dict[str, Any] = {"cash_status": to_status, "_status_notes": notes}
    if to_status == "settled":
        fields["settlement_date"] = date_s
    elif to_status == "withdrawn":
        fields["withdrawal_date"] = date_s
        if not row.get("settlement_date"):
            fields["settlement_date"] = date_s
    elif to_status == "applied":
        fields["applied_date"] = date_s
        if fixed_expense_id is not None:
            fields["fixed_expense_id"] = fixed_expense_id
        if not row.get("settlement_date"):
            fields["settlement_date"] = date_s
    if not row.get("generated_date"):
        fields["generated_date"] = date_s
    ok = update_investment_cashflow(record_id, fields)
    if not ok:
        raise ValueError("No se pudo actualizar el estado")
    out = get_investment_cashflow(record_id)
    assert out is not None
    out["status_history"] = list_status_history(record_id)
    return out


def delete_investment_cashflow(record_id: int) -> bool:
    with connection_scope() as conn:
        cur = conn.execute(
            "DELETE FROM investment_cashflow_records WHERE id = ?", (record_id,)
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Leverage
# ---------------------------------------------------------------------------


def compute_total_financing_cost(interest_paid: float, taxes_and_fees: float) -> float:
    return float(interest_paid or 0) + float(taxes_and_fees or 0)


def list_leverage_records(
    *, month: str | None = None, currency: str | None = None
) -> list[dict[str, Any]]:
    parts: list[str] = []
    params: list[Any] = []
    if month:
        parts.append("month = ?"); params.append(month.strip()[:7])
    if currency:
        parts.append("upper(currency) = ?"); params.append(currency.upper())
    sql = "SELECT * FROM leverage_records"
    if parts:
        sql += " WHERE " + " AND ".join(parts)
    sql += " ORDER BY month DESC, id DESC"
    with connection_scope() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row_as_mapping(r) for r in rows]


def get_leverage_record(record_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute("SELECT * FROM leverage_records WHERE id = ?", (record_id,)).fetchone()
    return row_as_mapping(r) if r else None


def insert_leverage_record(**fields: Any) -> int:
    ts = _now_iso()
    interest = float(fields.get("interest_paid") or 0)
    fees = float(fields.get("taxes_and_fees") or 0)
    total = fields.get("total_financing_cost")
    if total is None:
        total = compute_total_financing_cost(interest, fees)
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO leverage_records (
              month, liability_id, linked_asset_id, currency, average_balance_used,
              days_used, nominal_annual_rate, interest_paid, taxes_and_fees,
              total_financing_cost, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(fields["month"]).strip()[:7],
                fields.get("liability_id"),
                fields.get("linked_asset_id"),
                str(fields["currency"]).upper(),
                float(fields.get("average_balance_used") or 0),
                int(fields.get("days_used") or 0),
                float(fields.get("nominal_annual_rate") or 0),
                interest,
                fees,
                float(total),
                (fields.get("notes") or "").strip() or None if fields.get("notes") is not None else None,
                ts,
                ts,
            ),
        )
        return int(cur.lastrowid)


def update_leverage_record(record_id: int, fields: dict[str, Any]) -> bool:
    existing = get_leverage_record(record_id)
    if existing is None:
        return False
    merged = {**existing, **fields}
    interest = float(merged.get("interest_paid") or 0)
    fees = float(merged.get("taxes_and_fees") or 0)
    if "total_financing_cost" not in fields or fields.get("total_financing_cost") is None:
        merged["total_financing_cost"] = compute_total_financing_cost(interest, fees)
    cols = [
        "month = ?", "liability_id = ?", "linked_asset_id = ?", "currency = ?",
        "average_balance_used = ?", "days_used = ?", "nominal_annual_rate = ?",
        "interest_paid = ?", "taxes_and_fees = ?", "total_financing_cost = ?",
        "notes = ?", "updated_at = ?",
    ]
    params = [
        str(merged["month"]).strip()[:7],
        merged.get("liability_id"),
        merged.get("linked_asset_id"),
        str(merged["currency"]).upper(),
        float(merged.get("average_balance_used") or 0),
        int(merged.get("days_used") or 0),
        float(merged.get("nominal_annual_rate") or 0),
        interest,
        fees,
        float(merged["total_financing_cost"]),
        (merged.get("notes") or "").strip() or None if merged.get("notes") is not None else None,
        _now_iso(),
        record_id,
    ]
    with connection_scope() as conn:
        cur = conn.execute(
            "UPDATE leverage_records SET " + ", ".join(cols) + " WHERE id = ?",
            params,
        )
        return cur.rowcount > 0


def delete_leverage_record(record_id: int) -> bool:
    with connection_scope() as conn:
        cur = conn.execute("DELETE FROM leverage_records WHERE id = ?", (record_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Capital allocations
# ---------------------------------------------------------------------------


def list_allocations(
    *, month: str | None = None, currency: str | None = None, include_cancelled: bool = True
) -> list[dict[str, Any]]:
    parts: list[str] = []
    params: list[Any] = []
    if month:
        parts.append("month = ?"); params.append(month.strip()[:7])
    if currency:
        parts.append("upper(currency) = ?"); params.append(currency.upper())
    if not include_cancelled:
        parts.append("status != 'cancelled'")
    sql = "SELECT * FROM capital_allocations"
    if parts:
        sql += " WHERE " + " AND ".join(parts)
    sql += " ORDER BY id DESC"
    with connection_scope() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row_as_mapping(r) for r in rows]


def sum_active_allocated(
    *, month: str, currency: str, exclude_id: int | None = None
) -> float:
    params: list[Any] = [month.strip()[:7], currency.upper(), *ACTIVE_ALLOCATION_STATUSES]
    sql = """
        SELECT COALESCE(SUM(allocated_amount), 0) AS s
        FROM capital_allocations
        WHERE month = ? AND upper(currency) = ?
          AND status IN (?, ?, ?)
    """
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    with connection_scope() as conn:
        r = conn.execute(sql, params).fetchone()
    return float(r["s"] or 0) if r else 0.0


def get_allocation(allocation_id: int) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute(
            "SELECT * FROM capital_allocations WHERE id = ?", (allocation_id,)
        ).fetchone()
    return row_as_mapping(r) if r else None


def insert_allocation(**fields: Any) -> int:
    ts = _now_iso()
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO capital_allocations (
              month, currency, available_amount, destination, allocated_amount,
              status, policy_id, asset_id, liability_id, house_project_id,
              rationale, expected_return, expected_monthly_cashflow,
              expected_hours_saved, executed_date, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(fields["month"]).strip()[:7],
                str(fields["currency"]).upper(),
                float(fields["available_amount"]),
                fields["destination"],
                float(fields["allocated_amount"]),
                fields.get("status") or "proposed",
                fields.get("policy_id"),
                fields.get("asset_id"),
                fields.get("liability_id"),
                fields.get("house_project_id"),
                (fields.get("rationale") or "").strip() or None,
                fields.get("expected_return"),
                fields.get("expected_monthly_cashflow"),
                fields.get("expected_hours_saved"),
                fields.get("executed_date"),
                ts,
                ts,
            ),
        )
        return int(cur.lastrowid)


def update_allocation(allocation_id: int, fields: dict[str, Any]) -> bool:
    existing = get_allocation(allocation_id)
    if existing is None:
        return False
    merged = {**existing, **{k: v for k, v in fields.items()}}
    cols = [
        "month = ?", "currency = ?", "available_amount = ?", "destination = ?",
        "allocated_amount = ?", "status = ?", "policy_id = ?", "asset_id = ?",
        "liability_id = ?", "house_project_id = ?", "rationale = ?",
        "expected_return = ?", "expected_monthly_cashflow = ?",
        "expected_hours_saved = ?", "executed_date = ?", "updated_at = ?",
    ]
    params = [
        str(merged["month"]).strip()[:7],
        str(merged["currency"]).upper(),
        float(merged["available_amount"]),
        merged["destination"],
        float(merged["allocated_amount"]),
        merged.get("status") or "proposed",
        merged.get("policy_id"),
        merged.get("asset_id"),
        merged.get("liability_id"),
        merged.get("house_project_id"),
        (merged.get("rationale") or "").strip() or None if merged.get("rationale") is not None else None,
        merged.get("expected_return"),
        merged.get("expected_monthly_cashflow"),
        merged.get("expected_hours_saved"),
        merged.get("executed_date"),
        _now_iso(),
        allocation_id,
    ]
    with connection_scope() as conn:
        cur = conn.execute(
            "UPDATE capital_allocations SET " + ", ".join(cols) + " WHERE id = ?",
            params,
        )
        return cur.rowcount > 0


def delete_allocation(allocation_id: int) -> bool:
    """Marca cancelled (soft) para no romper historial."""
    return update_allocation(allocation_id, {"status": "cancelled"})


# ---------------------------------------------------------------------------
# Month closures
# ---------------------------------------------------------------------------


def get_month_closure(month: str, currency: str) -> dict[str, Any] | None:
    with connection_scope() as conn:
        r = conn.execute(
            """
            SELECT * FROM family_month_closures
            WHERE month = ? AND upper(currency) = ?
            """,
            (month.strip()[:7], currency.upper()),
        ).fetchone()
    return row_as_mapping(r) if r else None


def list_month_closures(*, limit: int = 24) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit or 24), 120))
    with connection_scope() as conn:
        rows = conn.execute(
            """
            SELECT * FROM family_month_closures
            ORDER BY month DESC, currency ASC
            LIMIT ?
            """,
            (lim,),
        ).fetchall()
    return [row_as_mapping(r) for r in rows]


def upsert_month_closure(**fields: Any) -> int:
    ts = _now_iso()
    month = str(fields["month"]).strip()[:7]
    currency = str(fields["currency"]).upper()
    existing = get_month_closure(month, currency)
    total_income = float(fields.get("total_income") or 0)
    total_expenses = float(fields.get("total_expenses") or 0)
    debt_service = float(fields.get("debt_service") or 0)
    house_spending = float(fields.get("house_spending") or 0)
    investment_contributions = float(fields.get("investment_contributions") or 0)
    scalable_income = float(fields.get("scalable_income") or 0)
    free_cashflow = float(fields.get("free_cashflow") or 0)
    amount_allocated = float(fields.get("amount_allocated") or 0)
    unallocated_cash = float(fields.get("unallocated_cash") or 0)
    status = fields.get("status") or "draft"
    closed_at = fields.get("closed_at")
    notes = (
        (fields.get("notes") or "").strip() or None
        if fields.get("notes") is not None
        else None
    )
    if existing:
        with connection_scope() as conn:
            conn.execute(
                """
                UPDATE family_month_closures SET
                  total_income = ?, total_expenses = ?, debt_service = ?,
                  house_spending = ?, investment_contributions = ?,
                  scalable_income = ?, free_cashflow = ?, amount_allocated = ?,
                  unallocated_cash = ?, status = ?, closed_at = ?, notes = ?,
                  updated_at = ?
                WHERE id = ?
                """,
                (
                    total_income,
                    total_expenses,
                    debt_service,
                    house_spending,
                    investment_contributions,
                    scalable_income,
                    free_cashflow,
                    amount_allocated,
                    unallocated_cash,
                    status,
                    closed_at,
                    notes,
                    ts,
                    int(existing["id"]),
                ),
            )
        return int(existing["id"])
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO family_month_closures (
              month, currency, total_income, total_expenses, debt_service,
              house_spending, investment_contributions, scalable_income,
              free_cashflow, amount_allocated, unallocated_cash, status,
              closed_at, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                month,
                currency,
                total_income,
                total_expenses,
                debt_service,
                house_spending,
                investment_contributions,
                scalable_income,
                free_cashflow,
                amount_allocated,
                unallocated_cash,
                status,
                closed_at,
                notes,
                ts,
                ts,
            ),
        )
        return int(cur.lastrowid)
