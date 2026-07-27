from __future__ import annotations

import math
import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from persistence.sqlite import family_office_repo as repo
from services.family_office import (
    ASSET_CATEGORIES,
    ASSET_CURRENCIES,
    HOUSE_PRIORITIES,
    HOUSE_STATUSES,
    LIABILITY_CURRENCIES,
    LIABILITY_TYPES,
    LIQUIDITIES,
    OWNERSHIP_STATUSES,
    POLICY_DESTINATIONS,
    SNAPSHOT_CURRENCIES,
    build_dashboard,
    compute_snapshot_free_cashflow,
)

router = APIRouter(prefix="/family-office", tags=["family-office"])

AssetCategory = Literal[
    "real_estate", "vehicle", "financial", "business", "cash", "other"
]
OwnershipStatus = Literal["owned", "mortgaged", "purchase_agreement", "other"]
AssetCurrency = Literal["ARS", "USD"]
Liquidity = Literal["high", "medium", "low"]
LiabilityType = Literal[
    "mortgage_uva",
    "family_debt",
    "overdraft",
    "vehicle_loan",
    "personal_loan",
    "other",
]
LiabilityCurrency = Literal["ARS", "USD", "UVA"]
PolicyDestination = Literal[
    "debt",
    "investments",
    "salva",
    "investment_radar",
    "house",
    "emergency_fund",
    "other",
]
HousePriority = Literal["necessary", "functional", "aesthetic"]
HouseStatus = Literal["planned", "approved", "in_progress", "completed", "paused"]
SnapshotCurrency = Literal["ARS", "USD"]

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AssetCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: AssetCategory
    ownership_status: OwnershipStatus
    currency: AssetCurrency
    estimated_value: float
    valuation_date: str = Field(min_length=8, max_length=32)
    liquidity: Liquidity
    generates_cashflow: bool = False
    monthly_cashflow: float = 0.0
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool = True

    @field_validator("estimated_value", "monthly_cashflow")
    @classmethod
    def amounts_ok(cls, v: float, info) -> float:  # type: ignore[no-untyped-def]
        return _finite_nonneg(v, info.field_name)


class AssetUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: AssetCategory | None = None
    ownership_status: OwnershipStatus | None = None
    currency: AssetCurrency | None = None
    estimated_value: float | None = None
    valuation_date: str | None = Field(default=None, min_length=8, max_length=32)
    liquidity: Liquidity | None = None
    generates_cashflow: bool | None = None
    monthly_cashflow: float | None = None
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None

    @field_validator("estimated_value", "monthly_cashflow")
    @classmethod
    def amounts_ok(cls, v: float | None, info) -> float | None:  # type: ignore[no-untyped-def]
        return _optional_nonneg(v, info.field_name)


class LiabilityCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    liability_type: LiabilityType
    currency: LiabilityCurrency
    original_amount: float
    outstanding_balance: float
    installment_amount: float = 0.0
    installments_remaining: int = Field(default=0, ge=0)
    nominal_annual_rate: float = 0.0
    effective_annual_cost: float | None = None
    next_due_date: str | None = Field(default=None, max_length=32)
    linked_asset_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool = True
    rate_type: Literal["fixed", "variable", "uva", "family", "unknown"] = "unknown"
    current_installment: float | None = None
    total_financial_cost: float | None = None
    prepayment_cost: float | None = None
    allows_partial_prepayment: bool = True
    maturity_date: str | None = Field(default=None, max_length=32)
    priority_override: int | None = None

    @field_validator(
        "original_amount",
        "outstanding_balance",
        "installment_amount",
        "nominal_annual_rate",
    )
    @classmethod
    def amounts_ok(cls, v: float, info) -> float:  # type: ignore[no-untyped-def]
        return _finite_nonneg(v, info.field_name)

    @field_validator(
        "effective_annual_cost",
        "current_installment",
        "total_financial_cost",
        "prepayment_cost",
    )
    @classmethod
    def eac_ok(cls, v: float | None, info) -> float | None:  # type: ignore[no-untyped-def]
        return _optional_nonneg(v, info.field_name)


class LiabilityUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    liability_type: LiabilityType | None = None
    currency: LiabilityCurrency | None = None
    original_amount: float | None = None
    outstanding_balance: float | None = None
    installment_amount: float | None = None
    installments_remaining: int | None = Field(default=None, ge=0)
    nominal_annual_rate: float | None = None
    effective_annual_cost: float | None = None
    next_due_date: str | None = Field(default=None, max_length=32)
    linked_asset_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None
    rate_type: Literal["fixed", "variable", "uva", "family", "unknown"] | None = None
    current_installment: float | None = None
    total_financial_cost: float | None = None
    prepayment_cost: float | None = None
    allows_partial_prepayment: bool | None = None
    maturity_date: str | None = Field(default=None, max_length=32)
    priority_override: int | None = None

    @field_validator(
        "original_amount",
        "outstanding_balance",
        "installment_amount",
        "nominal_annual_rate",
        "effective_annual_cost",
        "current_installment",
        "total_financial_cost",
        "prepayment_cost",
    )
    @classmethod
    def amounts_ok(cls, v: float | None, info) -> float | None:  # type: ignore[no-untyped-def]
        return _optional_nonneg(v, info.field_name)


class PolicyCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    destination: PolicyDestination
    minimum_monthly_amount: float | None = None
    maximum_monthly_amount: float | None = None
    priority: int = 0
    is_mandatory: bool = False
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool = True

    @field_validator("minimum_monthly_amount", "maximum_monthly_amount")
    @classmethod
    def amounts_ok(cls, v: float | None, info) -> float | None:  # type: ignore[no-untyped-def]
        return _optional_nonneg(v, info.field_name)

    @model_validator(mode="after")
    def min_max(self) -> PolicyCreateBody:
        if (
            self.minimum_monthly_amount is not None
            and self.maximum_monthly_amount is not None
            and self.minimum_monthly_amount > self.maximum_monthly_amount
        ):
            raise ValueError("minimum_monthly_amount no puede superar maximum_monthly_amount")
        return self


class PolicyUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    destination: PolicyDestination | None = None
    minimum_monthly_amount: float | None = None
    maximum_monthly_amount: float | None = None
    priority: int | None = None
    is_mandatory: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None

    @field_validator("minimum_monthly_amount", "maximum_monthly_amount")
    @classmethod
    def amounts_ok(cls, v: float | None, info) -> float | None:  # type: ignore[no-untyped-def]
        return _optional_nonneg(v, info.field_name)


class HouseProjectCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    priority: HousePriority
    estimated_cost: float
    paid_amount: float = 0.0
    currency: AssetCurrency
    target_date: str | None = Field(default=None, max_length=32)
    status: HouseStatus = "planned"
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("estimated_cost", "paid_amount")
    @classmethod
    def amounts_ok(cls, v: float, info) -> float:  # type: ignore[no-untyped-def]
        return _finite_nonneg(v, info.field_name)


class HouseProjectUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    priority: HousePriority | None = None
    estimated_cost: float | None = None
    paid_amount: float | None = None
    currency: AssetCurrency | None = None
    target_date: str | None = Field(default=None, max_length=32)
    status: HouseStatus | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("estimated_cost", "paid_amount")
    @classmethod
    def amounts_ok(cls, v: float | None, info) -> float | None:  # type: ignore[no-untyped-def]
        return _optional_nonneg(v, info.field_name)


class SnapshotCreateBody(BaseModel):
    month: str = Field(min_length=7, max_length=7, description="YYYY-MM")
    active_income: float = 0.0
    consulting_income: float = 0.0
    scalable_income: float = 0.0
    fixed_expenses: float = 0.0
    debt_payments: float = 0.0
    house_spending: float = 0.0
    investment_contributions: float = 0.0
    free_cashflow: float | None = None
    currency: SnapshotCurrency = "ARS"
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("month")
    @classmethod
    def month_fmt(cls, v: str) -> str:
        s = v.strip()
        if not _MONTH_RE.match(s):
            raise ValueError("month debe ser YYYY-MM")
        return s

    @field_validator(
        "active_income",
        "consulting_income",
        "scalable_income",
        "fixed_expenses",
        "debt_payments",
        "house_spending",
        "investment_contributions",
    )
    @classmethod
    def amounts_ok(cls, v: float, info) -> float:  # type: ignore[no-untyped-def]
        return _finite_nonneg(v, info.field_name)

    @field_validator("free_cashflow")
    @classmethod
    def fcf_ok(cls, v: float | None) -> float | None:
        if v is None:
            return None
        try:
            n = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError("free_cashflow inválido") from exc
        if math.isnan(n) or math.isinf(n):
            raise ValueError("free_cashflow inválido (NaN/Inf)")
        return n


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_linked_asset(linked_asset_id: int | None) -> None:
    if linked_asset_id is None:
        return
    if repo.get_asset(int(linked_asset_id)) is None:
        raise HTTPException(status_code=400, detail="linked_asset_id no existe")


def _dump_unset(body: BaseModel) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True)


# ---------------------------------------------------------------------------
# Dashboard / snapshots
# ---------------------------------------------------------------------------


@router.get("/dashboard")
def get_dashboard() -> dict[str, Any]:
    return build_dashboard()


@router.get("/snapshots")
def get_snapshots(limit: int = Query(default=24, ge=1, le=120)) -> list[dict[str, Any]]:
    return repo.list_snapshots(limit=limit)


@router.post("/snapshots", status_code=201)
def post_snapshot(body: SnapshotCreateBody) -> dict[str, Any]:
    fcf = body.free_cashflow
    if fcf is None:
        fcf = compute_snapshot_free_cashflow(
            active_income=body.active_income,
            consulting_income=body.consulting_income,
            scalable_income=body.scalable_income,
            fixed_expenses=body.fixed_expenses,
            debt_payments=body.debt_payments,
            house_spending=body.house_spending,
            investment_contributions=body.investment_contributions,
        )
    sid = repo.upsert_snapshot(
        month=body.month,
        active_income=body.active_income,
        consulting_income=body.consulting_income,
        scalable_income=body.scalable_income,
        fixed_expenses=body.fixed_expenses,
        debt_payments=body.debt_payments,
        house_spending=body.house_spending,
        investment_contributions=body.investment_contributions,
        free_cashflow=fcf,
        currency=body.currency,
        notes=body.notes,
    )
    row = repo.get_snapshot_by_month(body.month, body.currency)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo persistir el snapshot")
    row["id"] = sid
    return row


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@router.get("/assets")
def list_assets(
    active_only: bool = Query(default=True),
) -> list[dict[str, Any]]:
    return repo.list_assets(active_only=active_only)


@router.post("/assets", status_code=201)
def create_asset(body: AssetCreateBody) -> dict[str, Any]:
    if body.currency not in ASSET_CURRENCIES:
        raise HTTPException(status_code=400, detail="currency no permitida")
    if body.category not in ASSET_CATEGORIES:
        raise HTTPException(status_code=400, detail="category inválida")
    if body.ownership_status not in OWNERSHIP_STATUSES:
        raise HTTPException(status_code=400, detail="ownership_status inválido")
    if body.liquidity not in LIQUIDITIES:
        raise HTTPException(status_code=400, detail="liquidity inválida")
    aid = repo.insert_asset(**body.model_dump())
    row = repo.get_asset(aid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear el activo")
    return row


@router.get("/assets/{asset_id}")
def get_asset(asset_id: int) -> dict[str, Any]:
    row = repo.get_asset(asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    return row


@router.patch("/assets/{asset_id}")
def patch_asset(asset_id: int, body: AssetUpdateBody) -> dict[str, Any]:
    if repo.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    fields = _dump_unset(body)
    if not fields:
        return repo.get_asset(asset_id)  # type: ignore[return-value]
    if "currency" in fields and fields["currency"] not in ASSET_CURRENCIES:
        raise HTTPException(status_code=400, detail="currency no permitida")
    ok = repo.update_asset(asset_id, fields)
    if not ok:
        raise HTTPException(status_code=400, detail="Sin cambios")
    return repo.get_asset(asset_id)  # type: ignore[return-value]


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int) -> dict[str, Any]:
    if repo.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    repo.deactivate_asset(asset_id)
    return {"ok": True, "id": asset_id, "is_active": False}


# ---------------------------------------------------------------------------
# Liabilities
# ---------------------------------------------------------------------------


@router.get("/liabilities")
def list_liabilities(
    active_only: bool = Query(default=True),
) -> list[dict[str, Any]]:
    return repo.list_liabilities(active_only=active_only)


@router.post("/liabilities", status_code=201)
def create_liability(body: LiabilityCreateBody) -> dict[str, Any]:
    if body.currency not in LIABILITY_CURRENCIES:
        raise HTTPException(status_code=400, detail="currency no permitida")
    if body.liability_type not in LIABILITY_TYPES:
        raise HTTPException(status_code=400, detail="liability_type inválido")
    _ensure_linked_asset(body.linked_asset_id)
    lid = repo.insert_liability(**body.model_dump())
    row = repo.get_liability(lid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear el pasivo")
    return row


@router.get("/liabilities/{liability_id}")
def get_liability(liability_id: int) -> dict[str, Any]:
    row = repo.get_liability(liability_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pasivo no encontrado")
    return row


@router.patch("/liabilities/{liability_id}")
def patch_liability(liability_id: int, body: LiabilityUpdateBody) -> dict[str, Any]:
    if repo.get_liability(liability_id) is None:
        raise HTTPException(status_code=404, detail="Pasivo no encontrado")
    fields = _dump_unset(body)
    if not fields:
        return repo.get_liability(liability_id)  # type: ignore[return-value]
    if "currency" in fields and fields["currency"] not in LIABILITY_CURRENCIES:
        raise HTTPException(status_code=400, detail="currency no permitida")
    if "linked_asset_id" in fields:
        _ensure_linked_asset(fields["linked_asset_id"])
    ok = repo.update_liability(liability_id, fields)
    if not ok:
        raise HTTPException(status_code=400, detail="Sin cambios")
    return repo.get_liability(liability_id)  # type: ignore[return-value]


@router.delete("/liabilities/{liability_id}")
def delete_liability(liability_id: int) -> dict[str, Any]:
    if repo.get_liability(liability_id) is None:
        raise HTTPException(status_code=404, detail="Pasivo no encontrado")
    repo.deactivate_liability(liability_id)
    return {"ok": True, "id": liability_id, "is_active": False}


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


@router.get("/policies")
def list_policies(
    active_only: bool = Query(default=True),
) -> list[dict[str, Any]]:
    return repo.list_policies(active_only=active_only)


@router.post("/policies", status_code=201)
def create_policy(body: PolicyCreateBody) -> dict[str, Any]:
    if body.destination not in POLICY_DESTINATIONS:
        raise HTTPException(status_code=400, detail="destination inválido")
    pid = repo.insert_policy(**body.model_dump())
    row = repo.get_policy(pid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear la política")
    return row


@router.get("/policies/{policy_id}")
def get_policy(policy_id: int) -> dict[str, Any]:
    row = repo.get_policy(policy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Política no encontrada")
    return row


@router.patch("/policies/{policy_id}")
def patch_policy(policy_id: int, body: PolicyUpdateBody) -> dict[str, Any]:
    existing = repo.get_policy(policy_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Política no encontrada")
    fields = _dump_unset(body)
    if not fields:
        return existing
    mn = fields.get("minimum_monthly_amount", existing.get("minimum_monthly_amount"))
    mx = fields.get("maximum_monthly_amount", existing.get("maximum_monthly_amount"))
    if mn is not None and mx is not None and float(mn) > float(mx):
        raise HTTPException(
            status_code=400,
            detail="minimum_monthly_amount no puede superar maximum_monthly_amount",
        )
    ok = repo.update_policy(policy_id, fields)
    if not ok:
        raise HTTPException(status_code=400, detail="Sin cambios")
    return repo.get_policy(policy_id)  # type: ignore[return-value]


@router.delete("/policies/{policy_id}")
def delete_policy(policy_id: int) -> dict[str, Any]:
    if repo.get_policy(policy_id) is None:
        raise HTTPException(status_code=404, detail="Política no encontrada")
    repo.deactivate_policy(policy_id)
    return {"ok": True, "id": policy_id, "is_active": False}


# ---------------------------------------------------------------------------
# House projects
# ---------------------------------------------------------------------------


@router.get("/house-projects")
def list_house_projects(
    active_only: bool = Query(default=True),
) -> list[dict[str, Any]]:
    return repo.list_house_projects(active_only=active_only)


@router.post("/house-projects", status_code=201)
def create_house_project(body: HouseProjectCreateBody) -> dict[str, Any]:
    if body.priority not in HOUSE_PRIORITIES:
        raise HTTPException(status_code=400, detail="priority inválida")
    if body.status not in HOUSE_STATUSES:
        raise HTTPException(status_code=400, detail="status inválido")
    if body.currency not in ASSET_CURRENCIES:
        raise HTTPException(status_code=400, detail="currency no permitida")
    pid = repo.insert_house_project(**body.model_dump())
    row = repo.get_house_project(pid)
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear el proyecto")
    return row


@router.get("/house-projects/{project_id}")
def get_house_project(project_id: int) -> dict[str, Any]:
    row = repo.get_house_project(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return row


@router.patch("/house-projects/{project_id}")
def patch_house_project(project_id: int, body: HouseProjectUpdateBody) -> dict[str, Any]:
    if repo.get_house_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    fields = _dump_unset(body)
    if not fields:
        return repo.get_house_project(project_id)  # type: ignore[return-value]
    ok = repo.update_house_project(project_id, fields)
    if not ok:
        raise HTTPException(status_code=400, detail="Sin cambios")
    return repo.get_house_project(project_id)  # type: ignore[return-value]


@router.delete("/house-projects/{project_id}")
def delete_house_project(project_id: int) -> dict[str, Any]:
    if repo.get_house_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    repo.deactivate_house_project(project_id)
    return {"ok": True, "id": project_id, "is_active": False}
