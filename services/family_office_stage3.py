"""Análisis de deudas, resumen de negocios y comparación de escenarios (etapa 3)."""

from __future__ import annotations

from typing import Any

from persistence.sqlite import family_office_business_repo as biz
from persistence.sqlite import family_office_repo as repo


def build_debt_analysis() -> dict[str, Any]:
    liabilities = repo.list_liabilities(active_only=True)
    by_currency: dict[str, list[dict[str, Any]]] = {"ARS": [], "USD": [], "UVA": []}
    for li in liabilities:
        cur = str(li.get("currency") or "ARS").upper()
        bal = float(li.get("outstanding_balance") or 0)
        installment = float(
            li.get("current_installment")
            if li.get("current_installment") is not None
            else (li.get("installment_amount") or 0)
        )
        months = int(li.get("installments_remaining") or 0)
        rate = float(li.get("nominal_annual_rate") or 0)
        eac = li.get("effective_annual_cost")
        missing: list[str] = []
        if rate <= 0 and eac is None:
            missing.append("tasa/CFT")
        if months <= 0:
            missing.append("cuotas restantes")
        if installment <= 0:
            missing.append("cuota actual")
        if li.get("maturity_date") is None:
            missing.append("fecha vencimiento")
        # Retorno equivalente de cancelar ≈ tasa efectiva anual conocida (informativo).
        cancel_equiv = float(eac) if eac is not None else (rate if rate > 0 else None)
        # Score informativo 0-100: más alto = más urgente mirar (no es recomendación).
        score = 50.0
        if cancel_equiv is not None:
            score += min(30.0, float(cancel_equiv))
        if months > 0 and months < 12:
            score += 10
        if li.get("priority_override") is not None:
            score += float(li["priority_override"]) * 2
        score = max(0.0, min(100.0, score))
        row = {
            "liability_id": li["id"],
            "name": li.get("name"),
            "liability_type": li.get("liability_type"),
            "currency": cur,
            "outstanding_balance": bal,
            "installment": installment,
            "nominal_annual_rate": rate,
            "effective_annual_cost": eac,
            "rate_type": li.get("rate_type") or "unknown",
            "months_remaining": months,
            "monthly_committed_cashflow": installment,
            "cancel_equivalent_return_pct": cancel_equiv,
            "liquidity_needed_to_cancel": bal + float(li.get("prepayment_cost") or 0),
            "allows_partial_prepayment": bool(li.get("allows_partial_prepayment", True)),
            "maturity_date": li.get("maturity_date"),
            "missing_data": missing,
            "informational_score": score,
            "notes": [
                "Score informativo, no recomendación automática.",
                "No comparar deudas de distinta moneda en un total único.",
            ],
        }
        by_currency.setdefault(cur, []).append(row)

    return {
        "by_currency": by_currency,
        "notes": [
            "Análisis por moneda separado.",
            "No se emite orden de cancelar/refinanciar.",
        ],
    }


def simulate_debt_scenario(
    *,
    liability_id: int,
    prepayment_amount: float,
    scenario_type: str,
    assumptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    li = repo.get_liability(liability_id)
    if li is None:
        raise ValueError("Pasivo no encontrado")
    assumptions = assumptions or {}
    bal = float(li.get("outstanding_balance") or 0)
    installment = float(
        li.get("current_installment")
        if li.get("current_installment") is not None
        else (li.get("installment_amount") or 0)
    )
    months = int(li.get("installments_remaining") or 0)
    rate = float(li.get("nominal_annual_rate") or 0)
    eac = li.get("effective_annual_cost")
    prepay_cost = float(li.get("prepayment_cost") or assumptions.get("prepayment_cost") or 0)
    approx = False
    warnings: list[str] = []
    used_assumptions: list[str] = []

    if rate <= 0 and eac is None:
        approx = True
        rate = float(assumptions.get("assumed_annual_rate") or 18.5)
        used_assumptions.append(f"assumed_annual_rate={rate} (dato faltante)")
        warnings.append("Escenario APROXIMADO: falta tasa contractual.")
    monthly_rate = rate / 100.0 / 12.0 if rate else 0.0

    pay = max(0.0, float(prepayment_amount))
    if pay > bal + 1e-9:
        warnings.append("prepago mayor al saldo; se limita al saldo.")
        pay = bal
    if not li.get("allows_partial_prepayment", True) and pay < bal - 1e-9:
        warnings.append("El pasivo indica que no permite prepago parcial.")

    new_bal = max(0.0, bal - pay)
    interest_avoided = None
    new_months = months
    new_installment = installment
    freed = 0.0

    if scenario_type == "full_cancel":
        pay = bal
        new_bal = 0.0
        new_months = 0
        new_installment = 0.0
        freed = installment
        # interés restante aproximado: cuota*meses - saldo (si hay datos)
        if months > 0 and installment > 0:
            interest_avoided = max(0.0, installment * months - bal)
            used_assumptions.append("interés evitado ≈ cuotas restantes − saldo")
        elif monthly_rate > 0 and months > 0:
            interest_avoided = bal * monthly_rate * months * 0.5
            approx = True
            used_assumptions.append("interés evitado ≈ saldo * tasa_mensual * meses * 0.5")
        else:
            approx = True
            warnings.append("No se pudo estimar interés evitado con datos disponibles.")
    elif scenario_type == "reduce_term":
        if installment <= 0 or monthly_rate < 0:
            approx = True
            warnings.append("Sin cuota válida; se reduce saldo sin recalcular plazo exacto.")
            new_months = months
        else:
            # Aproximación: meses ≈ saldo / cuota (sin amortización completa)
            if installment > 0:
                new_months = max(0, int(round(new_bal / installment))) if new_bal > 0 else 0
                used_assumptions.append("plazo ≈ saldo_posterior / cuota (aprox.)")
                approx = True
            freed = 0.0
            if months > 0 and monthly_rate > 0:
                interest_avoided = pay * monthly_rate * max(1, months) * 0.5
                used_assumptions.append("interés evitado ≈ prepago * tasa_mensual * meses * 0.5")
                approx = True
    elif scenario_type == "reduce_installment":
        if months <= 0:
            approx = True
            months = int(assumptions.get("assumed_months") or 24)
            used_assumptions.append(f"assumed_months={months}")
            warnings.append("Cuotas restantes faltantes; se asume plazo.")
        new_months = months
        new_installment = (new_bal / months) if months > 0 else 0.0
        freed = max(0.0, installment - new_installment)
        used_assumptions.append("nueva cuota ≈ saldo_posterior / meses (aprox. lineal)")
        approx = True
        if monthly_rate > 0:
            interest_avoided = pay * monthly_rate * months * 0.5
    else:
        raise ValueError("scenario_type inválido")

    return {
        "liability_id": liability_id,
        "currency": li.get("currency"),
        "scenario_type": scenario_type,
        "approximate": approx,
        "prepayment_amount": pay,
        "prepayment_cost": prepay_cost,
        "balance_before": bal,
        "balance_after": new_bal,
        "installment_before": installment,
        "installment_after": new_installment,
        "months_before": int(li.get("installments_remaining") or 0),
        "months_after": new_months,
        "monthly_cashflow_freed": freed,
        "interest_avoided_estimate": interest_avoided,
        "assumptions_used": used_assumptions,
        "warnings": warnings,
        "notes": [
            "Simulación informativa. No es asesoramiento ni orden de precancelación.",
            "TNA de deuda no es comparable directamente a una rentabilidad proyectada.",
        ],
    }


def build_business_unit_summary(unit_id: int) -> dict[str, Any]:
    unit = biz.get_business_unit(unit_id)
    if unit is None:
        raise ValueError("Unidad no encontrada")
    metrics = biz.list_metrics(unit_id, limit=12)
    products = biz.list_products(unit_id, active_only=True)
    cases = biz.list_investment_cases(unit_id)

    latest = metrics[0] if metrics else None
    prev = metrics[1] if len(metrics) > 1 else None
    profit_per_owner_hour = None
    units_per_owner_hour = None
    founder_dependency = None
    growth = None
    working_capital_approx = None

    if latest:
        oh = float(latest.get("owner_hours") or 0)
        op = float(latest.get("operating_profit") or 0)
        sold = latest.get("units_sold")
        if oh > 0:
            profit_per_owner_hour = op / oh
            if sold is not None:
                units_per_owner_hour = float(sold) / oh
        # founder dependency: owner_hours / (owner + outsourced)
        total_h = oh + float(latest.get("outsourced_hours") or 0)
        if total_h > 0:
            founder_dependency = oh / total_h
        # working capital approx: variable costs of a month (rough)
        working_capital_approx = float(latest.get("variable_costs") or 0)
        if prev and float(prev.get("revenue") or 0) > 0:
            growth = (
                float(latest.get("revenue") or 0) - float(prev.get("revenue") or 0)
            ) / float(prev["revenue"])

    product_rows = []
    for p in products:
        product_rows.append(
            {
                "id": p["id"],
                "name": p["name"],
                "sale_price": p["sale_price"],
                "variable_cost": p["variable_cost"],
                "gross_margin": p["gross_margin"],
                "gross_margin_pct": (
                    float(p["gross_margin"]) / float(p["sale_price"])
                    if float(p["sale_price"]) > 0
                    else None
                ),
            }
        )

    bottleneck = None
    for c in cases:
        if c.get("status") in ("evaluating", "approved", "draft"):
            bottleneck = c.get("bottleneck")
            break

    return {
        "unit": unit,
        "latest_metrics": latest,
        "gross_profit": None if not latest else latest.get("gross_profit"),
        "operating_profit": None if not latest else latest.get("operating_profit"),
        "profit_per_owner_hour": profit_per_owner_hour,
        "units_per_owner_hour": units_per_owner_hour,
        "founder_dependency_index": founder_dependency,
        "monthly_revenue_growth": growth,
        "working_capital_approx": working_capital_approx,
        "products": product_rows,
        "current_bottleneck_hint": bottleneck,
        "notes": [
            "Facturación ≠ rentabilidad.",
            "No se valora automáticamente la unidad.",
            "Índices son descriptivos, no recomendaciones.",
        ],
    }


def compare_allocation_scenarios(
    *, month: str, currency: str, scenario_ids: list[int] | None = None
) -> dict[str, Any]:
    rows = biz.list_scenarios(month=month, currency=currency)
    if scenario_ids:
        wanted = set(scenario_ids)
        rows = [r for r in rows if int(r["id"]) in wanted]
    if not rows:
        return {
            "month": month,
            "currency": currency,
            "scenarios": [],
            "highlights": {},
            "missing_data": ["No hay escenarios para comparar"],
            "notes": ["Comparación explicativa; no selecciona automáticamente."],
        }

    def _key_cash(r: dict[str, Any]) -> float:
        return float(r.get("expected_monthly_cashflow") or 0)

    def _key_risk(r: dict[str, Any]) -> float:
        return float(r.get("risk_score") or 100)

    def _key_liq(r: dict[str, Any]) -> float:
        return float(r.get("liquidity_score") or 0)

    def _key_hours(r: dict[str, Any]) -> float:
        return float(r.get("expected_hours_saved") or 0)

    best_cash = max(rows, key=_key_cash)
    best_risk = min(rows, key=_key_risk)
    best_liq = max(rows, key=_key_liq)
    best_hours = max(rows, key=_key_hours)

    missing: list[str] = []
    for r in rows:
        if r.get("expected_annual_return") is None:
            missing.append(f"Escenario {r['id']}: falta expected_annual_return (proyección)")
        if r.get("confidence") == "low":
            missing.append(f"Escenario {r['id']}: confianza baja")

    enriched = []
    for r in rows:
        enriched.append(
            {
                **r,
                "is_projection": True,
                "projection_disclaimer": (
                    "Valores esperados son proyecciones, no resultados realizados. "
                    "No son órdenes de comprar/vender/invertir."
                ),
            }
        )

    return {
        "month": month,
        "currency": currency,
        "scenarios": enriched,
        "highlights": {
            "highest_expected_cashflow": {
                "id": best_cash["id"],
                "name": best_cash["name"],
                "value": best_cash.get("expected_monthly_cashflow"),
            },
            "lowest_risk_score": {
                "id": best_risk["id"],
                "name": best_risk["name"],
                "value": best_risk.get("risk_score"),
            },
            "highest_liquidity_score": {
                "id": best_liq["id"],
                "name": best_liq["name"],
                "value": best_liq.get("liquidity_score"),
            },
            "highest_hours_saved_founder_relief": {
                "id": best_hours["id"],
                "name": best_hours["name"],
                "value": best_hours.get("expected_hours_saved"),
                "note": "Proxy de menor dependencia del fundador vía horas liberadas.",
            },
        },
        "missing_data": missing,
        "notes": [
            "Comparación explicativa lado a lado.",
            "No se emite 'comprar', 'vender' ni 'invertir' como orden automática.",
            "Separar proyecciones de resultados realizados de Cartera/FO.",
            f"Solo moneda {currency}.",
        ],
    }
