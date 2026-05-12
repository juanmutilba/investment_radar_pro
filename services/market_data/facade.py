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
# tercer componente: símbolo Yahoo .BA opcional (cadena vacía = comportamiento clásico).
_resolved_argentina: dict[tuple[str, bool, str], PriceQuote] = {}


def _argentina_cache_key(ticker: str, prefer_export: bool, options_spot_yahoo_symbol: str | None) -> tuple[str, bool, str]:
    t = (ticker or "").strip().upper()
    y = (options_spot_yahoo_symbol or "").strip().upper()
    return (t, prefer_export, y)


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


def get_argentina_price(
    ticker: str,
    prefer_export: bool = True,
    *,
    options_spot_yahoo_symbol: str | None = None,
) -> PriceQuote:
    """
    Precio ARS para ticker BYMA (sin .BA). Si ``options_spot_yahoo_symbol`` (ej. GGAL.BA) está
    definido, intenta primero Yahoo con ese símbolo; si no hay precio válido, sigue export → IOL → Yahoo(ticker).
    """
    t = (ticker or "").strip().upper()
    y_first = (options_spot_yahoo_symbol or "").strip().upper()
    key = _argentina_cache_key(ticker, prefer_export, y_first or None)
    if t:
        hit = _resolved_argentina.get(key)
        if hit is not None:
            return hit

    if y_first:
        try:
            yq = yahoo_last_price(y_first, "ARS")
        except Exception:
            yq = PriceQuote(
                value=None,
                currency="ARS",
                source="yahoo",
                as_of=None,
                symbol_used=y_first,
                notes=None,
            )
        if yq.is_valid:
            if t:
                _resolved_argentina[key] = yq
            return yq

    if prefer_export:
        q = get_export_argentina_price(ticker)
        if q.is_valid:
            if t:
                _resolved_argentina[key] = q
            return q

    # Provider opcional: IOL (si hay credenciales en memoria).
    if is_iol_enabled():
        try:
            iq = get_iol_quote(ticker)
            if iq is not None and iq.is_valid:
                if t:
                    _resolved_argentina[key] = iq
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
        _resolved_argentina[key] = out
    return out
