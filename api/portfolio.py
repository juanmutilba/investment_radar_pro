from __future__ import annotations

import json
import math
from datetime import date
from typing import Any, Literal

import sqlite3
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from persistence.sqlite.positions_repo import (
    append_management_event,
    close_position_row,
    get_position_by_id,
    insert_open_position,
    insert_trade_position,
    list_positions_by_status,
    list_trades_filtered,
    portfolio_instrument_metrics,
    row_as_mapping,
    update_trade_position_fields,
)
from services.portfolio_snapshots import (
    ASSET_ARGENTINA,
    ASSET_CEDEAR,
    ASSET_USA,
    autocomplete_tickers,
    compute_realized_return_argentina_usd_mep,
    compute_realized_return_cedear_usd,
    compute_realized_return_pct,
    compute_return_pct_open,
    current_market_snapshot,
    snapshot_fields_for_buy,
    snapshot_fields_for_sell,
)
from services.portfolio_alerts import buy_alert_label_or_default, sell_alert_label_or_default
from services.portfolio_strategy_accounting import (
    compute_strategy_cashflow_pnl,
    compute_strategy_cashflow_total,
    compute_strategy_is_closed,
    normalize_leg_multiplier,
    option_strategy_use_cashflow_pnl,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

AssetType = Literal["USA", "Argentina", "CEDEAR"]
PortfolioKind = Literal["radar", "real"]


class PositionCreateBody(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    asset_type: AssetType
    quantity: float = Field(gt=0)
    buy_date: str = Field(min_length=8, max_length=32)
    buy_price_ars: float | None = None
    buy_price_usd: float | None = None
    tc_mep_compra: float | None = Field(
        default=None,
        description="TC MEP (ARS por USD) al momento de la compra; Argentina y CEDEAR.",
    )
    notes: str | None = Field(default=None, max_length=4000)
    portfolio_type: PortfolioKind = Field(
        default="radar",
        description="radar = seguimiento señales app; real = operaciones reales.",
    )


class PositionCloseBody(BaseModel):
    sell_date: str = Field(min_length=8, max_length=32)
    sell_price_ars: float | None = None
    sell_price_usd: float | None = None
    sell_notes: str | None = Field(default=None, max_length=4000)
    tc_mep_venta: float | None = Field(
        default=None,
        description="TC MEP al momento de la venta; Argentina y CEDEAR.",
    )
    sell_price_cedear_usd: float | None = None
    sell_price_usa: float | None = None
    sell_gap: float | None = None


InstrumentKind = Literal["stock", "option", "option_strategy"]
StrategyKind = Literal[
    "covered_call",
    "csp",
    "bull_call_spread",
    "bear_put_spread",
    "collar",
    "long_call",
    "long_put",
    "custom",
]


class TradeLegBody(BaseModel):
    leg_type: Literal["call", "put", "stock", "cash"]
    action: Literal["buy", "sell"]
    symbol: str = Field(min_length=1, max_length=64)
    strike: float | None = None
    expiration: str | None = Field(default=None, max_length=32)
    premium: float | None = None
    quantity: float = Field(default=1.0, gt=0)
    multiplier: float = Field(default=100.0, gt=0)


class TradeManagementEventBody(BaseModel):
    id: str | None = Field(default=None, max_length=64)
    date: str = Field(min_length=8, max_length=32)
    event_type: Literal["open", "adjustment", "roll", "partial_close", "full_close", "note"]
    description: str = ""
    debit_credit: float | None = None
    underlying_price: float | None = None
    iv: float | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("debit_credit", mode="before")
    @classmethod
    def debit_credit_numeric(cls, v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            x = float(v)
        except (TypeError, ValueError) as e:
            raise ValueError("debit_credit debe ser numérico") from e
        if math.isnan(x) or math.isinf(x):
            raise ValueError("debit_credit inválido (NaN/Inf)")
        return x


class TradeCreateBody(BaseModel):
    """Alta de opción o estrategia; acciones siguen en POST /portfolio/positions."""

    instrument_type: Literal["option", "option_strategy"]
    ticker: str = Field(min_length=1, max_length=64)
    asset_type: AssetType
    quantity: float = Field(gt=0)
    buy_date: str = Field(min_length=8, max_length=32)
    buy_price_ars: float | None = None
    buy_price_usd: float | None = None
    notes: str | None = Field(default=None, max_length=4000)
    tc_mep_compra: float | None = None
    underlying_symbol: str | None = Field(default=None, max_length=32)
    strategy_type: StrategyKind
    option_expiration: str | None = Field(default=None, max_length=32)
    initial_debit_credit: float | None = None
    committed_capital: float | None = None
    max_risk: float | None = None
    max_profit: float | None = None
    opening_underlying_price: float | None = None
    opening_iv: float | None = None
    legs: list[TradeLegBody] = Field(default_factory=list)
    management_events: list[TradeManagementEventBody] = Field(default_factory=list)
    portfolio_type: PortfolioKind | None = Field(
        default=None,
        description="radar | real; si no se envía, el backend usa real.",
    )
    allow_empty_legs: bool = Field(
        default=False,
        description="Si true, permite legs vacíos con strategy distinta de custom.",
    )

    @model_validator(mode="after")
    def validate_option_strategy(self) -> TradeCreateBody:
        if self.instrument_type != "option_strategy":
            return self
        if not (self.underlying_symbol or "").strip():
            raise ValueError("underlying_symbol es obligatorio para option_strategy")
        if not self.legs and self.strategy_type != "custom" and not self.allow_empty_legs:
            raise ValueError("legs no puede estar vacío salvo strategy_type=custom o allow_empty_legs=true")
        return self


class TradePatchBody(BaseModel):
    ticker: str | None = Field(default=None, min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=4000)
    quantity: float | None = Field(default=None, gt=0)
    underlying_symbol: str | None = Field(default=None, max_length=32)
    strategy_type: StrategyKind | None = None
    option_expiration: str | None = Field(default=None, max_length=32)
    initial_debit_credit: float | None = None
    committed_capital: float | None = None
    max_risk: float | None = None
    max_profit: float | None = None
    opening_underlying_price: float | None = None
    opening_iv: float | None = None
    instrument_type: InstrumentKind | None = None
    legs: list[TradeLegBody] | None = None
    management_events: list[TradeManagementEventBody] | None = None
    portfolio_type: PortfolioKind | None = None
    allow_empty_legs: bool | None = Field(
        default=None,
        description="Solo validación al actualizar legs/instrument_type; None = false.",
    )


class TradeEventAppendBody(TradeManagementEventBody):
    pass


def _query_portfolio_type(raw: str) -> str:
    s = (raw or "all").strip().lower()
    return s if s in ("radar", "real", "all") else "all"


def _norm_portfolio_type(d: dict[str, Any]) -> None:
    pt = str(d.get("portfolio_type") or "radar").lower()
    d["portfolio_type"] = pt if pt in ("radar", "real") else "radar"


def _attach_strategy_accounting_fields(d: dict[str, Any]) -> None:
    if str(d.get("instrument_type") or "").lower() != "option_strategy":
        return
    d["strategy_cashflow_total"] = round(compute_strategy_cashflow_total(d), 4)
    d["strategy_is_closed"] = compute_strategy_is_closed(d)
    pnl = compute_strategy_cashflow_pnl(d)
    d["strategy_realized_pnl"] = round(pnl, 4) if pnl is not None else None
    if not d["strategy_is_closed"]:
        d["strategy_pnl_accounting"] = None
    else:
        d["strategy_pnl_accounting"] = "cashflow" if option_strategy_use_cashflow_pnl(d) else "legacy"


def _normalize_trade_legs_dump(legs: list[TradeLegBody]) -> list[dict[str, Any]]:
    return [normalize_leg_multiplier(leg.model_dump()) for leg in legs]


def _validate_option_strategy_merged(
    *,
    instrument_type: str,
    underlying_symbol: str | None,
    strategy_type: str | None,
    legs: list[dict[str, Any]] | None,
    allow_empty_legs: bool,
) -> None:
    if instrument_type != "option_strategy":
        return
    if not (underlying_symbol or "").strip():
        raise HTTPException(status_code=400, detail="underlying_symbol es obligatorio para option_strategy")
    st = (strategy_type or "custom").strip() or "custom"
    leg_n = len(legs or [])
    if leg_n == 0 and st != "custom" and not allow_empty_legs:
        raise HTTPException(
            status_code=400,
            detail="legs no puede estar vacío salvo strategy_type=custom o allow_empty_legs=true",
        )


def _validate_append_event_debit(body: TradeEventAppendBody) -> None:
    if body.debit_credit is None:
        return
    if math.isnan(float(body.debit_credit)) or math.isinf(float(body.debit_credit)):
        raise HTTPException(status_code=400, detail="debit_credit inválido")


def _attach_trade_json_fields(d: dict[str, Any]) -> None:
    for src, dst in (("legs_json", "legs"), ("management_events_json", "management_events")):
        raw = d.get(src)
        try:
            parsed = json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError):
            parsed = []
        if not isinstance(parsed, list):
            parsed = []
        d[dst] = parsed


def _serialize_trade_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row_as_mapping(row))
    _norm_portfolio_type(d)
    _attach_trade_json_fields(d)
    _attach_strategy_accounting_fields(d)
    d.pop("legs_json", None)
    d.pop("management_events_json", None)
    it = str(d.get("instrument_type") or "stock").lower()
    d["instrument_type"] = it if it in ("stock", "option", "option_strategy") else "stock"
    return d


def _enrich_open_row(row: sqlite3.Row) -> dict[str, Any]:
    d = row_as_mapping(row)
    _norm_portfolio_type(d)
    _attach_trade_json_fields(d)
    instr = str(d.get("instrument_type") or "stock").lower()
    if instr in ("option", "option_strategy"):
        d["current_score"] = None
        d["current_signalstate"] = None
        d["current_price_ars"] = None
        d["current_price_usd"] = None
        d["buy_alert_label"] = None
        d["return_pct"] = None
        try:
            d0 = date.fromisoformat(str(d.get("buy_date") or "")[:10])
            d["days_in_position"] = (date.today() - d0).days
        except ValueError:
            d["days_in_position"] = None
        _attach_strategy_accounting_fields(d)
        d.pop("legs_json", None)
        d.pop("management_events_json", None)
        return d
    m = current_market_snapshot(d["ticker"], d["asset_type"])
    d["current_score"] = m["current_score"]
    d["current_signalstate"] = m["current_signalstate"]
    d["current_price_ars"] = m["current_price_ars"]
    d["current_price_usd"] = m["current_price_usd"]
    # Cartera abierta CEDEAR: precio principal en USD = ref USA; CCL local solo auxiliar.
    if d.get("asset_type") == ASSET_CEDEAR:
        d["current_price_ars"] = None
        d["current_price_cedear_usd"] = m.get("current_price_cedear_usd")
    d["buy_alert_label"] = buy_alert_label_or_default(ticker=d.get("ticker"), buy_date=d.get("buy_date"))
    cur_ars = m["current_price_ars"]
    cur_usd = m["current_price_usd"]
    if d.get("asset_type") == ASSET_CEDEAR:
        cur_ars = None
    d["return_pct"] = compute_return_pct_open(
        asset_type=d["asset_type"],
        buy_price_ars=d.get("buy_price_ars"),
        buy_price_usd=d.get("buy_price_usd"),
        cur_ars=cur_ars,
        cur_usd=cur_usd,
    )
    try:
        d0 = date.fromisoformat(str(d.get("buy_date") or "")[:10])
        d["days_in_position"] = (date.today() - d0).days
    except ValueError:
        d["days_in_position"] = None
    d.pop("legs_json", None)
    d.pop("management_events_json", None)
    return d


def _history_row(row: sqlite3.Row) -> dict[str, Any]:
    d = row_as_mapping(row)
    _norm_portfolio_type(d)
    _attach_trade_json_fields(d)
    _attach_strategy_accounting_fields(d)
    out: dict[str, Any] = {
        "id": d["id"],
        "ticker": d["ticker"],
        "asset_type": d["asset_type"],
        "portfolio_type": d["portfolio_type"],
        "instrument_type": str(d.get("instrument_type") or "stock"),
        "buy_date": d.get("buy_date"),
        "sell_date": d.get("sell_date"),
        "buy_price_ars": d.get("buy_price_ars"),
        "buy_price_usd": d.get("buy_price_usd"),
        "sell_price_ars": d.get("sell_price_ars"),
        "sell_price_usd": d.get("sell_price_usd"),
        "tc_mep_compra": d.get("tc_mep_compra"),
        "tc_mep_venta": d.get("tc_mep_venta"),
        "score_at_buy": d.get("score_at_buy"),
        "score_at_sell": d.get("score_at_sell"),
        "signalstate_at_buy": d.get("signalstate_at_buy"),
        "signalstate_at_sell": d.get("signalstate_at_sell"),
        "realized_return_pct": d.get("realized_return_pct"),
        "realized_return_usd_pct": d.get("realized_return_usd_pct"),
        "holding_days": d.get("holding_days"),
        "sell_alert_label": sell_alert_label_or_default(ticker=d.get("ticker"), sell_date=d.get("sell_date")),
        "underlying_symbol": d.get("underlying_symbol"),
        "strategy_type": d.get("strategy_type"),
        "legs": d.get("legs") or [],
        "management_events": d.get("management_events") or [],
        "strategy_cashflow_total": d.get("strategy_cashflow_total"),
        "strategy_is_closed": d.get("strategy_is_closed"),
        "strategy_realized_pnl": d.get("strategy_realized_pnl"),
        "strategy_pnl_accounting": d.get("strategy_pnl_accounting"),
        "notes": d.get("notes"),
        "sell_notes": d.get("sell_notes"),
    }
    return out


@router.post("/positions")
def create_position(body: PositionCreateBody):
    t = body.ticker.strip().upper()
    snap = snapshot_fields_for_buy(t, body.asset_type)
    buy_ars = body.buy_price_ars
    buy_usd = body.buy_price_usd
    tc_mep_c = body.tc_mep_compra
    if body.asset_type == ASSET_CEDEAR:
        buy_ars = None
        # Costo en USD: lo ingresado por el usuario; no persistir precio ARS en CEDEAR.
    elif body.asset_type == ASSET_USA:
        tc_mep_c = None
    pid = insert_open_position(
        ticker=t,
        asset_type=body.asset_type,
        quantity=body.quantity,
        buy_date=body.buy_date.strip(),
        buy_price_ars=buy_ars,
        buy_price_usd=buy_usd,
        notes=body.notes,
        tc_mep_compra=tc_mep_c,
        buy_price_cedear_usd=snap.get("buy_price_cedear_usd"),
        buy_price_usa=snap.get("buy_price_usa"),
        buy_gap=snap.get("buy_gap"),
        score_at_buy=snap.get("score_at_buy"),
        signalstate_at_buy=snap.get("signalstate_at_buy"),
        techscore_at_buy=snap.get("techscore_at_buy"),
        fundscore_at_buy=snap.get("fundscore_at_buy"),
        riskscore_at_buy=snap.get("riskscore_at_buy"),
        portfolio_type=body.portfolio_type,
    )
    return {"id": pid, "status": "ok"}


@router.get("/positions/open")
def list_open_positions(
    portfolio_type: str = Query(
        "all",
        description="radar | real | all",
    ),
):
    pt = _query_portfolio_type(portfolio_type)
    rows = list_positions_by_status("open", portfolio_type=pt)
    return [_enrich_open_row(r) for r in rows]


@router.get("/positions/history")
def list_history(
    portfolio_type: str = Query(
        "all",
        description="radar | real | all",
    ),
):
    pt = _query_portfolio_type(portfolio_type)
    rows = list_positions_by_status("closed", portfolio_type=pt)
    return [_history_row(r) for r in rows]


@router.get("/tickers/autocomplete")
def tickers_autocomplete(
    asset_type: AssetType = Query(..., description="USA | Argentina | CEDEAR"),
    q: str = Query(..., min_length=1, max_length=32),
    limit: int = Query(default=30, ge=1, le=200),
):
    """
    Autocomplete de ticker para la carga de compra.
    Best-effort: usa el último export radar y/o snapshot CEDEAR.
    """
    return autocomplete_tickers(asset_type=asset_type, q=q, limit=limit)


@router.post("/positions/{position_id}/close")
def close_position_endpoint(position_id: int, body: PositionCloseBody):
    row = get_position_by_id(position_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Posición no encontrada")
    d = row_as_mapping(row)
    if d.get("status") != "open":
        raise HTTPException(status_code=400, detail="La posición ya está cerrada")

    instr = str(d.get("instrument_type") or "stock").lower()
    if instr in ("option", "option_strategy"):
        try:
            d0 = date.fromisoformat(str(d["buy_date"])[:10])
            d1 = date.fromisoformat(body.sell_date.strip()[:10])
            hold = (d1 - d0).days
        except ValueError:
            hold = None
        tc_mep_venta = body.tc_mep_venta if d["asset_type"] in (ASSET_ARGENTINA, ASSET_CEDEAR) else None
        rr: float | None = None
        rr_usd: float | None = None
        at = d["asset_type"]
        if at == ASSET_ARGENTINA:
            rr = compute_realized_return_pct(
                asset_type=at,
                buy_price_ars=d.get("buy_price_ars"),
                buy_price_usd=d.get("buy_price_usd"),
                sell_price_ars=body.sell_price_ars,
                sell_price_usd=body.sell_price_usd,
            )
            rr_usd = compute_realized_return_argentina_usd_mep(
                buy_price_ars=d.get("buy_price_ars"),
                sell_price_ars=body.sell_price_ars,
                tc_mep_compra=d.get("tc_mep_compra"),
                tc_mep_venta=tc_mep_venta,
            )
        elif at == ASSET_CEDEAR:
            try:
                buy_usd_basis = d.get("buy_price_usd")
                if buy_usd_basis is None or float(buy_usd_basis) <= 0:
                    buy_usd_basis = d.get("buy_price_usa")
                buy_f = float(buy_usd_basis) if buy_usd_basis is not None else None
            except (TypeError, ValueError):
                buy_f = None
            sell_usa_ref = body.sell_price_usd
            rr = compute_realized_return_cedear_usd(
                buy_price_usd=buy_f,
                sell_price_usd=sell_usa_ref,
            )
            rr_usd = rr
        else:
            try:
                bp = float(d["buy_price_usd"]) if d.get("buy_price_usd") is not None else None
                sp = float(body.sell_price_usd) if body.sell_price_usd is not None else None
                if bp is not None and sp is not None and abs(bp) > 1e-12:
                    rr_usd = ((sp / bp) - 1.0) * 100.0
                    rr = rr_usd
            except (TypeError, ValueError):
                rr_usd = None
                rr = None
        ok = close_position_row(
            position_id,
            sell_date=body.sell_date.strip(),
            sell_price_ars=body.sell_price_ars,
            sell_price_usd=body.sell_price_usd,
            sell_notes=body.sell_notes,
            tc_mep_venta=tc_mep_venta,
            sell_price_cedear_usd=body.sell_price_cedear_usd,
            sell_price_usa=body.sell_price_usa,
            sell_gap=body.sell_gap,
            score_at_sell=None,
            signalstate_at_sell=None,
            techscore_at_sell=None,
            fundscore_at_sell=None,
            riskscore_at_sell=None,
            realized_return_pct=rr,
            realized_return_usd_pct=rr_usd,
            holding_days=hold,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="No se pudo cerrar la posición")
        return {"status": "ok"}

    snap = snapshot_fields_for_sell(d["ticker"], d["asset_type"])
    sell_usa_snap = body.sell_price_usa if body.sell_price_usa is not None else snap.get("sell_price_usa")
    sell_gap = body.sell_gap if body.sell_gap is not None else snap.get("sell_gap")

    sell_price_ars_out = body.sell_price_ars
    sell_price_usd_out = body.sell_price_usd
    sell_price_cedear_usd_out = body.sell_price_cedear_usd
    sell_price_usa_out = sell_usa_snap

    tc_mep_venta = body.tc_mep_venta if d["asset_type"] in (ASSET_ARGENTINA, ASSET_CEDEAR) else None

    rr: float | None
    rr_usd: float | None = None
    if d["asset_type"] == ASSET_CEDEAR:
        # Venta: sell_price_usd / retorno = precio USA (subyacente). CCL va solo a sell_price_cedear_usd (aux).
        sell_aux_ccl = snap.get("sell_price_cedear_usd")
        if body.sell_price_cedear_usd is not None:
            sell_aux_ccl = body.sell_price_cedear_usd
        # No usar precio CCL como proxy de USD USA si falta sell_price_usd.
        sell_usa_explicit = body.sell_price_usd
        sell_usa_ref = sell_usa_explicit if sell_usa_explicit is not None else snap.get("sell_price_usa")
        sell_price_ars_out = None
        sell_price_usd_out = sell_usa_ref
        sell_price_cedear_usd_out = sell_aux_ccl
        sell_price_usa_out = body.sell_price_usa if body.sell_price_usa is not None else sell_usa_ref

        buy_usd_basis = d.get("buy_price_usd")
        try:
            if buy_usd_basis is None or float(buy_usd_basis) <= 0:
                buy_usd_basis = d.get("buy_price_usa")
        except (TypeError, ValueError):
            buy_usd_basis = d.get("buy_price_usa")
        # buy_price_cedear_usd es línea CCL (USD por CEDEAR), no USD por acción USA — no usar en retorno USA.
        try:
            buy_f = float(buy_usd_basis) if buy_usd_basis is not None else None
        except (TypeError, ValueError):
            buy_f = None
        rr = compute_realized_return_cedear_usd(
            buy_price_usd=buy_f,
            sell_price_usd=sell_usa_ref,
        )
        rr_usd = rr
    elif d["asset_type"] == ASSET_ARGENTINA:
        rr = compute_realized_return_pct(
            asset_type=d["asset_type"],
            buy_price_ars=d.get("buy_price_ars"),
            buy_price_usd=d.get("buy_price_usd"),
            sell_price_ars=body.sell_price_ars,
            sell_price_usd=body.sell_price_usd,
        )
        rr_usd = compute_realized_return_argentina_usd_mep(
            buy_price_ars=d.get("buy_price_ars"),
            sell_price_ars=body.sell_price_ars,
            tc_mep_compra=d.get("tc_mep_compra"),
            tc_mep_venta=tc_mep_venta,
        )
    else:
        rr = compute_realized_return_pct(
            asset_type=d["asset_type"],
            buy_price_ars=d.get("buy_price_ars"),
            buy_price_usd=d.get("buy_price_usd"),
            sell_price_ars=body.sell_price_ars,
            sell_price_usd=body.sell_price_usd,
        )
    try:
        d0 = date.fromisoformat(str(d["buy_date"])[:10])
        d1 = date.fromisoformat(body.sell_date.strip()[:10])
        hold = (d1 - d0).days
    except ValueError:
        hold = None

    ok = close_position_row(
        position_id,
        sell_date=body.sell_date.strip(),
        sell_price_ars=sell_price_ars_out,
        sell_price_usd=sell_price_usd_out,
        sell_notes=body.sell_notes,
        tc_mep_venta=tc_mep_venta,
        sell_price_cedear_usd=sell_price_cedear_usd_out,
        sell_price_usa=sell_price_usa_out,
        sell_gap=sell_gap,
        score_at_sell=snap.get("score_at_sell"),
        signalstate_at_sell=snap.get("signalstate_at_sell"),
        techscore_at_sell=snap.get("techscore_at_sell"),
        fundscore_at_sell=snap.get("fundscore_at_sell"),
        riskscore_at_sell=snap.get("riskscore_at_sell"),
        realized_return_pct=rr,
        realized_return_usd_pct=rr_usd,
        holding_days=hold,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="No se pudo cerrar la posición")
    return {"status": "ok"}


def _require_non_stock_trade_row(position_id: int) -> dict[str, Any]:
    row = get_position_by_id(position_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Operación no encontrada")
    d = row_as_mapping(row)
    if str(d.get("instrument_type") or "stock").lower() == "stock":
        raise HTTPException(
            status_code=400,
            detail="Este endpoint es para opciones/estrategias; las acciones usan POST /portfolio/positions y PATCH vía flujo estándar.",
        )
    return d


@router.get("/trades")
def list_trades(
    status: Literal["open", "closed"] = Query("open"),
    instrument_type: str = Query(
        "all",
        description="all | stock | option | option_strategy",
    ),
    portfolio_type: str = Query(
        "all",
        description="radar | real | all",
    ),
):
    pt = _query_portfolio_type(portfolio_type)
    rows = list_trades_filtered(
        status=status,
        instrument_type=instrument_type.strip().lower() or "all",
        portfolio_type=pt,
    )
    if status == "open":
        return [_enrich_open_row(r) for r in rows]
    return [_serialize_trade_row(r) for r in rows]


@router.get("/trades/metrics")
def trades_metrics(
    portfolio_type: str = Query(
        "all",
        description="radar | real | all",
    ),
):
    pt = _query_portfolio_type(portfolio_type)
    return portfolio_instrument_metrics(portfolio_type=pt)


@router.post("/trades")
def create_trade(body: TradeCreateBody):
    t = body.ticker.strip().upper()
    tc_mep_c = body.tc_mep_compra if body.asset_type in (ASSET_ARGENTINA, ASSET_CEDEAR) else None
    legs = _normalize_trade_legs_dump(body.legs)
    events = [ev.model_dump() for ev in body.management_events]
    buy_usd = body.buy_price_usd
    if buy_usd is None and body.initial_debit_credit is not None:
        buy_usd = float(body.initial_debit_credit)
    trade_pt: PortfolioKind = body.portfolio_type if body.portfolio_type is not None else "real"
    und = body.underlying_symbol.strip().upper() if body.underlying_symbol and body.underlying_symbol.strip() else None
    pid = insert_trade_position(
        ticker=t,
        asset_type=body.asset_type,
        quantity=body.quantity,
        buy_date=body.buy_date.strip(),
        buy_price_ars=body.buy_price_ars,
        buy_price_usd=buy_usd,
        notes=body.notes,
        instrument_type=body.instrument_type,
        underlying_symbol=und,
        strategy_type=body.strategy_type,
        option_expiration=body.option_expiration,
        initial_debit_credit=body.initial_debit_credit,
        committed_capital=body.committed_capital,
        max_risk=body.max_risk,
        max_profit=body.max_profit,
        opening_underlying_price=body.opening_underlying_price,
        opening_iv=body.opening_iv,
        legs=legs,
        management_events=events,
        tc_mep_compra=tc_mep_c,
        portfolio_type=trade_pt,
    )
    return {"id": pid, "status": "ok"}


@router.patch("/trades/{position_id}")
def patch_trade(position_id: int, body: TradePatchBody):
    ex = _require_non_stock_trade_row(position_id)
    patch: dict[str, Any] = {}
    if body.ticker is not None:
        patch["ticker"] = body.ticker.strip().upper()
    if body.notes is not None:
        patch["notes"] = body.notes
    if body.quantity is not None:
        patch["quantity"] = body.quantity
    if body.underlying_symbol is not None:
        patch["underlying_symbol"] = body.underlying_symbol.strip().upper()
    if body.strategy_type is not None:
        patch["strategy_type"] = body.strategy_type
    if body.option_expiration is not None:
        patch["option_expiration"] = body.option_expiration
    if body.initial_debit_credit is not None:
        patch["initial_debit_credit"] = body.initial_debit_credit
    if body.committed_capital is not None:
        patch["committed_capital"] = body.committed_capital
    if body.max_risk is not None:
        patch["max_risk"] = body.max_risk
    if body.max_profit is not None:
        patch["max_profit"] = body.max_profit
    if body.opening_underlying_price is not None:
        patch["opening_underlying_price"] = body.opening_underlying_price
    if body.opening_iv is not None:
        patch["opening_iv"] = body.opening_iv
    if body.instrument_type is not None:
        patch["instrument_type"] = body.instrument_type
    if body.portfolio_type is not None:
        patch["portfolio_type"] = body.portfolio_type
    if body.legs is not None:
        patch["legs_json"] = _normalize_trade_legs_dump(body.legs)
    if body.management_events is not None:
        patch["management_events_json"] = [x.model_dump() for x in body.management_events]
    if not patch:
        row = get_position_by_id(position_id)
        assert row is not None
        return _serialize_trade_row(row)

    merged_it = str((patch.get("instrument_type") if "instrument_type" in patch else ex.get("instrument_type")) or "option").lower()
    merged_und = ex.get("underlying_symbol")
    if body.underlying_symbol is not None:
        merged_und = body.underlying_symbol.strip().upper() or None
    merged_strat = body.strategy_type if body.strategy_type is not None else ex.get("strategy_type")
    if body.legs is not None:
        legs_merged: list[dict[str, Any]] = patch["legs_json"]
    else:
        raw_l = ex.get("legs_json")
        try:
            legs_merged = json.loads(raw_l) if raw_l else []
        except (json.JSONDecodeError, TypeError):
            legs_merged = []
        if not isinstance(legs_merged, list):
            legs_merged = []
        legs_merged = [normalize_leg_multiplier(leg) if isinstance(leg, dict) else leg for leg in legs_merged]

    allow_empty = bool(body.allow_empty_legs) if body.allow_empty_legs is not None else False
    validation_touch = (
        body.legs is not None
        or body.instrument_type is not None
        or body.strategy_type is not None
        or body.underlying_symbol is not None
        or body.allow_empty_legs is not None
    )
    if validation_touch and merged_it == "option_strategy":
        _validate_option_strategy_merged(
            instrument_type=merged_it,
            underlying_symbol=str(merged_und) if merged_und else None,
            strategy_type=str(merged_strat) if merged_strat is not None else None,
            legs=legs_merged,
            allow_empty_legs=allow_empty,
        )

    ok = update_trade_position_fields(position_id, patch)
    if not ok:
        raise HTTPException(status_code=400, detail="Nada para actualizar o posición no encontrada")
    row2 = get_position_by_id(position_id)
    assert row2 is not None
    return _serialize_trade_row(row2)


@router.post("/trades/{position_id}/events")
def append_trade_event(position_id: int, body: TradeEventAppendBody):
    _require_non_stock_trade_row(position_id)
    _validate_append_event_debit(body)
    ev = body.model_dump()
    ok = append_management_event(position_id, ev)
    if not ok:
        raise HTTPException(status_code=404, detail="No se pudo agregar el evento")
    row = get_position_by_id(position_id)
    assert row is not None
    return _serialize_trade_row(row)


@router.post("/trades/{position_id}/close")
def close_trade(position_id: int, body: PositionCloseBody):
    """Alias de POST /portfolio/positions/{id}/close (misma lógica de cierre)."""
    return close_position_endpoint(position_id, body)
