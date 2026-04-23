from __future__ import annotations

from typing import Literal

import yfinance as yf

from services.market_data.types import PriceQuote
from services.yfinance_helpers import precio_valido

# (símbolo normalizado, moneda) → cota Yahoo ya resuelta en esta corrida.
_yahoo_by_symbol_currency: dict[tuple[str, Literal["ARS", "USD"]], PriceQuote] = {}


def _normalize_currency(currency: str) -> Literal["ARS", "USD"]:
    c = (currency or "USD").strip().upper()
    if c == "ARS":
        return "ARS"
    return "USD"


def yahoo_last_price(symbol: str, currency: str = "USD") -> PriceQuote:
    cur = _normalize_currency(currency)
    sym_u = (symbol or "").strip().upper()
    if not sym_u:
        sym_raw = (symbol or "").strip()
        return PriceQuote(
            value=None,
            currency=cur,
            source="yahoo",
            as_of=None,
            symbol_used=sym_raw,
            notes=None,
        )

    cache_key = (sym_u, cur)
    hit = _yahoo_by_symbol_currency.get(cache_key)
    if hit is not None:
        return hit

    price: float | None = None
    try:
        t = yf.Ticker(sym_u)
        fi = getattr(t, "fast_info", None)
        raw: object | None = None
        if isinstance(fi, dict):
            raw = fi.get("last_price") or fi.get("lastPrice") or fi.get("regularMarketPrice")
        if raw is None and fi is not None:
            try:
                raw = fi["last_price"]  # type: ignore[index]
            except Exception:
                raw = None
        if raw is not None:
            try:
                price = float(raw)
            except (TypeError, ValueError):
                price = None
        if not precio_valido(price):
            price = None
            hist = t.history(period="5d")
            if hist is not None and not hist.empty and "Close" in hist.columns:
                last = hist["Close"].iloc[-1]
                try:
                    price = float(last)
                except (TypeError, ValueError):
                    price = None
    except Exception:
        price = None

    if not precio_valido(price):
        q = PriceQuote(
            value=None,
            currency=cur,
            source="yahoo",
            as_of=None,
            symbol_used=sym_u,
            notes=None,
        )
        _yahoo_by_symbol_currency[cache_key] = q
        return q

    q = PriceQuote(
        value=round(float(price), 6),
        currency=cur,
        source="yahoo",
        as_of=None,
        symbol_used=sym_u,
        notes=None,
    )
    _yahoo_by_symbol_currency[cache_key] = q
    return q
