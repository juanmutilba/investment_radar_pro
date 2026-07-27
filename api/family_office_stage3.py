from __future__ import annotations

import math
import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from persistence.sqlite import family_office_business_repo as biz
from persistence.sqlite import family_office_flow_repo as flow
from services.family_office_portfolio_adapter import (
    build_portfolio_summary,
    confirm_portfolio_import,
    preview_portfolio_import,
)
from services.family_office_stage3 import (
    build_business_unit_summary,
    build_debt_analysis,
    compare_allocation_scenarios,
    simulate_debt_scenario,
)

router = APIRouter(prefix="/family-office", tags=["family-office-stage3"])

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _month_ok(v: str) -> str:
    s = v.strip()
    if not _MONTH_RE.match(s):
        raise ValueError("month debe ser YYYY-MM")
    return s


def _nonneg(v: float, field: str) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} inválido") from exc
    if math.isnan(n) or math.isinf(n) or n < 0:
        raise ValueError(f"{field} inválido")
    return n


# ---------- Integrations ----------


class ImportPreviewBody(BaseModel):
    portfolio_type: Literal["real", "radar"] = "real"
    include_source_ids: list[str] | None = None
    exclude_source_ids: list[str] | None = None


class ImportConfirmBody(BaseModel):
    portfolio_type: Literal["real", "radar"] = "real"
    include_source_ids: list[str] = Field(min_length=1)
    exclude_source_ids: list[str] | None = None


@router.get("/integrations/portfolio-summary")
def portfolio_summary(
    portfolio_type: Literal["real", "radar"] = Query(default="real"),
) -> dict[str, Any]:
    return build_portfolio_summary(portfolio_type=portfolio_type)


@router.post("/integrations/portfolio-import")
def portfolio_import(body: ImportPreviewBody | ImportConfirmBody) -> dict[str, Any]:
    """
    Sin include_source_ids (o vacío en preview body) → vista previa.
    Con include_source_ids en confirm → importa idempotente.
    """
    if isinstance(body, ImportConfirmBody) or (
        hasattr(body, "include_source_ids")
        and body.include_source_ids
        and getattr(body, "__class__", None).__name__ == "ImportConfirmBody"
    ):
        return confirm_portfolio_import(
            portfolio_type=body.portfolio_type,
            include_source_ids=list(body.include_source_ids or []),
            exclude_source_ids=body.exclude_source_ids,
        )
    # Preview path: use dedicated endpoint semantics via query-less POST preview
    return preview_portfolio_import(
        portfolio_type=body.portfolio_type,
        include_source_ids=body.include_source_ids,
        exclude_source_ids=body.exclude_source_ids,
    )


@router.post("/integrations/portfolio-import/preview")
def portfolio_import_preview(body: ImportPreviewBody) -> dict[str, Any]:
    return preview_portfolio_import(
        portfolio_type=body.portfolio_type,
        include_source_ids=body.include_source_ids,
        exclude_source_ids=body.exclude_source_ids,
    )


@router.post("/integrations/portfolio-import/confirm")
def portfolio_import_confirm(body: ImportConfirmBody) -> dict[str, Any]:
    return confirm_portfolio_import(
        portfolio_type=body.portfolio_type,
        include_source_ids=body.include_source_ids,
        exclude_source_ids=body.exclude_source_ids,
    )


# ---------- Cash status transitions ----------


class CashStatusBody(BaseModel):
    to_status: Literal["generated", "settled", "withdrawn", "applied"]
    fixed_expense_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)
    as_of: str | None = Field(default=None, max_length=32)


@router.post("/investment-cashflow-records/{record_id}/status")
def set_inv_cash_status(record_id: int, body: CashStatusBody) -> dict[str, Any]:
    try:
        return flow.transition_investment_cash_status(
            record_id,
            to_status=body.to_status,
            fixed_expense_id=body.fixed_expense_id,
            notes=body.notes,
            as_of=body.as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/investment-cashflow-records/{record_id}/status-history")
def inv_cash_status_history(record_id: int) -> list[dict[str, Any]]:
    if flow.get_investment_cashflow(record_id) is None:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    return flow.list_status_history(record_id)


# ---------- Debt ----------


class DebtScenarioBody(BaseModel):
    liability_id: int
    prepayment_amount: float
    scenario_type: Literal["reduce_term", "reduce_installment", "full_cancel"]
    assumptions: dict[str, Any] | None = None

    @field_validator("prepayment_amount")
    @classmethod
    def amt(cls, v: float) -> float:
        return _nonneg(v, "prepayment_amount")


@router.get("/debt-analysis")
def debt_analysis() -> dict[str, Any]:
    return build_debt_analysis()


@router.post("/debt-scenarios")
def debt_scenarios(body: DebtScenarioBody) -> dict[str, Any]:
    try:
        return simulate_debt_scenario(
            liability_id=body.liability_id,
            prepayment_amount=body.prepayment_amount,
            scenario_type=body.scenario_type,
            assumptions=body.assumptions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------- Business units ----------


class BusinessUnitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    unit_type: Literal["salva", "consulting", "investment_radar", "other"]
    currency: Literal["ARS", "USD"]
    notes: str | None = None
    is_active: bool = True


class MetricCreate(BaseModel):
    month: str
    currency: Literal["ARS", "USD"]
    revenue: float = 0
    variable_costs: float = 0
    fixed_costs: float = 0
    owner_hours: float = 0
    outsourced_hours: float = 0
    units_sold: float | None = None
    customers: float | None = None
    notes: str | None = None

    @field_validator("month")
    @classmethod
    def m(cls, v: str) -> str:
        return _month_ok(v)


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    unit: str = "unit"
    sale_price: float
    variable_cost: float
    notes: str | None = None
    is_active: bool = True

    @field_validator("sale_price", "variable_cost")
    @classmethod
    def nn(cls, v: float, info) -> float:  # type: ignore[no-untyped-def]
        return _nonneg(v, info.field_name)


class CaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    currency: Literal["ARS", "USD"]
    investment_amount: float
    investment_type: Literal[
        "machinery", "marketing", "staff", "working_capital", "automation", "distribution", "other"
    ]
    bottleneck: Literal[
        "production",
        "sales",
        "logistics",
        "administration",
        "working_capital",
        "founder_dependency",
        "other",
    ]
    expected_monthly_revenue_increment: float = 0
    expected_monthly_cost_increment: float = 0
    expected_monthly_profit_increment: float = 0
    expected_hours_saved: float = 0
    expected_start_month: str | None = None
    status: Literal["draft", "evaluating", "approved", "executed", "rejected"] = "draft"
    assumptions: str | None = None

    @field_validator("investment_amount")
    @classmethod
    def amt(cls, v: float) -> float:
        return _nonneg(v, "investment_amount")


@router.get("/business-units")
def list_units(active_only: bool = Query(default=True)) -> list[dict[str, Any]]:
    return biz.list_business_units(active_only=active_only)


@router.post("/business-units", status_code=201)
def create_unit(body: BusinessUnitCreate) -> dict[str, Any]:
    uid = biz.insert_business_unit(**body.model_dump())
    row = biz.get_business_unit(uid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear la unidad")
    return row


@router.patch("/business-units/{unit_id}")
def patch_unit(unit_id: int, body: BusinessUnitCreate) -> dict[str, Any]:
    if biz.get_business_unit(unit_id) is None:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    biz.update_business_unit(unit_id, body.model_dump())
    return biz.get_business_unit(unit_id)  # type: ignore[return-value]


@router.delete("/business-units/{unit_id}")
def delete_unit(unit_id: int) -> dict[str, Any]:
    if biz.get_business_unit(unit_id) is None:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    biz.deactivate_business_unit(unit_id)
    return {"ok": True, "id": unit_id, "is_active": False}


@router.get("/business-units/{unit_id}/summary")
def unit_summary(unit_id: int) -> dict[str, Any]:
    try:
        return build_business_unit_summary(unit_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/business-units/{unit_id}/investment-cases")
def unit_cases(unit_id: int) -> list[dict[str, Any]]:
    if biz.get_business_unit(unit_id) is None:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    return biz.list_investment_cases(unit_id)


@router.post("/business-units/{unit_id}/metrics", status_code=201)
def create_metric(unit_id: int, body: MetricCreate) -> dict[str, Any]:
    if biz.get_business_unit(unit_id) is None:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    mid = biz.upsert_metric(business_unit_id=unit_id, **body.model_dump())
    rows = [m for m in biz.list_metrics(unit_id, limit=50) if int(m["id"]) == mid]
    return rows[0] if rows else {"id": mid}


@router.get("/business-units/{unit_id}/metrics")
def list_unit_metrics(unit_id: int) -> list[dict[str, Any]]:
    if biz.get_business_unit(unit_id) is None:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    return biz.list_metrics(unit_id)


@router.post("/business-units/{unit_id}/products", status_code=201)
def create_product(unit_id: int, body: ProductCreate) -> dict[str, Any]:
    if biz.get_business_unit(unit_id) is None:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    pid = biz.insert_product(business_unit_id=unit_id, **body.model_dump())
    products = [p for p in biz.list_products(unit_id, active_only=False) if int(p["id"]) == pid]
    return products[0] if products else {"id": pid}


@router.get("/business-units/{unit_id}/products")
def list_unit_products(unit_id: int) -> list[dict[str, Any]]:
    if biz.get_business_unit(unit_id) is None:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    return biz.list_products(unit_id)


@router.post("/business-units/{unit_id}/investment-cases", status_code=201)
def create_case(unit_id: int, body: CaseCreate) -> dict[str, Any]:
    if biz.get_business_unit(unit_id) is None:
        raise HTTPException(status_code=404, detail="Unidad no encontrada")
    cid = biz.insert_investment_case(business_unit_id=unit_id, **body.model_dump())
    cases = [c for c in biz.list_investment_cases(unit_id) if int(c["id"]) == cid]
    return cases[0] if cases else {"id": cid}


# ---------- Scenarios ----------


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    month: str
    currency: Literal["ARS", "USD"]
    available_capital: float
    destination_type: Literal[
        "debt", "portfolio", "salva", "investment_radar", "house", "emergency_fund", "cash"
    ]
    destination_id: int | None = None
    allocation_amount: float
    expected_annual_return: float | None = None
    expected_monthly_cashflow: float | None = None
    expected_payback_months: float | None = None
    expected_hours_saved: float | None = None
    liquidity_score: float = 50
    risk_score: float = 50
    confidence: Literal["low", "medium", "high"] = "low"
    assumptions: str | None = None
    is_selected: bool = False

    @field_validator("month")
    @classmethod
    def m(cls, v: str) -> str:
        return _month_ok(v)

    @field_validator("available_capital", "allocation_amount")
    @classmethod
    def nn(cls, v: float, info) -> float:  # type: ignore[no-untyped-def]
        return _nonneg(v, info.field_name)


class ScenarioCompareBody(BaseModel):
    month: str
    currency: Literal["ARS", "USD"]
    scenario_ids: list[int] | None = None

    @field_validator("month")
    @classmethod
    def m(cls, v: str) -> str:
        return _month_ok(v)


@router.get("/allocation-scenarios")
def list_allocation_scenarios(
    month: str | None = Query(default=None),
    currency: Literal["ARS", "USD"] | None = Query(default=None),
) -> list[dict[str, Any]]:
    if month:
        try:
            month = _month_ok(month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return biz.list_scenarios(month=month, currency=currency)


@router.post("/allocation-scenarios", status_code=201)
def create_allocation_scenario(body: ScenarioCreate) -> dict[str, Any]:
    sid = biz.insert_scenario(**body.model_dump())
    row = biz.get_scenario(sid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear el escenario")
    return row


@router.post("/allocation-scenarios/compare")
def compare_scenarios(body: ScenarioCompareBody) -> dict[str, Any]:
    return compare_allocation_scenarios(
        month=body.month, currency=body.currency, scenario_ids=body.scenario_ids
    )


@router.delete("/allocation-scenarios/{scenario_id}")
def delete_allocation_scenario(scenario_id: int) -> dict[str, Any]:
    if biz.get_scenario(scenario_id) is None:
        raise HTTPException(status_code=404, detail="Escenario no encontrado")
    biz.delete_scenario(scenario_id)
    return {"ok": True, "id": scenario_id}
