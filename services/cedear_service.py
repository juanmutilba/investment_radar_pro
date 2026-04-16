from __future__ import annotations

import math
from typing import Any

import yfinance as yf
from pydantic import BaseModel, ConfigDict, Field

from data.cedear_mapping import CEDEAR_MAPPINGS
from services import latest_export


class CedearRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ticker_usa: str
    ticker_cedear_ars: str
    ticker_cedear_usd: str
    ratio: float = Field(..., description="ratio_cedear_a_accion del mapping")
    precio_cedear_ars: float | None
    precio_cedear_usd: float | None
    ccl_implicito: float | None = Field(None, description="precio_cedear_ars / precio_cedear_usd")
    precio_usa_real: float | None
    precio_implicito_usd: float | None = Field(None, description="precio_cedear_usd / ratio")
    gap_pct: float | None = Field(
        None,
        description="(precio_implicito_usd / precio_usa_real - 1) * 100",
    )
    total_score: float | None = Field(None, serialization_alias="TotalScore")
    signal_state: str | None = Field(None, serialization_alias="SignalState")


def _radar_get(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k not in row:
            continue
        v = row[k]
        if v is None:
            continue
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            continue
        return v
    return None


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


def _fetch_last_price(symbol: str) -> float | None:
    """
    Ultimo precio operable via Yahoo (fast_info o ultimo cierre corto).
    No recalcula tecnica ni fundamentales; solo spot para CEDEAR.
    """
    sym = (symbol or "").strip()
    if not sym:
        return None
    try:
        asset = yf.Ticker(sym)
        fi = getattr(asset, "fast_info", None)
        raw: Any = None
        if isinstance(fi, dict):
            raw = fi.get("last_price") or fi.get("lastPrice") or fi.get("regularMarketPrice")
        if raw is None and fi is not None:
            try:
                raw = fi["last_price"]  # type: ignore[index]
            except Exception:
                raw = None
        p = _to_float(raw)
        if p is not None and p > 0:
            return round(p, 6)

        hist = asset.history(period="5d", auto_adjust=False, actions=False, repair=False)
        if hist is not None and not hist.empty and "Close" in hist.columns:
            close = _to_float(hist["Close"].iloc[-1])
            if close is not None and close > 0:
                return round(close, 6)
    except Exception:
        return None
    return None


def _usa_row_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        raw = _radar_get(r, "Ticker", "ticker")
        if raw is None:
            continue
        key = str(raw).strip().upper()
        if key:
            out[key] = r
    return out


def build_cedear_rows_from_latest_radar() -> list[CedearRow] | None:
    """
    None si no hay export radar_*.xlsx.
    Solo incluye mapeos cuyo ticker_usa aparece en Radar_Completo del último export.
    """
    payload = latest_export.read_latest_radar()
    if payload is None:
        return None
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        return []

    by_ticker = _usa_row_index(raw_rows)
    out: list[CedearRow] = []

    for m in CEDEAR_MAPPINGS:
        if not m.activo:
            continue
        usa_key = m.ticker_usa.strip().upper()
        row = by_ticker.get(usa_key)
        if row is None:
            continue

        precio_usa = _to_float(_radar_get(row, "Precio", "precio"))
        total_score = _to_float(_radar_get(row, "TotalScore", "total_score"))
        sig = _radar_get(row, "SignalState", "signal_state")
        signal_state = str(sig).strip() if sig is not None else None

        p_ars = _fetch_last_price(m.ticker_cedear_ars)
        p_usd = _fetch_last_price(m.ticker_cedear_usd)

        ratio = float(m.ratio_cedear_a_accion)
        ccl: float | None = None
        if p_ars is not None and p_usd is not None and p_usd > 0:
            ccl = round(p_ars / p_usd, 6)

        precio_impl: float | None = None
        if p_usd is not None and ratio > 0:
            precio_impl = round(p_usd / ratio, 6)

        gap: float | None = None
        if precio_impl is not None and precio_usa is not None and precio_usa > 0:
            gap = round((precio_impl / precio_usa - 1.0) * 100.0, 4)

        out.append(
            CedearRow(
                ticker_usa=m.ticker_usa.strip().upper(),
                ticker_cedear_ars=m.ticker_cedear_ars.strip(),
                ticker_cedear_usd=m.ticker_cedear_usd.strip(),
                ratio=ratio,
                precio_cedear_ars=p_ars,
                precio_cedear_usd=p_usd,
                ccl_implicito=ccl,
                precio_usa_real=precio_usa,
                precio_implicito_usd=precio_impl,
                gap_pct=gap,
                total_score=total_score,
                signal_state=signal_state,
            )
        )

    return out
