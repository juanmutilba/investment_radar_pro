from __future__ import annotations

from typing import Any

from persistence.sqlite import family_office_repo as repo

ASSET_CURRENCIES = ("ARS", "USD")
LIABILITY_CURRENCIES = ("ARS", "USD", "UVA")
SNAPSHOT_CURRENCIES = ("ARS", "USD")

ASSET_CATEGORIES = (
    "real_estate",
    "vehicle",
    "financial",
    "business",
    "cash",
    "other",
)
OWNERSHIP_STATUSES = ("owned", "mortgaged", "purchase_agreement", "other")
LIQUIDITIES = ("high", "medium", "low")
LIABILITY_TYPES = (
    "mortgage_uva",
    "family_debt",
    "overdraft",
    "vehicle_loan",
    "personal_loan",
    "other",
)
POLICY_DESTINATIONS = (
    "debt",
    "investments",
    "salva",
    "investment_radar",
    "house",
    "emergency_fund",
    "other",
)
HOUSE_PRIORITIES = ("necessary", "functional", "aesthetic")
HOUSE_STATUSES = ("planned", "approved", "in_progress", "completed", "paused")


def _empty_currency_totals(currencies: tuple[str, ...]) -> dict[str, float]:
    return {c: 0.0 for c in currencies}


def _add(bucket: dict[str, float], currency: str, amount: float) -> None:
    cur = (currency or "").upper()
    if cur not in bucket:
        return
    try:
        bucket[cur] += float(amount or 0)
    except (TypeError, ValueError):
        pass


def build_dashboard() -> dict[str, Any]:
    """
    Agrega patrimonio familiar por moneda, sin convertir ARS/USD/UVA entre sí.
    """
    assets = repo.list_assets(active_only=True)
    liabilities = repo.list_liabilities(active_only=True)
    projects = repo.list_house_projects(active_only=True)
    latest_snapshot = repo.get_latest_snapshot()

    assets_by_currency = _empty_currency_totals(ASSET_CURRENCIES)
    assets_by_category: dict[str, dict[str, float]] = {
        cat: _empty_currency_totals(ASSET_CURRENCIES) for cat in ASSET_CATEGORIES
    }
    liquid_assets = _empty_currency_totals(ASSET_CURRENCIES)
    cashflow_assets = _empty_currency_totals(ASSET_CURRENCIES)
    monthly_cashflow = _empty_currency_totals(ASSET_CURRENCIES)

    alerts: list[str] = []

    for a in assets:
        cur = str(a.get("currency") or "").upper()
        value = float(a.get("estimated_value") or 0)
        _add(assets_by_currency, cur, value)
        cat = str(a.get("category") or "other")
        if cat not in assets_by_category:
            assets_by_category[cat] = _empty_currency_totals(ASSET_CURRENCIES)
        _add(assets_by_category[cat], cur, value)

        if a.get("liquidity") == "high":
            _add(liquid_assets, cur, value)
        if a.get("generates_cashflow"):
            _add(cashflow_assets, cur, value)
            _add(monthly_cashflow, cur, float(a.get("monthly_cashflow") or 0))

        if not a.get("valuation_date"):
            alerts.append(f"Activo '{a.get('name')}' sin fecha de valuación.")
        if a.get("generates_cashflow") and float(a.get("monthly_cashflow") or 0) <= 0:
            alerts.append(
                f"Activo '{a.get('name')}' marca genera flujo pero monthly_cashflow es 0."
            )

    liabilities_by_currency = _empty_currency_totals(LIABILITY_CURRENCIES)
    liabilities_by_type: dict[str, dict[str, float]] = {
        t: _empty_currency_totals(LIABILITY_CURRENCIES) for t in LIABILITY_TYPES
    }

    for li in liabilities:
        cur = str(li.get("currency") or "").upper()
        bal = float(li.get("outstanding_balance") or 0)
        _add(liabilities_by_currency, cur, bal)
        lt = str(li.get("liability_type") or "other")
        if lt not in liabilities_by_type:
            liabilities_by_type[lt] = _empty_currency_totals(LIABILITY_CURRENCIES)
        _add(liabilities_by_type[lt], cur, bal)

        if float(li.get("outstanding_balance") or 0) > float(li.get("original_amount") or 0):
            alerts.append(
                f"Pasivo '{li.get('name')}': saldo pendiente mayor al monto original."
            )
        linked = li.get("linked_asset_id")
        if linked is not None and repo.get_asset(int(linked)) is None:
            alerts.append(
                f"Pasivo '{li.get('name')}' referencia linked_asset_id={linked} inexistente."
            )

    net_worth: dict[str, float] = {}
    for cur in LIABILITY_CURRENCIES:
        assets_total = float(assets_by_currency.get(cur, 0.0)) if cur in ASSET_CURRENCIES else 0.0
        liab_total = float(liabilities_by_currency.get(cur, 0.0))
        # UVA no tiene activos en esta etapa; patrimonio neto UVA = -pasivos UVA.
        net_worth[cur] = assets_total - liab_total

    house_projects_by_status = {s: 0 for s in HOUSE_STATUSES}
    for p in projects:
        st = str(p.get("status") or "planned")
        if st not in house_projects_by_status:
            house_projects_by_status[st] = 0
        house_projects_by_status[st] += 1
        if float(p.get("paid_amount") or 0) > float(p.get("estimated_cost") or 0):
            alerts.append(
                f"Proyecto '{p.get('name')}': pagado supera el costo estimado."
            )

    if not assets:
        alerts.append("No hay activos familiares activos cargados.")
    if not liabilities:
        alerts.append("No hay pasivos familiares activos cargados.")
    if latest_snapshot is None:
        alerts.append("No hay snapshot mensual cargado (flujo libre no disponible).")

    latest_free_cashflow = None
    latest_snapshot_month = None
    latest_snapshot_currency = None
    if latest_snapshot is not None:
        latest_free_cashflow = float(latest_snapshot.get("free_cashflow") or 0)
        latest_snapshot_month = latest_snapshot.get("month")
        latest_snapshot_currency = latest_snapshot.get("currency")

    return {
        "assets_by_currency": assets_by_currency,
        "assets_by_category": assets_by_category,
        "liabilities_by_currency": liabilities_by_currency,
        "liabilities_by_type": liabilities_by_type,
        "net_worth_by_currency": net_worth,
        "liquid_assets_by_currency": liquid_assets,
        "cashflow_assets_by_currency": cashflow_assets,
        "monthly_cashflow_by_currency": monthly_cashflow,
        "house_projects_by_status": house_projects_by_status,
        "latest_snapshot_month": latest_snapshot_month,
        "latest_snapshot_currency": latest_snapshot_currency,
        "latest_free_cashflow": latest_free_cashflow,
        "counts": {
            "assets": len(assets),
            "liabilities": len(liabilities),
            "house_projects": len(projects),
            "active_policies": len(repo.list_policies(active_only=True)),
        },
        "alerts": alerts,
        "notes": [
            "Totales separados por moneda: no se convierte ni se suma ARS + USD + UVA.",
            "Patrimonio neto por moneda = activos(moneda) − pasivos(moneda).",
            "UVA solo aplica a pasivos en esta etapa.",
        ],
    }


def compute_snapshot_free_cashflow(
    *,
    active_income: float,
    consulting_income: float,
    scalable_income: float,
    fixed_expenses: float,
    debt_payments: float,
    house_spending: float,
    investment_contributions: float,
) -> float:
    return (
        float(active_income or 0)
        + float(consulting_income or 0)
        + float(scalable_income or 0)
        - float(fixed_expenses or 0)
        - float(debt_payments or 0)
        - float(house_spending or 0)
        - float(investment_contributions or 0)
    )


FIXED_EXPENSE_CATEGORIES = (
    "education",
    "utilities",
    "insurance",
    "debt_payment",
    "food",
    "transport",
    "health",
    "housing",
    "taxes",
    "other",
)
SOURCE_UNITS = (
    "employment",
    "consulting",
    "salva",
    "investment_radar",
    "investments",
    "debt",
    "house",
    "family",
    "other",
)
STRATEGY_TYPES = (
    "covered_call",
    "dividend",
    "interest",
    "realized_gain",
    "realized_loss",
    "other",
)
ALLOCATION_DESTINATIONS = (
    "debt",
    "investments",
    "salva",
    "investment_radar",
    "house",
    "emergency_fund",
    "cash",
    "other",
)
ALLOCATION_STATUSES = ("proposed", "approved", "executed", "cancelled")
CLOSURE_STATUSES = ("draft", "closed", "reopened")


def build_monthly_summary(*, month: str, currency: str) -> dict[str, Any]:
    from persistence.sqlite import family_office_flow_repo as flow

    m = month.strip()[:7]
    cur = currency.upper()
    entries = flow.list_cashflow_entries(month=m, currency=cur)
    income_by_unit: dict[str, float] = {u: 0.0 for u in SOURCE_UNITS}
    expenses_by_category: dict[str, float] = {}
    debt_service = 0.0
    house_spending = 0.0
    investment_contributions = 0.0
    scalable_income = 0.0
    total_income = 0.0
    total_expenses = 0.0

    for e in entries:
        amt = float(e.get("amount") or 0)
        unit = str(e.get("source_unit") or "other")
        cat = str(e.get("category") or "other")
        if e.get("entry_type") == "income":
            total_income += amt
            income_by_unit[unit] = income_by_unit.get(unit, 0.0) + amt
            if unit in ("salva", "investment_radar", "investments"):
                scalable_income += amt
        else:
            total_expenses += amt
            expenses_by_category[cat] = expenses_by_category.get(cat, 0.0) + amt
            if unit == "debt" or cat == "debt_payment":
                debt_service += amt
            if unit == "house":
                house_spending += amt
            if unit in ("investments", "investment_radar", "salva"):
                investment_contributions += amt

    free_cashflow = total_income - total_expenses
    amount_allocated = flow.sum_active_allocated(month=m, currency=cur)
    unallocated = free_cashflow - amount_allocated
    closure = flow.get_month_closure(m, cur)

    return {
        "month": m,
        "currency": cur,
        "income_by_unit": income_by_unit,
        "expenses_by_category": expenses_by_category,
        "debt_service": debt_service,
        "house_spending": house_spending,
        "investment_contributions": investment_contributions,
        "scalable_income": scalable_income,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "free_cashflow": free_cashflow,
        "amount_allocated": amount_allocated,
        "unallocated_cash": unallocated,
        "closure_status": (closure or {}).get("status") or "draft",
        "closure": closure,
        "notes": [
            f"Resumen exclusivo en {cur}. No se mezclan otras monedas.",
            "Las proyecciones no se incluyen: solo entradas registradas.",
        ],
    }


def build_fixed_expense_coverage(*, month: str, currency: str) -> dict[str, Any]:
    from persistence.sqlite import family_office_flow_repo as flow

    m = month.strip()[:7]
    cur = currency.upper()
    expenses = flow.list_fixed_expenses(active_only=True, currency=cur)
    entries = flow.list_cashflow_entries(month=m, currency=cur)
    invs = flow.list_investment_cashflows(month=m, currency=cur)

    covered_rows: list[dict[str, Any]] = []
    total_essential = 0.0
    total_covered_essential = 0.0
    first_uncovered: dict[str, Any] | None = None

    for fe in expenses:
        fid = int(fe["id"])
        expected = float(fe.get("expected_monthly_amount") or 0)
        sources: list[dict[str, Any]] = []
        assigned = 0.0

        for e in entries:
            if e.get("fixed_expense_id") != fid:
                continue
            amt = float(e.get("amount") or 0)
            assigned += amt
            sources.append(
                {
                    "kind": "cashflow_entry",
                    "id": e.get("id"),
                    "entry_type": e.get("entry_type"),
                    "source_unit": e.get("source_unit"),
                    "amount": amt,
                    "description": e.get("description"),
                }
            )
        for inv in invs:
            if inv.get("fixed_expense_id") != fid:
                continue
            if str(inv.get("cash_status") or "") != "applied":
                continue
            amt = float(inv.get("net_cashflow") or 0)
            if amt <= 0:
                continue
            assigned += amt
            sources.append(
                {
                    "kind": "investment_cashflow",
                    "id": inv.get("id"),
                    "strategy_type": inv.get("strategy_type"),
                    "account_name": inv.get("account_name"),
                    "cash_status": inv.get("cash_status"),
                    "amount": amt,
                }
            )

        pct = (assigned / expected * 100.0) if expected > 0 else (100.0 if assigned > 0 else 0.0)
        row = {
            "fixed_expense_id": fid,
            "name": fe.get("name"),
            "category": fe.get("category"),
            "coverage_order": fe.get("coverage_order"),
            "priority": fe.get("priority"),
            "is_essential": bool(fe.get("is_essential")),
            "expected_monthly_amount": expected,
            "assigned_cashflow": assigned,
            "coverage_pct": min(pct, 999.0),
            "fully_covered": assigned + 1e-9 >= expected,
            "sources": sources,
        }
        covered_rows.append(row)
        if fe.get("is_essential"):
            total_essential += expected
            total_covered_essential += min(assigned, expected)
        if first_uncovered is None and not row["fully_covered"]:
            first_uncovered = row

    coverage_index = (
        (total_covered_essential / total_essential) if total_essential > 0 else None
    )

    return {
        "month": m,
        "currency": cur,
        "items": covered_rows,
        "total_essential_fixed_expenses": total_essential,
        "total_covered_essential": total_covered_essential,
        "coverage_index": coverage_index,
        "first_uncovered_expense": first_uncovered,
        "notes": [
            "Cobertura basada en vínculos manuales (fixed_expense_id).",
            "No se mezclan proyecciones con resultados realizados.",
            f"Solo moneda {cur}.",
        ],
    }


def build_leverage_performance(*, month: str) -> dict[str, Any]:
    from persistence.sqlite import family_office_flow_repo as flow

    m = month.strip()[:7]
    lev = flow.list_leverage_records(month=m)
    invs = flow.list_investment_cashflows(month=m)

    by_currency: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for cur in ("ARS", "USD", "UVA"):
        by_currency[cur] = {
            "financed_capital": 0.0,
            "gross_income": 0.0,
            "realized_result": 0.0,
            "financing_cost": 0.0,
            "taxes_and_fees": 0.0,
            "commissions": 0.0,
            "net_cashflow": 0.0,
            "net_return_on_financed_capital": None,
            "own_capital_note": "Capital propio no se infiere automáticamente; cargar en notas/activos.",
        }

    for r in lev:
        cur = str(r.get("currency") or "ARS").upper()
        if cur not in by_currency:
            by_currency[cur] = {
                "financed_capital": 0.0,
                "gross_income": 0.0,
                "realized_result": 0.0,
                "financing_cost": 0.0,
                "taxes_and_fees": 0.0,
                "commissions": 0.0,
                "net_cashflow": 0.0,
                "net_return_on_financed_capital": None,
                "own_capital_note": "Capital propio no se infiere automáticamente.",
            }
        by_currency[cur]["financed_capital"] += float(r.get("average_balance_used") or 0)
        by_currency[cur]["financing_cost"] += float(r.get("interest_paid") or 0)
        by_currency[cur]["taxes_and_fees"] += float(r.get("taxes_and_fees") or 0)
        by_currency[cur]["net_cashflow"] -= float(r.get("total_financing_cost") or 0)

    premium_only = True
    has_realized = False
    for inv in invs:
        cur = str(inv.get("currency") or "ARS").upper()
        if cur not in by_currency:
            continue
        gross = float(inv.get("gross_income") or 0)
        by_currency[cur]["gross_income"] += gross
        by_currency[cur]["commissions"] += float(inv.get("commissions") or 0)
        by_currency[cur]["taxes_and_fees"] += float(inv.get("taxes") or 0)
        by_currency[cur]["financing_cost"] += float(inv.get("financing_cost") or 0)
        net = float(inv.get("net_cashflow") or 0)
        by_currency[cur]["net_cashflow"] += net
        st = str(inv.get("strategy_type") or "")
        if st in ("realized_gain", "realized_loss"):
            has_realized = True
            premium_only = False
            by_currency[cur]["realized_result"] += net
        elif st == "covered_call":
            by_currency[cur]["realized_result"] += net  # primas realizadas, no P&L subyacente
        else:
            premium_only = False
            by_currency[cur]["realized_result"] += net

    for cur, bucket in by_currency.items():
        fin = float(bucket["financed_capital"] or 0)
        if fin > 0:
            bucket["net_return_on_financed_capital"] = float(bucket["net_cashflow"]) / fin
        if fin > 0 and abs(float(bucket["net_cashflow"])) < 1e-9 and not invs:
            warnings.append(f"{cur}: hay capital financiado sin ingresos de inversión registrados.")

    if not lev and not invs:
        warnings.append("Faltan datos de apalancamiento y/o cashflow de inversiones para el mes.")
    if lev and invs and premium_only and not has_realized:
        warnings.append(
            "El resultado incluye primas/ingresos de estrategia pero no el resultado del subyacente. "
            "No comparar una TNA de deuda con una rentabilidad proyectada."
        )
    if any(float(r.get("average_balance_used") or 0) > 0 for r in lev):
        warnings.append(
            "Hay deuda usada para invertir: capital propio y financiado deben mirarse por separado."
        )

    return {
        "month": m,
        "by_currency": by_currency,
        "leverage_records": lev,
        "investment_records": invs,
        "warnings": warnings,
        "notes": [
            "Rendimientos son realizados registrados, no proyecciones.",
            "No se afirma que una rentabilidad proyectada sea segura.",
            "Monedas sin convertir ni sumar.",
        ],
    }


def build_allocation_board(*, month: str, currency: str) -> dict[str, Any]:
    from persistence.sqlite import family_office_flow_repo as flow

    m = month.strip()[:7]
    cur = currency.upper()
    summary = build_monthly_summary(month=m, currency=cur)
    free = float(summary["free_cashflow"])
    allocations = flow.list_allocations(month=m, currency=cur, include_cancelled=True)
    active_sum = flow.sum_active_allocated(month=m, currency=cur)
    pending = free - active_sum
    house_reserved = sum(
        float(a.get("allocated_amount") or 0)
        for a in allocations
        if a.get("destination") == "house" and a.get("status") in ("proposed", "approved", "executed")
    )
    return {
        "month": m,
        "currency": cur,
        "free_cashflow": free,
        "amount_allocated": active_sum,
        "unallocated_cash": pending,
        "house_monthly_reserve": house_reserved,
        "allocations": allocations,
        "closure_status": summary["closure_status"],
        "notes": [
            "Toda asignación es manual. No hay recomendaciones automáticas.",
            "expected_return / proyecciones son orientativas, no resultados seguros.",
            f"Solo {cur}.",
        ],
    }


def validate_allocation_capacity(
    *,
    month: str,
    currency: str,
    allocated_amount: float,
    available_amount: float,
    exclude_id: int | None = None,
    status: str = "proposed",
) -> None:
    from persistence.sqlite import family_office_flow_repo as flow

    if status == "cancelled":
        return
    if allocated_amount > available_amount + 1e-9:
        raise ValueError("allocated_amount no puede superar available_amount")
    current = flow.sum_active_allocated(
        month=month, currency=currency, exclude_id=exclude_id
    )
    # Capacidad del mes = max(available_amount de esta fila, free cashflow del mes)
    summary = build_monthly_summary(month=month, currency=currency)
    capacity = max(float(available_amount), float(summary["free_cashflow"]))
    if current + float(allocated_amount) > capacity + 1e-9:
        raise ValueError(
            "Sobreasignación: la suma de asignaciones activas supera el capital disponible "
            f"del mes/moneda (capacidad={capacity:.2f}, ya asignado={current:.2f})."
        )


def close_month(*, month: str, currency: str, notes: str | None = None) -> dict[str, Any]:
    from persistence.sqlite import family_office_flow_repo as flow
    from datetime import datetime, timezone

    summary = build_monthly_summary(month=month, currency=currency)
    free = float(summary["free_cashflow"])
    allocated = float(summary["amount_allocated"])
    if allocated > free + 1e-9:
        raise ValueError(
            "No se puede cerrar: las asignaciones activas superan el flujo libre del mes."
        )
    cid = flow.upsert_month_closure(
        month=month,
        currency=currency,
        total_income=summary["total_income"],
        total_expenses=summary["total_expenses"],
        debt_service=summary["debt_service"],
        house_spending=summary["house_spending"],
        investment_contributions=summary["investment_contributions"],
        scalable_income=summary["scalable_income"],
        free_cashflow=free,
        amount_allocated=allocated,
        unallocated_cash=summary["unallocated_cash"],
        status="closed",
        closed_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
    )
    row = flow.get_month_closure(month, currency)
    assert row is not None
    row["id"] = cid
    return row


def reopen_month(*, month: str, currency: str, notes: str | None = None) -> dict[str, Any]:
    from persistence.sqlite import family_office_flow_repo as flow

    existing = flow.get_month_closure(month, currency)
    if existing is None:
        raise ValueError("No hay cierre para reabrir")
    if existing.get("status") != "closed":
        raise ValueError("Solo se pueden reabrir cierres en estado closed")
    flow.upsert_month_closure(
        month=month,
        currency=currency,
        total_income=existing.get("total_income"),
        total_expenses=existing.get("total_expenses"),
        debt_service=existing.get("debt_service"),
        house_spending=existing.get("house_spending"),
        investment_contributions=existing.get("investment_contributions"),
        scalable_income=existing.get("scalable_income"),
        free_cashflow=existing.get("free_cashflow"),
        amount_allocated=existing.get("amount_allocated"),
        unallocated_cash=existing.get("unallocated_cash"),
        status="reopened",
        closed_at=None,
        notes=notes or existing.get("notes"),
    )
    row = flow.get_month_closure(month, currency)
    assert row is not None
    return row


def ensure_draft_closure(*, month: str, currency: str) -> dict[str, Any]:
    from persistence.sqlite import family_office_flow_repo as flow

    existing = flow.get_month_closure(month, currency)
    if existing is not None:
        return existing
    summary = build_monthly_summary(month=month, currency=currency)
    flow.upsert_month_closure(
        month=month,
        currency=currency,
        total_income=summary["total_income"],
        total_expenses=summary["total_expenses"],
        debt_service=summary["debt_service"],
        house_spending=summary["house_spending"],
        investment_contributions=summary["investment_contributions"],
        scalable_income=summary["scalable_income"],
        free_cashflow=summary["free_cashflow"],
        amount_allocated=summary["amount_allocated"],
        unallocated_cash=summary["unallocated_cash"],
        status="draft",
        closed_at=None,
        notes=None,
    )
    row = flow.get_month_closure(month, currency)
    assert row is not None
    return row
