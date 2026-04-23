from __future__ import annotations

from datetime import date
from typing import Any, Literal

import sqlite3
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from persistence.sqlite.positions_repo import (
    close_position_row,
    get_position_by_id,
    insert_open_position,
    list_positions_by_status,
    row_as_mapping,
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

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

AssetType = Literal["USA", "Argentina", "CEDEAR"]


class PositionCreateBody(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    asset_type: AssetType
    quantity: float = Field(gt=0)
    buy_date: str = Field(min_length=8, max_length=32)
    buy_price_ars: float | None = None
    buy_price_usd: float | None = None
    """TC MEP (ARS por USD) al momento de la compra; Argentina y CEDEAR."""
    tc_mep_compra: float | None = None
    notes: str | None = Field(default=None, max_length=4000)


class PositionCloseBody(BaseModel):
    sell_date: str = Field(min_length=8, max_length=32)
    sell_price_ars: float | None = None
    sell_price_usd: float | None = None
    sell_notes: str | None = Field(default=None, max_length=4000)
    """TC MEP al momento de la venta; Argentina y CEDEAR."""
    tc_mep_venta: float | None = None
    sell_price_cedear_usd: float | None = None
    sell_price_usa: float | None = None
    sell_gap: float | None = None


def _enrich_open_row(row: sqlite3.Row) -> dict[str, Any]:
    d = row_as_mapping(row)
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
    return d


def _history_row(row: sqlite3.Row) -> dict[str, Any]:
    d = row_as_mapping(row)
    return {
        "id": d["id"],
        "ticker": d["ticker"],
        "asset_type": d["asset_type"],
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
    }


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
    )
    return {"id": pid, "status": "ok"}


@router.get("/positions/open")
def list_open_positions():
    rows = list_positions_by_status("open")
    return [_enrich_open_row(r) for r in rows]


@router.get("/positions/history")
def list_history():
    rows = list_positions_by_status("closed")
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
