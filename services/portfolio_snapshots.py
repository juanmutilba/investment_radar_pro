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


def _cedear_usa_reference_price(c: CedearRow) -> float | None:
    """
    USD por acción USA (subyacente): siempre vía market_data; fallback a la fila CEDEAR si falla.
    Import diferido: market_data → portfolio_snapshots en cadena de imports.
    """
    try:
        from services.market_data import get_usa_price

        q = get_usa_price(c.ticker_usa, prefer_export=True)
        if q.is_valid and q.value is not None:
            return float(q.value)
    except Exception:
        pass
    return c.precio_usa_real


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
            out["buy_price_usa"] = _cedear_usa_reference_price(c)
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
            # Base principal USA: market_data (export + Yahoo), no solo fila snapshot/CCL.
            out["current_price_usd"] = _cedear_usa_reference_price(c)
            # Auxiliar: mercado local (no usar como base de retorno vs compra USA).
            out["current_price_ars"] = c.precio_cedear_ars
            out["current_price_cedear_usd"] = c.precio_cedear_usd
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


def autocomplete_tickers(*, asset_type: str, q: str, limit: int = 30) -> list[str]:
    """
    Autocomplete best-effort usando el último export/snapshot disponible.
    No consulta Yahoo ni DB; solo lee el export radar y/o snapshot CEDEAR.
    """
    query = _norm_ticker(q)
    if not query:
        return []
    lim = max(1, min(int(limit or 30), 200))

    candidates: list[str] = []

    if asset_type == ASSET_USA:
        for row in _load_usa_rows():
            if not isinstance(row, dict):
                continue
            t = _row_get(row, "Ticker", "ticker")
            if t is None:
                continue
            candidates.append(_norm_ticker(str(t)))
    elif asset_type == ASSET_ARGENTINA:
        for row in _load_arg_rows():
            if not isinstance(row, dict):
                continue
            t = _row_get(row, "Ticker", "ticker")
            if t is None:
                continue
            candidates.append(_norm_ticker(str(t)))
    elif asset_type == ASSET_CEDEAR:
        for c in _load_cedear_rows():
            candidates.append(_norm_ticker(c.ticker_usa))
            candidates.append(_norm_ticker(c.ticker_cedear_ars))
            candidates.append(_norm_ticker(c.ticker_cedear_usd))
    else:
        return []

    seen: set[str] = set()
    uniq: list[str] = []
    for t in candidates:
        if not t or t in seen:
            continue
        seen.add(t)
        uniq.append(t)

    # Primero: prefix match; luego: contains match (por si pegan parte).
    prefix = [t for t in uniq if t.startswith(query)]
    if len(prefix) >= lim:
        return sorted(prefix)[:lim]

    contains = [t for t in uniq if query in t and not t.startswith(query)]
    out = sorted(prefix) + sorted(contains)
    return out[:lim]


def compute_return_pct_open(
    *,
    asset_type: str,
    buy_price_ars: float | None,
    buy_price_usd: float | None,
    cur_ars: float | None,
    cur_usd: float | None,
) -> float | None:
    # CEDEAR: siempre comparación en USD (no mezclar con ARS / CCL local).
    if asset_type == ASSET_CEDEAR:
        if buy_price_usd is not None and buy_price_usd > 0 and cur_usd is not None:
            return round((cur_usd - buy_price_usd) / buy_price_usd * 100.0, 4)
        return None
    if asset_type == ASSET_USA or (buy_price_usd is not None and buy_price_usd > 0 and cur_usd is not None):
        if buy_price_usd is not None and buy_price_usd > 0 and cur_usd is not None:
            return round((cur_usd - buy_price_usd) / buy_price_usd * 100.0, 4)
    if buy_price_ars is not None and buy_price_ars > 0 and cur_ars is not None:
        return round((cur_ars - buy_price_ars) / buy_price_ars * 100.0, 4)
    if buy_price_usd is not None and buy_price_usd > 0 and cur_usd is not None:
        return round((cur_usd - buy_price_usd) / buy_price_usd * 100.0, 4)
    return None


def compute_realized_return_cedear_usd(
    *,
    buy_price_usd: float | None,
    sell_price_usd: float | None,
) -> float | None:
    """Retorno realizado CEDEAR: precio venta USA vs costo USA (misma base ref USA)."""
    if buy_price_usd is None or sell_price_usd is None:
        return None
    if buy_price_usd <= 0:
        return None
    return round((sell_price_usd - buy_price_usd) / buy_price_usd * 100.0, 4)


def compute_realized_return_argentina_usd_mep(
    *,
    buy_price_ars: float | None,
    sell_price_ars: float | None,
    tc_mep_compra: float | None,
    tc_mep_venta: float | None,
) -> float | None:
    """
    retorno_usd_pct = (((precio_venta_ars / tc_mep_venta) / (precio_compra_ars / tc_mep_compra)) - 1) * 100
    """
    if buy_price_ars is None or sell_price_ars is None:
        return None
    if tc_mep_compra is None or tc_mep_venta is None:
        return None
    if buy_price_ars <= 0 or tc_mep_compra <= 0 or tc_mep_venta <= 0:
        return None
    buy_usd = buy_price_ars / tc_mep_compra
    sell_usd = sell_price_ars / tc_mep_venta
    if buy_usd <= 0:
        return None
    return round((sell_usd / buy_usd - 1.0) * 100.0, 4)


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
