"""
Cotización individual IOL por especie (GET …/Titulos/{symbol}/Cotizacion) para bid/ask reales.

Caché RAM por símbolo (TTL corto). No sustituye la cadena de opciones ni el merge Allaria/Rava.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import requests

from services.market_data.providers.iol import IOL_COTIZACION_URL, get_iol_token, is_iol_enabled
from services.options.providers.iol import (
    _bid_ask_from_row,
    _flatten_row,
    _parse_float,
    _pick_first,
)


def _log(msg: str) -> None:
    print(f"[OPTIONS_IOL_ENRICH] {msg}", flush=True)


OPTIONS_IOL_QUOTE_CACHE_TTL_SECONDS = float(os.environ.get("OPTIONS_IOL_QUOTE_CACHE_TTL_SECONDS", "10") or "10")

_CACHE_LOCK = threading.Lock()


def _options_quote_verbose_debug_enabled() -> bool:
    return (os.environ.get("OPTIONS_IOL_QUOTE_VERBOSE", "") or "").strip() == "1"


def _log_options_quote_debug(
    sym: str,
    *,
    status_label: str,
    http_status: int,
    data: dict[str, Any] | None,
    q: IolOptionQuote,
) -> None:
    """Diagnóstico /options/quotes: solo con OPTIONS_IOL_QUOTE_VERBOSE=1."""
    if not _options_quote_verbose_debug_enabled():
        return
    keys_top: list[str] = []
    keys_sub: list[str] = []
    bid_raw: Any = None
    ask_raw: Any = None
    ultimo_raw: Any = None
    vol_raw: Any = None
    ops_raw: Any = None
    source_s: Any = None
    as_of_s: Any = None
    if isinstance(data, dict) and data:
        keys_top = sorted(str(k) for k in data.keys())[:35]
        for nest in ("cotizacion", "Cotizacion"):
            sub = data.get(nest)
            if isinstance(sub, dict):
                keys_sub = sorted(str(k) for k in sub.keys())[:35]
                break
        row = _row_from_cotizacion_payload(data)
        flat = _flatten_row(row)
        keys_bid = (
            "precioCompra",
            "PrecioCompra",
            "precioCompraD",
            "bid",
            "Bid",
            "pCompra",
            "precioCompraDinamico",
            "PrecioCompraDinamico",
        )
        keys_ask = (
            "precioVenta",
            "PrecioVenta",
            "precioVentaD",
            "ask",
            "Ask",
            "pVenta",
            "precioVentaDinamico",
            "PrecioVentaDinamico",
        )
        bid_raw = _pick_first(flat, keys_bid)
        ask_raw = _pick_first(flat, keys_ask)
        ultimo_raw = _pick_first(
            flat,
            ("ultimoPrecio", "UltimoPrecio", "ultimo", "Ultimo", "last", "Last", "cierre", "Cierre"),
        )
        vol_raw = _pick_first(
            flat,
            ("volumenNominal", "VolumenNominal", "volumen", "Volumen", "volume", "Volume"),
        )
        ops_raw = _pick_first(
            flat,
            ("cantidadOperaciones", "CantidadOperaciones", "operaciones", "Operaciones"),
        )
        source_s = _pick_first(flat, ("source", "Source", "fuente", "Fuente", "mercado", "Mercado"))
        as_of_s = _pick_first(flat, ("as_of", "AsOf", "fechaHora", "FechaHora", "fecha", "Fecha"))

    print(
        "[OPTIONS_QUOTE_DEBUG] "
        f"symbol={sym!r} status={status_label!r} http_status={http_status} "
        f"keys_top={keys_top!r} keys_cotizacion={keys_sub!r} "
        f"bid_raw={bid_raw!r} ask_raw={ask_raw!r} bid_parsed={q.bid!r} ask_parsed={q.ask!r} "
        f"ultimoPrecio={ultimo_raw!r} volumen={vol_raw!r} operaciones={ops_raw!r} "
        f"source={source_s!r} as_of={as_of_s!r} error={q.error!r} "
        f"parsed_volume={q.volume!r} parsed_ops={q.cantidad_operaciones!r}",
        flush=True,
    )


@dataclass
class IolOptionQuote:
    symbol: str
    bid: float | None
    ask: float | None
    puntas: Any
    volume: float | None
    cantidad_operaciones: float | None
    fecha_hora: str | None
    error: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "bid": self.bid,
            "ask": self.ask,
            "puntas": self.puntas,
            "volume": self.volume,
            "cantidad_operaciones": self.cantidad_operaciones,
            "fecha_hora": self.fecha_hora,
        }
        if self.error:
            d["error"] = self.error
        return d


_CACHE: dict[str, tuple[float, IolOptionQuote | None]] = {}


def _normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace(" ", "")


def _row_from_cotizacion_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Normaliza respuesta IOL a la forma que esperan ``_flatten_row`` / ``_bid_ask_from_row``."""
    if "cotizacion" in data or "Cotizacion" in data:
        return dict(data)
    return {"cotizacion": dict(data)}


def _parse_cotizacion_json(symbol: str, data: dict[str, Any]) -> IolOptionQuote:
    row = _row_from_cotizacion_payload(data)
    flat = _flatten_row(row)
    bid, ask, _plen = _bid_ask_from_row(row, flat)

    puntas_out: Any = None
    for nest in ("cotizacion", "Cotizacion"):
        sub = row.get(nest)
        if isinstance(sub, dict) and "puntas" in sub:
            puntas_out = sub.get("puntas")
            break
    if puntas_out is None and "puntas" in data:
        puntas_out = data.get("puntas")

    vol = _parse_float(
        _pick_first(
            flat,
            (
                "volumenNominal",
                "VolumenNominal",
                "volumen",
                "Volumen",
                "volume",
                "Volume",
            ),
        ),
    )
    ops = _parse_float(
        _pick_first(
            flat,
            (
                "cantidadOperaciones",
                "CantidadOperaciones",
                "operaciones",
                "Operaciones",
            ),
        ),
    )
    fh = _pick_first(flat, ("fechaHora", "FechaHora", "fecha", "Fecha"))
    fecha_hora = str(fh).strip() if fh is not None else None

    return IolOptionQuote(
        symbol=symbol,
        bid=bid,
        ask=ask,
        puntas=puntas_out,
        volume=vol,
        cantidad_operaciones=ops,
        fecha_hora=fecha_hora,
        error=None,
    )


def _http_get_cotizacion(symbol: str, timeout: float) -> tuple[int, dict[str, Any] | None, str | None]:
    tok = get_iol_token()
    if not tok:
        return 0, None, "no_token"
    if not is_iol_enabled():
        return 0, None, "iol_disabled"
    t = _normalize_symbol(symbol)
    if not t:
        return 0, None, "empty_symbol"
    url = IOL_COTIZACION_URL.format(ticker=t)
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        return 0, None, f"{type(e).__name__}: {str(e)[:120]}"
    if not r.ok:
        return r.status_code, None, (r.text or "")[:200]
    try:
        obj: Any = r.json()
    except ValueError:
        return r.status_code, None, "invalid_json"
    if not isinstance(obj, dict):
        return r.status_code, None, f"unexpected_type={type(obj).__name__}"
    return r.status_code, obj, None


def fetch_iol_option_quote(symbol: str, *, timeout: float = 2.5) -> IolOptionQuote:
    """
    Una especie: GET v1 ``/api/bCBA/Titulos/{symbol}/Cotizacion`` (mismo que ``get_iol_quote``).
    Resultado cacheado en RAM por ``OPTIONS_IOL_QUOTE_CACHE_TTL_SECONDS``.
    """
    sym = _normalize_symbol(symbol)
    t0 = time.perf_counter()
    now = time.monotonic()
    ttl = max(1.0, OPTIONS_IOL_QUOTE_CACHE_TTL_SECONDS)

    with _CACHE_LOCK:
        hit = _CACHE.get(sym)
        if hit is not None:
            exp, cached = hit
            if now < exp:
                _log("cache_hit symbol=%r ttl_left_s=%.2f" % (sym, exp - now))
                _log_options_quote_debug(sym, status_label="cache_hit", http_status=0, data=None, q=cached)
                return cached

    status, data, err = _http_get_cotizacion(sym, timeout=timeout)
    ms = (time.perf_counter() - t0) * 1000.0

    if err:
        q = IolOptionQuote(
            symbol=sym,
            bid=None,
            ask=None,
            puntas=None,
            volume=None,
            cantidad_operaciones=None,
            fecha_hora=None,
            error=err,
        )
        _log("symbol=%r status=%s ms=%.0f error=%r" % (sym, status, ms, err))
        _log_options_quote_debug(sym, status_label=str(err), http_status=status, data=data, q=q)
    else:
        assert data is not None
        q = _parse_cotizacion_json(sym, data)
        _log(
            "symbol=%r status=%s ms=%.0f bid=%r ask=%r vol=%r ops=%r"
            % (sym, status, ms, q.bid, q.ask, q.volume, q.cantidad_operaciones)
        )
        _log_options_quote_debug(sym, status_label="http_ok", http_status=status, data=data, q=q)

    with _CACHE_LOCK:
        _CACHE[sym] = (now + ttl, q)

    return q


def fetch_iol_option_quotes_batch(symbols: list[str], *, max_workers: int = 5) -> dict[str, IolOptionQuote]:
    """
    Varias especies en paralelo (pool acotado). Respeta caché por símbolo.
    """
    seen: list[str] = []
    for s in symbols:
        u = _normalize_symbol(s)
        if u and u not in seen:
            seen.append(u)
    if not seen:
        return {}
    workers = max(1, min(int(max_workers), 8, len(seen)))
    out: dict[str, IolOptionQuote] = {}
    if len(seen) == 1:
        s0 = seen[0]
        out[s0] = fetch_iol_option_quote(s0)
        return out

    _log("batch start symbols=%s workers=%s" % (len(seen), workers))
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fut_map = {pool.submit(fetch_iol_option_quote, s): s for s in seen}
        for fut in as_completed(fut_map):
            s = fut_map[fut]
            try:
                out[s] = fut.result()
            except Exception as ex:
                out[s] = IolOptionQuote(
                    symbol=s,
                    bid=None,
                    ask=None,
                    puntas=None,
                    volume=None,
                    cantidad_operaciones=None,
                    fecha_hora=None,
                    error=f"{type(ex).__name__}: {ex}",
                )
                _log("batch symbol=%r exception=%r" % (s, out[s].error))
                _log_options_quote_debug(
                    s,
                    status_label=f"exception:{type(ex).__name__}",
                    http_status=0,
                    data=None,
                    q=out[s],
                )
    _log("batch done symbols=%s total_ms=%.0f" % (len(seen), (time.perf_counter() - t0) * 1000.0))
    return out


def clear_iol_option_quote_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
