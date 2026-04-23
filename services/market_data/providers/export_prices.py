from __future__ import annotations

from datetime import datetime, timezone

from services import latest_export
from services.market_data.types import PriceQuote
from services.portfolio_snapshots import ASSET_ARGENTINA, ASSET_USA, current_market_snapshot

# Misma corrida / proceso: evita releer snapshot-export por ticker repetido.
_export_usa_by_ticker: dict[str, PriceQuote] = {}
_export_arg_by_ticker: dict[str, PriceQuote] = {}


def _export_as_of() -> datetime | None:
    path = latest_export.resolve_latest_export_path()
    if path is None:
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _quote_export_usd(ticker: str, value: float | None) -> PriceQuote:
    t = (ticker or "").strip().upper()
    if value is None:
        return PriceQuote(
            value=None,
            currency="USD",
            source="export",
            as_of=None,
            symbol_used=t,
            notes=None,
        )
    return PriceQuote(
        value=float(value),
        currency="USD",
        source="export",
        as_of=_export_as_of(),
        symbol_used=t,
        notes=None,
    )


def _quote_export_ars(ticker: str, value: float | None) -> PriceQuote:
    t = (ticker or "").strip().upper()
    if value is None:
        return PriceQuote(
            value=None,
            currency="ARS",
            source="export",
            as_of=None,
            symbol_used=t,
            notes=None,
        )
    return PriceQuote(
        value=float(value),
        currency="ARS",
        source="export",
        as_of=_export_as_of(),
        symbol_used=t,
        notes=None,
    )


def get_export_usa_price(ticker: str) -> PriceQuote:
    t = (ticker or "").strip().upper()
    if not t:
        return PriceQuote(
            value=None,
            currency="USD",
            source="export",
            as_of=None,
            symbol_used=t,
            notes=None,
        )
    hit = _export_usa_by_ticker.get(t)
    if hit is not None:
        return hit
    try:
        snap = current_market_snapshot(t, ASSET_USA)
        val = snap.get("current_price_usd")
        q = _quote_export_usd(t, None if val is None else float(val))
    except Exception:
        q = PriceQuote(
            value=None,
            currency="USD",
            source="export",
            as_of=None,
            symbol_used=t,
            notes=None,
        )
    _export_usa_by_ticker[t] = q
    return q


def get_export_argentina_price(ticker: str) -> PriceQuote:
    t = (ticker or "").strip().upper()
    if not t:
        return PriceQuote(
            value=None,
            currency="ARS",
            source="export",
            as_of=None,
            symbol_used=t,
            notes=None,
        )
    hit = _export_arg_by_ticker.get(t)
    if hit is not None:
        return hit
    try:
        snap = current_market_snapshot(t, ASSET_ARGENTINA)
        val = snap.get("current_price_ars")
        q = _quote_export_ars(t, None if val is None else float(val))
    except Exception:
        q = PriceQuote(
            value=None,
            currency="ARS",
            source="export",
            as_of=None,
            symbol_used=t,
            notes=None,
        )
    _export_arg_by_ticker[t] = q
    return q
