from __future__ import annotations

from services.market_data.providers.export_prices import (
    get_export_argentina_price,
    get_export_usa_price,
)
from services.market_data.providers.iol import get_iol_quote, is_iol_enabled
from services.market_data.providers.yahoo_spot import yahoo_last_price
from services.market_data.types import PriceQuote

# Resultado ya resuelto (export y/o Yahoo) por ticker y preferencia de export.
_resolved_usa: dict[tuple[str, bool], PriceQuote] = {}
_resolved_argentina: dict[tuple[str, bool], PriceQuote] = {}


def get_usa_price(ticker: str, prefer_export: bool = True) -> PriceQuote:
    t = (ticker or "").strip().upper()
    if t:
        key = (t, prefer_export)
        hit = _resolved_usa.get(key)
        if hit is not None:
            return hit
    if prefer_export:
        q = get_export_usa_price(ticker)
        if q.is_valid:
            if t:
                _resolved_usa[(t, prefer_export)] = q
            return q
    try:
        out = yahoo_last_price(ticker, "USD")
    except Exception:
        out = PriceQuote(
            value=None,
            currency="USD",
            source="yahoo",
            as_of=None,
            symbol_used=t,
            notes=None,
        )
    if t:
        _resolved_usa[(t, prefer_export)] = out
    return out


def get_argentina_price(ticker: str, prefer_export: bool = True) -> PriceQuote:
    t = (ticker or "").strip().upper()
    if t:
        key = (t, prefer_export)
        hit = _resolved_argentina.get(key)
        if hit is not None:
            return hit
    if prefer_export:
        q = get_export_argentina_price(ticker)
        if q.is_valid:
            if t:
                _resolved_argentina[(t, prefer_export)] = q
            return q

    # Provider opcional: IOL (si hay credenciales en memoria).
    if is_iol_enabled():
        try:
            iq = get_iol_quote(ticker)
            if iq is not None and iq.is_valid:
                if t:
                    _resolved_argentina[(t, prefer_export)] = iq
                return iq
        except Exception:
            pass
    try:
        out = yahoo_last_price(ticker, "ARS")
    except Exception:
        out = PriceQuote(
            value=None,
            currency="ARS",
            source="yahoo",
            as_of=None,
            symbol_used=t,
            notes=None,
        )
    if t:
        _resolved_argentina[(t, prefer_export)] = out
    return out
