from __future__ import annotations

import math
from typing import Any

from services import latest_export
from services.cedear_scan_cache import try_load_cedear_snapshot_rows
from services.cedear_service import CedearRow, build_cedear_rows_from_latest_radar

ASSET_USA = "USA"
ASSET_ARGENTINA = "Argentina"
ASSET_CEDEAR = "CEDEAR"


def _norm_ticker(t: str) -> str:
    return (t or "").strip().upper()


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _row_get(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _load_usa_rows() -> list[dict[str, Any]]:
    payload = latest_export.read_latest_radar()
    if not payload:
        return []
    rows = payload.get("rows")
    return rows if isinstance(rows, list) else []


def _load_arg_rows() -> list[dict[str, Any]]:
    payload = latest_export.read_latest_radar_argentina()
    if not payload:
        return []
    rows = payload.get("rows")
    return rows if isinstance(rows, list) else []


def find_radar_row(ticker: str, asset_type: str) -> dict[str, Any] | None:
    t = _norm_ticker(ticker)
    if asset_type == ASSET_USA:
        rows = _load_usa_rows()
    elif asset_type == ASSET_ARGENTINA:
        rows = _load_arg_rows()
    else:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        rt = _row_get(row, "Ticker", "ticker")
        if rt is None:
            continue
        if _norm_ticker(str(rt)) == t:
            return row
    return None


def scores_from_radar_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "score_at_buy": None,
            "signalstate_at_buy": None,
            "techscore_at_buy": None,
            "fundscore_at_buy": None,
            "riskscore_at_buy": None,
        }
    return {
        "score_at_buy": _to_float(_row_get(row, "TotalScore", "total_score")),
        "signalstate_at_buy": _to_str(_row_get(row, "SignalState", "signal_state", "signalState")),
        "techscore_at_buy": _to_float(_row_get(row, "TechScore", "tech_score")),
        "fundscore_at_buy": _to_float(_row_get(row, "FundScore", "fund_score")),
        "riskscore_at_buy": _to_float(_row_get(row, "RiskScore", "risk_score")),
    }


def _load_cedear_rows() -> list[CedearRow]:
    snap = try_load_cedear_snapshot_rows()
    if snap is not None:
        return snap
    built = build_cedear_rows_from_latest_radar()
    return built if built else []


def find_cedear_row(ticker: str) -> CedearRow | None:
    t = _norm_ticker(ticker)
    for c in _load_cedear_rows():
        if _norm_ticker(c.ticker_usa) == t:
            return c
        if _norm_ticker(c.ticker_cedear_ars) == t:
            return c
        if _norm_ticker(c.ticker_cedear_usd) == t:
            return c
    return None


def snapshot_fields_for_buy(ticker: str, asset_type: str) -> dict[str, Any]:
    """
    Campos persistidos al comprar: scores desde último radar + pricing CEDEAR si aplica.
    Best-effort si no hay export o ticker no está en el universo.
    """
    out: dict[str, Any] = {
        "buy_price_cedear_usd": None,
        "buy_price_usa": None,
        "buy_gap": None,
        "score_at_buy": None,
        "signalstate_at_buy": None,
        "techscore_at_buy": None,
        "fundscore_at_buy": None,
        "riskscore_at_buy": None,
    }
    if asset_type == ASSET_CEDEAR:
        c = find_cedear_row(ticker)
        if c:
            out["buy_price_cedear_usd"] = c.precio_cedear_usd
            out["buy_price_usa"] = c.precio_usa_real
            out["buy_gap"] = c.gap_pct
            out["score_at_buy"] = c.total_score
            out["signalstate_at_buy"] = c.signal_state
            usa_row = find_radar_row(c.ticker_usa, ASSET_USA)
            sub = scores_from_radar_row(usa_row)
            out["techscore_at_buy"] = sub["techscore_at_buy"]
            out["fundscore_at_buy"] = sub["fundscore_at_buy"]
            out["riskscore_at_buy"] = sub["riskscore_at_buy"]
        return out

    row = find_radar_row(ticker, asset_type)
    sub = scores_from_radar_row(row)
    out.update(sub)
    return out


def snapshot_fields_for_sell(ticker: str, asset_type: str) -> dict[str, Any]:
    """Snapshot al vender (misma lógica que compra, nombres de columnas sell_* en el caller)."""
    shaped = snapshot_fields_for_buy(ticker, asset_type)
    return {
        "score_at_sell": shaped.get("score_at_buy"),
        "signalstate_at_sell": shaped.get("signalstate_at_buy"),
        "techscore_at_sell": shaped.get("techscore_at_buy"),
        "fundscore_at_sell": shaped.get("fundscore_at_buy"),
        "riskscore_at_sell": shaped.get("riskscore_at_buy"),
        "sell_price_cedear_usd": shaped.get("buy_price_cedear_usd") if asset_type == ASSET_CEDEAR else None,
        "sell_price_usa": shaped.get("buy_price_usa") if asset_type == ASSET_CEDEAR else None,
        "sell_gap": shaped.get("buy_gap") if asset_type == ASSET_CEDEAR else None,
    }


def current_market_snapshot(ticker: str, asset_type: str) -> dict[str, Any]:
    """Precios y scores actuales desde último scan (para cartera abierta)."""
    out: dict[str, Any] = {
        "current_score": None,
        "current_signalstate": None,
        "current_price_ars": None,
        "current_price_usd": None,
    }
    if asset_type == ASSET_CEDEAR:
        c = find_cedear_row(ticker)
        if c:
            out["current_score"] = c.total_score
            out["current_signalstate"] = c.signal_state
            out["current_price_ars"] = c.precio_cedear_ars
            out["current_price_usd"] = c.precio_cedear_usd
        return out

    row = find_radar_row(ticker, asset_type)
    if not row:
        return out
    s = scores_from_radar_row(row)
    out["current_score"] = s["score_at_buy"]
    out["current_signalstate"] = s["signalstate_at_buy"]
    p = _to_float(_row_get(row, "Precio", "precio"))
    if asset_type == ASSET_USA:
        out["current_price_usd"] = p
    else:
        out["current_price_ars"] = p
        out["current_price_usd"] = _to_float(_row_get(row, "PrecioUSD", "precio_usd", "Precio_USD"))
    return out


def compute_return_pct_open(
    *,
    asset_type: str,
    buy_price_ars: float | None,
    buy_price_usd: float | None,
    cur_ars: float | None,
    cur_usd: float | None,
) -> float | None:
    if asset_type == ASSET_USA or (buy_price_usd is not None and buy_price_usd > 0 and cur_usd is not None):
        if buy_price_usd is not None and buy_price_usd > 0 and cur_usd is not None:
            return round((cur_usd - buy_price_usd) / buy_price_usd * 100.0, 4)
    if buy_price_ars is not None and buy_price_ars > 0 and cur_ars is not None:
        return round((cur_ars - buy_price_ars) / buy_price_ars * 100.0, 4)
    if buy_price_usd is not None and buy_price_usd > 0 and cur_usd is not None:
        return round((cur_usd - buy_price_usd) / buy_price_usd * 100.0, 4)
    return None


def compute_realized_return_pct(
    *,
    asset_type: str,
    buy_price_ars: float | None,
    buy_price_usd: float | None,
    sell_price_ars: float | None,
    sell_price_usd: float | None,
) -> float | None:
    if buy_price_usd is not None and buy_price_usd > 0 and sell_price_usd is not None:
        return round((sell_price_usd - buy_price_usd) / buy_price_usd * 100.0, 4)
    if buy_price_ars is not None and buy_price_ars > 0 and sell_price_ars is not None:
        return round((sell_price_ars - buy_price_ars) / buy_price_ars * 100.0, 4)
    if buy_price_usd is not None and buy_price_usd > 0 and sell_price_usd is not None:
        return round((sell_price_usd - buy_price_usd) / buy_price_usd * 100.0, 4)
    return None
