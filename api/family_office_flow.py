from __future__ import annotations

import math
import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from persistence.sqlite import family_office_flow_repo as flow
from persistence.sqlite import family_office_repo as repo
from services.family_office import (
    ALLOCATION_DESTINATIONS,
    ALLOCATION_STATUSES,
    ASSET_CURRENCIES,
    FIXED_EXPENSE_CATEGORIES,
    LIABILITY_CURRENCIES,
    SOURCE_UNITS,
    STRATEGY_TYPES,
    build_allocation_board,
    build_fixed_expense_coverage,
    build_leverage_performance,
    build_monthly_summary,
    close_month,
    create_cashflow_allocation,
    delete_cashflow_allocation as delete_cf_allocation_svc,
    enrich_cashflow_entries,
    ensure_draft_closure,
    reopen_month,
    require_month_writable,
    update_cashflow_allocation as update_cf_allocation_svc,
    validate_allocation_capacity,
)

router = APIRouter(prefix="/family-office", tags=["family-office-flow"])

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

FixedExpenseCategory = Literal[
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
]
EntryType = Literal["income", "expense"]
SourceUnit = Literal[
    "employment",
    "consulting",
    "salva",
    "investment_radar",
    "investments",
    "debt",
    "house",
    "family",
    "other",
]
StrategyType = Literal[
    "covered_call",
    "dividend",
    "interest",
    "realized_gain",
    "realized_loss",
    "other",
]
AllocationDestination = Literal[
    "debt",
    "investments",
    "salva",
    "investment_radar",
    "house",
    "emergency_fund",
    "cash",
    "other",
]
AllocationStatus = Literal["proposed", "approved", "executed", "cancelled"]
FoCurrency = Literal["ARS", "USD"]
LevCurrency = Literal["ARS", "USD", "UVA"]


def _finite_nonneg(v: float, field: str) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} inválido") from exc
    if math.isnan(n) or math.isinf(n):
        raise ValueError(f"{field} inválido (NaN/Inf)")
    if n < 0:
        raise ValueError(f"{field} no puede ser negativo")
    return n


def _optional_nonneg(v: float | None, field: str) -> float | None:
    if v is None:
        return None
    return _finite_nonneg(v, field)


def _month_ok(v: str) -> str:
    s = v.strip()
    if not _MONTH_RE.match(s):
        raise ValueError("month debe ser YYYY-MM")
    return s


def _dump_unset(body: BaseModel) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class FixedExpenseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: FixedExpenseCategory
    currency: FoCurrency
    expected_monthly_amount: float
    priority: int = 0
    coverage_order: int = 0
    is_essential: bool = True
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool = True

    @field_validator("expected_monthly_amount")
    @classmethod
    def amt(cls, v: float) -> float:
        return _finite_nonneg(v, "expected_monthly_amount")


class FixedExpenseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: FixedExpenseCategory | None = None
    currency: FoCurrency | None = None
    expected_monthly_amount: float | None = None
    priority: int | None = None
    coverage_order: int | None = None
    is_essential: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None

    @field_validator("expected_monthly_amount")
    @classmethod
    def amt(cls, v: float | None) -> float | None:
        return _optional_nonneg(v, "expected_monthly_amount")


class CashflowCreate(BaseModel):
    date: str = Field(min_length=8, max_length=32)
    month: str | None = Field(default=None, min_length=7, max_length=7)
    entry_type: EntryType
    category: str = Field(min_length=1, max_length=100)
    source_unit: SourceUnit
    currency: FoCurrency
    amount: float
    description: str | None = Field(default=None, max_length=4000)
    fixed_expense_id: int | None = None
    is_fixed_expense: bool = False
    asset_id: int | None = None
    liability_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("amount")
    @classmethod
    def amt(cls, v: float) -> float:
        return _finite_nonneg(v, "amount")

    @field_validator("month")
    @classmethod
    def month_fmt(cls, v: str | None) -> str | None:
        return None if v is None else _month_ok(v)


class CashflowUpdate(BaseModel):
    date: str | None = Field(default=None, min_length=8, max_length=32)
    month: str | None = Field(default=None, min_length=7, max_length=7)
    entry_type: EntryType | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    source_unit: SourceUnit | None = None
    currency: FoCurrency | None = None
    amount: float | None = None
    description: str | None = Field(default=None, max_length=4000)
    fixed_expense_id: int | None = None
    is_fixed_expense: bool | None = None
    asset_id: int | None = None
    liability_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("amount")
    @classmethod
    def amt(cls, v: float | None) -> float | None:
        return _optional_nonneg(v, "amount")

    @field_validator("month")
    @classmethod
    def month_fmt(cls, v: str | None) -> str | None:
        return None if v is None else _month_ok(v)


CashflowAllocationDestination = Literal[
    "fixed_expense",
    "variable_expense",
    "debt",
    "investment",
    "saving",
    "house_project",
    "other",
]


class CashflowAllocationCreate(BaseModel):
    month: str
    currency: FoCurrency
    source_cashflow_entry_id: int
    destination_type: CashflowAllocationDestination = "fixed_expense"
    destination_id: int
    allocated_amount: float
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("month")
    @classmethod
    def month_fmt(cls, v: str) -> str:
        return _month_ok(v)

    @field_validator("allocated_amount")
    @classmethod
    def amt(cls, v: float) -> float:
        n = _finite_nonneg(v, "allocated_amount")
        if n <= 0:
            raise ValueError("allocated_amount debe ser > 0")
        return n


class CashflowAllocationUpdate(BaseModel):
    month: str | None = None
    currency: FoCurrency | None = None
    source_cashflow_entry_id: int | None = None
    destination_type: CashflowAllocationDestination | None = None
    destination_id: int | None = None
    allocated_amount: float | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("month")
    @classmethod
    def month_fmt(cls, v: str | None) -> str | None:
        return None if v is None else _month_ok(v)

    @field_validator("allocated_amount")
    @classmethod
    def amt(cls, v: float | None) -> float | None:
        if v is None:
            return None
        n = _finite_nonneg(v, "allocated_amount")
        if n <= 0:
            raise ValueError("allocated_amount debe ser > 0")
        return n


class InvCashflowCreate(BaseModel):
    month: str
    account_name: str = Field(min_length=1, max_length=200)
    strategy_type: StrategyType
    currency: FoCurrency
    gross_income: float = 0.0
    commissions: float = 0.0
    taxes: float = 0.0
    financing_cost: float = 0.0
    net_cashflow: float | None = None
    linked_asset_id: int | None = None
    fixed_expense_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("month")
    @classmethod
    def month_fmt(cls, v: str) -> str:
        return _month_ok(v)

    @field_validator("commissions", "taxes", "financing_cost")
    @classmethod
    def nonneg(cls, v: float, info) -> float:  # type: ignore[no-untyped-def]
        return _finite_nonneg(v, info.field_name)

    @field_validator("gross_income")
    @classmethod
    def gross_ok(cls, v: float) -> float:
        try:
            n = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError("gross_income inválido") from exc
        if math.isnan(n) or math.isinf(n):
            raise ValueError("gross_income inválido (NaN/Inf)")
        return n


class InvCashflowUpdate(InvCashflowCreate):
    month: str | None = None  # type: ignore[assignment]
    account_name: str | None = None  # type: ignore[assignment]
    strategy_type: StrategyType | None = None  # type: ignore[assignment]
    currency: FoCurrency | None = None  # type: ignore[assignment]


class LeverageCreate(BaseModel):
    month: str
    liability_id: int | None = None
    linked_asset_id: int | None = None
    currency: LevCurrency
    average_balance_used: float = 0.0
    days_used: int = Field(default=0, ge=0)
    nominal_annual_rate: float = 0.0
    interest_paid: float = 0.0
    taxes_and_fees: float = 0.0
    total_financing_cost: float | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("month")
    @classmethod
    def month_fmt(cls, v: str) -> str:
        return _month_ok(v)

    @field_validator(
        "average_balance_used", "nominal_annual_rate", "interest_paid", "taxes_and_fees"
    )
    @classmethod
    def nonneg(cls, v: float, info) -> float:  # type: ignore[no-untyped-def]
        return _finite_nonneg(v, info.field_name)


class LeverageUpdate(LeverageCreate):
    month: str | None = None  # type: ignore[assignment]
    currency: LevCurrency | None = None  # type: ignore[assignment]


class AllocationCreate(BaseModel):
    month: str
    currency: FoCurrency
    available_amount: float
    destination: AllocationDestination
    allocated_amount: float
    status: AllocationStatus = "proposed"
    policy_id: int | None = None
    asset_id: int | None = None
    liability_id: int | None = None
    house_project_id: int | None = None
    rationale: str | None = Field(default=None, max_length=4000)
    expected_return: float | None = None
    expected_monthly_cashflow: float | None = None
    expected_hours_saved: float | None = None
    executed_date: str | None = Field(default=None, max_length=32)

    @field_validator("month")
    @classmethod
    def month_fmt(cls, v: str) -> str:
        return _month_ok(v)

    @field_validator("available_amount", "allocated_amount")
    @classmethod
    def nonneg(cls, v: float, info) -> float:  # type: ignore[no-untyped-def]
        return _finite_nonneg(v, info.field_name)


class AllocationUpdate(BaseModel):
    month: str | None = None
    currency: FoCurrency | None = None
    available_amount: float | None = None
    destination: AllocationDestination | None = None
    allocated_amount: float | None = None
    status: AllocationStatus | None = None
    policy_id: int | None = None
    asset_id: int | None = None
    liability_id: int | None = None
    house_project_id: int | None = None
    rationale: str | None = Field(default=None, max_length=4000)
    expected_return: float | None = None
    expected_monthly_cashflow: float | None = None
    expected_hours_saved: float | None = None
    executed_date: str | None = Field(default=None, max_length=32)

    @field_validator("month")
    @classmethod
    def month_fmt(cls, v: str | None) -> str | None:
        return None if v is None else _month_ok(v)

    @field_validator("available_amount", "allocated_amount")
    @classmethod
    def nonneg(cls, v: float | None, info) -> float | None:  # type: ignore[no-untyped-def]
        return _optional_nonneg(v, info.field_name)


class ClosureNotesBody(BaseModel):
    notes: str | None = Field(default=None, max_length=4000)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@router.get("/monthly-summary")
def monthly_summary(
    month: str = Query(..., min_length=7, max_length=7),
    currency: FoCurrency = Query(...),
) -> dict[str, Any]:
    try:
        m = _month_ok(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_monthly_summary(month=m, currency=currency)


@router.get("/fixed-expense-coverage")
def fixed_expense_coverage(
    month: str = Query(..., min_length=7, max_length=7),
    currency: FoCurrency = Query(...),
) -> dict[str, Any]:
    try:
        m = _month_ok(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_fixed_expense_coverage(month=m, currency=currency)


@router.get("/leverage-performance")
def leverage_performance(
    month: str = Query(..., min_length=7, max_length=7),
) -> dict[str, Any]:
    try:
        m = _month_ok(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_leverage_performance(month=m)


@router.get("/allocation-board")
def allocation_board(
    month: str = Query(..., min_length=7, max_length=7),
    currency: FoCurrency = Query(...),
) -> dict[str, Any]:
    try:
        m = _month_ok(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_allocation_board(month=m, currency=currency)


# ---------------------------------------------------------------------------
# Fixed expenses CRUD
# ---------------------------------------------------------------------------


@router.get("/fixed-expenses")
def list_fixed_expenses(
    active_only: bool = Query(default=True),
    currency: FoCurrency | None = Query(default=None),
) -> list[dict[str, Any]]:
    return flow.list_fixed_expenses(active_only=active_only, currency=currency)


@router.post("/fixed-expenses", status_code=201)
def create_fixed_expense(body: FixedExpenseCreate) -> dict[str, Any]:
    if body.category not in FIXED_EXPENSE_CATEGORIES:
        raise HTTPException(status_code=400, detail="category inválida")
    eid = flow.insert_fixed_expense(**body.model_dump())
    row = flow.get_fixed_expense(eid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear el gasto fijo")
    return row


@router.patch("/fixed-expenses/{expense_id}")
def patch_fixed_expense(expense_id: int, body: FixedExpenseUpdate) -> dict[str, Any]:
    if flow.get_fixed_expense(expense_id) is None:
        raise HTTPException(status_code=404, detail="Gasto fijo no encontrado")
    fields = _dump_unset(body)
    if fields and not flow.update_fixed_expense(expense_id, fields):
        raise HTTPException(status_code=400, detail="Sin cambios")
    return flow.get_fixed_expense(expense_id)  # type: ignore[return-value]


@router.delete("/fixed-expenses/{expense_id}")
def delete_fixed_expense(expense_id: int) -> dict[str, Any]:
    if flow.get_fixed_expense(expense_id) is None:
        raise HTTPException(status_code=404, detail="Gasto fijo no encontrado")
    flow.deactivate_fixed_expense(expense_id)
    return {"ok": True, "id": expense_id, "is_active": False}


# ---------------------------------------------------------------------------
# Cashflow entries CRUD
# ---------------------------------------------------------------------------


@router.get("/cashflow-entries")
def list_cashflow_entries(
    month: str | None = Query(default=None),
    currency: FoCurrency | None = Query(default=None),
) -> list[dict[str, Any]]:
    if month:
        try:
            month = _month_ok(month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = flow.list_cashflow_entries(month=month, currency=currency)
    return enrich_cashflow_entries(rows)


@router.post("/cashflow-entries", status_code=201)
def create_cashflow_entry(body: CashflowCreate) -> dict[str, Any]:
    if body.source_unit not in SOURCE_UNITS:
        raise HTTPException(status_code=400, detail="source_unit inválido")
    if body.fixed_expense_id is not None and flow.get_fixed_expense(body.fixed_expense_id) is None:
        raise HTTPException(status_code=400, detail="fixed_expense_id no existe")
    if body.entry_type == "income" and body.fixed_expense_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Un ingreso no se asocia a gasto fijo; use asignaciones de flujo",
        )
    if body.is_fixed_expense and body.entry_type != "expense":
        raise HTTPException(status_code=400, detail="is_fixed_expense solo aplica a egresos")
    data = body.model_dump()
    month = (data.get("month") or str(data["date"])[:7])[:7]
    try:
        require_month_writable(month=month, currency=body.currency)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    eid = flow.insert_cashflow_entry(**data)
    row = flow.get_cashflow_entry(eid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear la entrada")
    return enrich_cashflow_entries([row])[0]


@router.patch("/cashflow-entries/{entry_id}")
def patch_cashflow_entry(entry_id: int, body: CashflowUpdate) -> dict[str, Any]:
    existing = flow.get_cashflow_entry(entry_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    try:
        require_month_writable(month=str(existing["month"]), currency=str(existing["currency"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = _dump_unset(body)
    entry_type = fields.get("entry_type", existing.get("entry_type"))
    if fields.get("fixed_expense_id") is not None and entry_type == "income":
        raise HTTPException(
            status_code=400,
            detail="Un ingreso no se asocia a gasto fijo; use asignaciones de flujo",
        )
    if fields.get("is_fixed_expense") and entry_type != "expense":
        raise HTTPException(status_code=400, detail="is_fixed_expense solo aplica a egresos")
    if fields and not flow.update_cashflow_entry(entry_id, fields):
        raise HTTPException(status_code=400, detail="Sin cambios")
    row = flow.get_cashflow_entry(entry_id)
    return enrich_cashflow_entries([row])[0]  # type: ignore[arg-type]


@router.delete("/cashflow-entries/{entry_id}")
def delete_cashflow_entry(entry_id: int) -> dict[str, Any]:
    existing = flow.get_cashflow_entry(entry_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    try:
        require_month_writable(month=str(existing["month"]), currency=str(existing["currency"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    flow.delete_cashflow_entry(entry_id)
    return {"ok": True, "id": entry_id}


@router.get("/cashflow-allocations")
def list_cf_allocations(
    month: str | None = Query(default=None),
    currency: FoCurrency | None = Query(default=None),
    source_cashflow_entry_id: int | None = Query(default=None),
    destination_type: CashflowAllocationDestination | None = Query(default=None),
    destination_id: int | None = Query(default=None),
) -> list[dict[str, Any]]:
    if month:
        try:
            month = _month_ok(month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return flow.list_cashflow_allocations(
        month=month,
        currency=currency,
        source_cashflow_entry_id=source_cashflow_entry_id,
        destination_type=destination_type,
        destination_id=destination_id,
    )


@router.post("/cashflow-allocations", status_code=201)
def create_cf_allocation(body: CashflowAllocationCreate) -> dict[str, Any]:
    try:
        return create_cashflow_allocation(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/cashflow-allocations/{allocation_id}")
def patch_cf_allocation(allocation_id: int, body: CashflowAllocationUpdate) -> dict[str, Any]:
    if flow.get_cashflow_allocation(allocation_id) is None:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")
    try:
        return update_cf_allocation_svc(allocation_id, _dump_unset(body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/cashflow-allocations/{allocation_id}")
def delete_cf_allocation(allocation_id: int) -> dict[str, Any]:
    if flow.get_cashflow_allocation(allocation_id) is None:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")
    try:
        delete_cf_allocation_svc(allocation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "id": allocation_id}


# ---------------------------------------------------------------------------
# Investment cashflow CRUD
# ---------------------------------------------------------------------------

@router.get("/investment-cashflow-records")
def list_inv_cf(
    month: str | None = Query(default=None),
    currency: FoCurrency | None = Query(default=None),
) -> list[dict[str, Any]]:
    if month:
        try:
            month = _month_ok(month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return flow.list_investment_cashflows(month=month, currency=currency)


@router.post("/investment-cashflow-records", status_code=201)
def create_inv_cf(body: InvCashflowCreate) -> dict[str, Any]:
    if body.strategy_type not in STRATEGY_TYPES:
        raise HTTPException(status_code=400, detail="strategy_type inválido")
    rid = flow.insert_investment_cashflow(**body.model_dump())
    row = flow.get_investment_cashflow(rid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear el registro")
    return row


@router.patch("/investment-cashflow-records/{record_id}")
def patch_inv_cf(record_id: int, body: InvCashflowUpdate) -> dict[str, Any]:
    if flow.get_investment_cashflow(record_id) is None:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    fields = _dump_unset(body)
    if fields and not flow.update_investment_cashflow(record_id, fields):
        raise HTTPException(status_code=400, detail="Sin cambios")
    return flow.get_investment_cashflow(record_id)  # type: ignore[return-value]


@router.delete("/investment-cashflow-records/{record_id}")
def delete_inv_cf(record_id: int) -> dict[str, Any]:
    if flow.get_investment_cashflow(record_id) is None:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    flow.delete_investment_cashflow(record_id)
    return {"ok": True, "id": record_id}


# ---------------------------------------------------------------------------
# Leverage CRUD
# ---------------------------------------------------------------------------


@router.get("/leverage-records")
def list_leverage(
    month: str | None = Query(default=None),
    currency: LevCurrency | None = Query(default=None),
) -> list[dict[str, Any]]:
    if month:
        try:
            month = _month_ok(month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return flow.list_leverage_records(month=month, currency=currency)


@router.post("/leverage-records", status_code=201)
def create_leverage(body: LeverageCreate) -> dict[str, Any]:
    if body.currency not in LIABILITY_CURRENCIES:
        raise HTTPException(status_code=400, detail="currency no permitida")
    if body.liability_id is not None and repo.get_liability(body.liability_id) is None:
        raise HTTPException(status_code=400, detail="liability_id no existe")
    rid = flow.insert_leverage_record(**body.model_dump())
    row = flow.get_leverage_record(rid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear el registro")
    return row


@router.patch("/leverage-records/{record_id}")
def patch_leverage(record_id: int, body: LeverageUpdate) -> dict[str, Any]:
    if flow.get_leverage_record(record_id) is None:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    fields = _dump_unset(body)
    if fields and not flow.update_leverage_record(record_id, fields):
        raise HTTPException(status_code=400, detail="Sin cambios")
    return flow.get_leverage_record(record_id)  # type: ignore[return-value]


@router.delete("/leverage-records/{record_id}")
def delete_leverage(record_id: int) -> dict[str, Any]:
    if flow.get_leverage_record(record_id) is None:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    flow.delete_leverage_record(record_id)
    return {"ok": True, "id": record_id}


# ---------------------------------------------------------------------------
# Allocations CRUD
# ---------------------------------------------------------------------------


@router.get("/capital-allocations")
def list_allocations(
    month: str | None = Query(default=None),
    currency: FoCurrency | None = Query(default=None),
) -> list[dict[str, Any]]:
    if month:
        try:
            month = _month_ok(month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return flow.list_allocations(month=month, currency=currency)


@router.post("/capital-allocations", status_code=201)
def create_allocation(body: AllocationCreate) -> dict[str, Any]:
    if body.destination not in ALLOCATION_DESTINATIONS:
        raise HTTPException(status_code=400, detail="destination inválido")
    if body.status not in ALLOCATION_STATUSES:
        raise HTTPException(status_code=400, detail="status inválido")
    try:
        validate_allocation_capacity(
            month=body.month,
            currency=body.currency,
            allocated_amount=body.allocated_amount,
            available_amount=body.available_amount,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    aid = flow.insert_allocation(**body.model_dump())
    row = flow.get_allocation(aid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear la asignación")
    return row


@router.patch("/capital-allocations/{allocation_id}")
def patch_allocation(allocation_id: int, body: AllocationUpdate) -> dict[str, Any]:
    existing = flow.get_allocation(allocation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")
    fields = _dump_unset(body)
    merged = {**existing, **fields}
    try:
        validate_allocation_capacity(
            month=str(merged["month"]),
            currency=str(merged["currency"]),
            allocated_amount=float(merged["allocated_amount"]),
            available_amount=float(merged["available_amount"]),
            exclude_id=allocation_id,
            status=str(merged.get("status") or "proposed"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if fields and not flow.update_allocation(allocation_id, fields):
        raise HTTPException(status_code=400, detail="Sin cambios")
    return flow.get_allocation(allocation_id)  # type: ignore[return-value]


@router.delete("/capital-allocations/{allocation_id}")
def delete_allocation(allocation_id: int) -> dict[str, Any]:
    if flow.get_allocation(allocation_id) is None:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")
    flow.delete_allocation(allocation_id)
    return {"ok": True, "id": allocation_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# Month closures
# ---------------------------------------------------------------------------


@router.get("/month-closures")
def list_closures(limit: int = Query(default=24, ge=1, le=120)) -> list[dict[str, Any]]:
    return flow.list_month_closures(limit=limit)


@router.get("/month-closures/{month}/{currency}")
def get_closure(month: str, currency: FoCurrency) -> dict[str, Any]:
    try:
        m = _month_ok(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = flow.get_month_closure(m, currency)
    if row is None:
        return ensure_draft_closure(month=m, currency=currency)
    return row


@router.post("/month-closures/{month}/{currency}/draft", status_code=201)
def create_draft_closure(month: str, currency: FoCurrency) -> dict[str, Any]:
    try:
        m = _month_ok(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ensure_draft_closure(month=m, currency=currency)


@router.post("/month-closures/{month}/{currency}/close")
def close_month_endpoint(
    month: str, currency: FoCurrency, body: ClosureNotesBody | None = None
) -> dict[str, Any]:
    try:
        m = _month_ok(month)
        return close_month(month=m, currency=currency, notes=(body.notes if body else None))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/month-closures/{month}/{currency}/reopen")
def reopen_month_endpoint(
    month: str, currency: FoCurrency, body: ClosureNotesBody | None = None
) -> dict[str, Any]:
    try:
        m = _month_ok(month)
        return reopen_month(month=m, currency=currency, notes=(body.notes if body else None))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
