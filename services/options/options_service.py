"""
Servicio interno: cadena de opciones merged (Allaria + Rava) con fallback por fuente.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from services.market_data.facade import get_argentina_price
from services.market_data.types import PriceQuote
from services.market_data.providers.iol import (
    ensure_iol_credentials_from_env,
    get_iol_quote,
    is_iol_enabled,
    read_iol_quote_ram_only,
)
from services.market_data.providers.yahoo_spot import yahoo_last_price
from services.options.chain_builder import build_master_chain
from services.options.market_merge import build_iol_primary_market_chain, build_merged_market_chain
from services.options.models import OptionChain, OptionContract
from services.options.normalizer import normalize_underlying
from services.options.providers.allaria import fetch_allaria_option_contracts
from services.options.providers.iol import fetch_iol_option_contracts
from services.options.providers.rava import fetch_rava_option_contracts
from services.options.spot_mapping import option_underlying_to_spot_symbol, option_underlying_to_yahoo_symbol


def _log(msg: str) -> None:
    print(f"[OPTIONS_SERVICE] {msg}", flush=True)


def _log_spot(msg: str) -> None:
    print(f"[OPTIONS_SPOT] {msg}", flush=True)


def _log_timing(msg: str) -> None:
    print(f"[OPTIONS_TIMING] {msg}", flush=True)


def _log_cache(msg: str) -> None:
    print(f"[OPTIONS_CACHE] {msg}", flush=True)


OPTIONS_CHAIN_CACHE_TTL_SECONDS = 15.0
_options_chain_cache: dict[tuple[str, bool], tuple[float, OptionChain]] = {}


def clear_options_chain_cache() -> None:
    """Vacía la caché en RAM de cadenas de opciones (tests / debug)."""
    _options_chain_cache.clear()


def _options_chain_cache_key(underlying: str, enrich_sources: bool) -> tuple[str, bool]:
    u_norm = normalize_underlying(underlying) or str(underlying or "").strip().upper()
    return (u_norm, enrich_sources)


def _empty_chain(underlying: str) -> OptionChain:
    u_norm = normalize_underlying(underlying) or str(underlying or "").strip().upper()
    return OptionChain(underlying=u_norm, contracts=[])


def _spot_source_label(source: str) -> str:
    m = {
        "export": "export",
        "yahoo": "Yahoo",
        "iol": "IOL",
        "snapshot": "snapshot",
        "unknown": "unknown",
    }
    return m.get(source, source)


def _empty_spot_meta() -> dict[str, Any]:
    return {
        "spot_source_detail": None,
        "spot_cache_hit": None,
        "spot_updated_at": None,
        "spot_symbol_used": None,
    }


def _log_options_spot_iol_fail(
    *,
    underlying: str | None,
    attempted_symbol: str,
    reason: str,
    result: str,
    ram_before: str,
    exception_status: str | None,
) -> None:
    exc = f" exception_status={exception_status!r}" if exception_status else ""
    print(
        "[OPTIONS_SPOT_IOL_FAIL]"
        f" underlying={underlying!r}"
        f" attempted_symbol={attempted_symbol!r}"
        f" reason={reason}"
        f" result={result}"
        f" ram_before={ram_before}"
        f"{exc}",
        flush=True,
    )


def resolve_option_chain_spot(
    underlying: str | None,
) -> tuple[float | None, str | None, str | None, dict[str, Any]]:
    """
    Precio spot del subyacente (acción local) vía market_data.

    Prioriza IOL (BCBA) con ticker BYMA (p. ej. GGAL). Si no hay precio válido,
    usa Yahoo Finance con símbolo BYMA ``*.BA`` (p. ej. GGAL.BA). Si Yahoo falla,
    reutiliza la cadena export → IOL → Yahoo(ticker BYMA) de ``get_argentina_price``.

    Returns
    -------
    spot, spot_source, spot_symbol, meta
        meta incluye (opcional) spot_source_detail, spot_cache_hit (siempre false si precio IOL
        directo: se evita RAM positiva para no desfasar vs. cadena en TTL), spot_updated_at (ISO),
        spot_symbol_used.
    """
    meta = _empty_spot_meta()
    # Ticker BCBA para Titulos/Cotizacion (p. ej. GGAL), nunca prefijo de opción (GFG).
    sym = option_underlying_to_spot_symbol(underlying)
    ysym = option_underlying_to_yahoo_symbol(underlying)
    _log_spot(
        f"underlying_received={underlying!r} spot_symbol={sym!r} yahoo_symbol={ysym!r} "
        f"get_argentina_ticker_in={sym!r}"
    )
    if not sym:
        _log_spot("abort empty_spot_symbol fallback_applied=none")
        _log_timing("spot_iol_ms=0.0")
        _log_timing("spot_yahoo_ms=0.0")
        meta["spot_source_detail"] = "empty_spot_symbol"
        return None, None, None, meta

    spot_iol_ms = 0.0
    spot_yahoo_ms = 0.0

    # 1) IOL primero (precio válido > 0): siempre ticker acción BCBA (p. ej. GGAL), bypass RAM +/−.
    _log_spot(f"iol_attempt ticker={sym}")
    iol_exc: str | None = None
    iq: PriceQuote | None = None
    ram_before = "n/a"
    if not is_iol_enabled():
        _log_spot(f"iol_miss ticker={sym} reason=disabled")
        _log_timing("spot_iol_ms=0.0")
        _log_options_spot_iol_fail(
            underlying=underlying,
            attempted_symbol=sym,
            reason="iol_disabled",
            result="None",
            ram_before=ram_before,
            exception_status=None,
        )
    else:
        ram_hit = read_iol_quote_ram_only(sym)
        if isinstance(ram_hit, PriceQuote):
            ram_before = "positive_ram"
        elif ram_hit == "negative":
            ram_before = "negative_ram"
        else:
            ram_before = "none"
        iol_ram_cache = isinstance(ram_hit, PriceQuote)
        t_iol = time.perf_counter()
        try:
            iq = get_iol_quote(
                sym,
                bypass_positive_ram_cache=True,
                bypass_negative_ram_cache=True,
            )
        except Exception as ex:
            iq = None
            iol_exc = f"{type(ex).__name__}: {ex}"
            _log_spot(f"iol_miss ticker={sym} reason=exception detail={type(ex).__name__}")
        spot_iol_ms = (time.perf_counter() - t_iol) * 1000.0
        _log_timing(f"spot_iol_ms={spot_iol_ms:.1f}")
        val_iol: float | None = None
        if iq is not None and iq.is_valid and iq.value is not None:
            try:
                val_iol = float(iq.value)
            except (TypeError, ValueError):
                val_iol = None
        if iq is not None and val_iol is not None and val_iol == val_iol and val_iol > 0:
            _log_spot(f"iol_ok ticker={sym} price={val_iol!r} source=IOL")
            _log_timing("spot_yahoo_ms=0.0")
            meta["spot_source_detail"] = (
                "iol_titulos_cotizacion|iol_positive_ram_bypassed"
                if iol_ram_cache
                else "iol_titulos_cotizacion"
            )
            meta["spot_cache_hit"] = False
            meta["spot_symbol_used"] = sym
            if iq.as_of is not None:
                meta["spot_updated_at"] = iq.as_of.isoformat()
            return val_iol, "IOL", sym, meta
        fail_reason = (
            "exception"
            if iol_exc
            else ("iol_no_quote" if iq is None else "iol_non_positive_or_invalid_price")
        )
        _log_spot(f"iol_miss ticker={sym} reason={fail_reason}")
        _log_options_spot_iol_fail(
            underlying=underlying,
            attempted_symbol=sym,
            reason=fail_reason,
            result=repr(iq) if iq is not None else "None",
            ram_before=ram_before,
            exception_status=iol_exc,
        )

    # 2) Yahoo .BA (fallback explícito)
    if ysym:
        _log_spot(f"yahoo_fallback ticker={ysym}")
        t_y = time.perf_counter()
        try:
            yq = yahoo_last_price(ysym, "ARS")
        except Exception as ex:
            yq = None
            _log_spot(f"yahoo_miss ticker={ysym} reason=exception detail={type(ex).__name__}")
        spot_yahoo_ms = (time.perf_counter() - t_y) * 1000.0
        _log_timing(f"spot_yahoo_ms={spot_yahoo_ms:.1f}")
        if yq is not None and yq.is_valid and yq.value is not None:
            try:
                val_y = float(yq.value)
            except (TypeError, ValueError):
                val_y = None
            if val_y is not None and val_y == val_y and val_y > 0:
                _log_spot(f"yahoo_ok ticker={ysym} price={val_y!r} source=Yahoo")
                meta["spot_source_detail"] = "yahoo_last_price_ba"
                meta["spot_cache_hit"] = None
                meta["spot_symbol_used"] = ysym
                if yq.as_of is not None:
                    meta["spot_updated_at"] = yq.as_of.isoformat()
                return val_y, "Yahoo", ysym, meta
        _log_spot(f"yahoo_miss ticker={ysym} reason=no_valid_price")
    else:
        _log_timing("spot_yahoo_ms=0.0")

    # 3) Fallbacks existentes (export → IOL → Yahoo ticker BYMA)
    try:
        q = get_argentina_price(sym, prefer_export=True, options_spot_yahoo_symbol=None)
    except Exception as ex:
        _log_spot(f"error get_argentina_price={ex!r} fallback_applied=none")
        meta["spot_source_detail"] = "facade_get_argentina_price_error"
        meta["spot_symbol_used"] = sym
        return None, None, sym, meta
    if not q.is_valid or q.value is None:
        _log_spot(
            f"no_price underlying_received={underlying!r} spot_symbol={sym!r} "
            f"yahoo_symbol={ysym!r} fallback_applied=unresolved"
        )
        meta["spot_source_detail"] = "facade_get_argentina_price_no_price"
        meta["spot_symbol_used"] = sym
        return None, None, sym, meta
    try:
        val = float(q.value)
    except (TypeError, ValueError):
        _log_spot("no_price invalid_float fallback_applied=unresolved")
        meta["spot_source_detail"] = "facade_get_argentina_price_invalid_float"
        meta["spot_symbol_used"] = sym
        return None, None, sym, meta
    if val != val or val <= 0:
        _log_spot("no_price non_positive fallback_applied=unresolved")
        meta["spot_source_detail"] = "facade_get_argentina_price_non_positive"
        meta["spot_symbol_used"] = sym
        return None, None, sym, meta
    src = _spot_source_label(str(q.source))
    used = (q.symbol_used or sym).strip().upper() or sym
    fb = str(q.source).lower() or "unknown"
    _log_spot(
        f"ok underlying_received={underlying!r} spot_symbol={sym!r} yahoo_symbol={ysym!r} "
        f"source={src!r} provider={str(q.source)!r} price={val!r} symbol_used={used!r} "
        f"fallback_applied={fb!r}"
    )
    meta["spot_source_detail"] = f"facade_get_argentina_price_source={fb}"
    meta["spot_cache_hit"] = None
    meta["spot_symbol_used"] = used
    if q.as_of is not None:
        meta["spot_updated_at"] = q.as_of.isoformat()
    return val, src, used, meta


def _legacy_merge_chain(
    underlying: str,
    ca: list[OptionContract],
    cr: list[OptionContract],
    ok_a: bool,
    ok_r: bool,
) -> OptionChain:
    u_norm = normalize_underlying(underlying) or str(underlying or "").strip().upper()
    try:
        if ok_a and ok_r:
            chain = build_merged_market_chain(underlying, ca, cr)
        elif ok_a:
            chain = build_master_chain(underlying, ca)
        elif ok_r:
            chain = build_master_chain(underlying, cr)
        else:
            _log(f"end underlying={underlying!r} contracts=0 (sin fuentes)")
            return _empty_chain(underlying)
        _log(f"end underlying={underlying!r} contracts={len(chain.contracts)}")
        return chain
    except Exception as e:
        _log(f"error chain_build={e!r}")
        if ok_a:
            try:
                c = build_master_chain(underlying, ca)
                _log(f"end fallback=allaria contracts={len(c.contracts)}")
                return c
            except Exception as e2:
                _log(f"error fallback_allaria={e2!r}")
        if ok_r:
            try:
                c = build_master_chain(underlying, cr)
                _log(f"end fallback=rava contracts={len(c.contracts)}")
                return c
            except Exception as e3:
                _log(f"error fallback_rava={e3!r}")
        _log(f"end underlying={underlying!r} contracts=0 (vacío)")
        return OptionChain(underlying=u_norm, contracts=[])


def _compute_options_chain(underlying: str, *, enrich_sources: bool) -> OptionChain:
    """
    Construye la cadena sin consultar caché (llamar solo en miss).
    """
    t_all = time.perf_counter()
    _log(f"start underlying={underlying!r} enrich_sources={enrich_sources}")

    ci: list[OptionContract] = []
    t0 = time.perf_counter()
    try:
        ci = fetch_iol_option_contracts(underlying)
    except Exception as e:
        _log(f"error iol={e!r}")
    fetch_iol_ms = (time.perf_counter() - t0) * 1000.0
    _log_timing(f"fetch_iol_options_ms={fetch_iol_ms:.1f}")

    ca: list[OptionContract] = []
    cr: list[OptionContract] = []
    ok_a = False
    ok_r = False
    fetch_allaria_ms = 0.0
    fetch_rava_ms = 0.0
    merge_ms = 0.0

    if len(ci) > 0:
        _log(f"iol available contracts={len(ci)} using_iol_primary=true")
        if enrich_sources:
            t0 = time.perf_counter()
            try:
                ca = fetch_allaria_option_contracts(underlying)
                ok_a = True
            except Exception as e:
                _log(f"error allaria(enrich)={e!r}")
            fetch_allaria_ms = (time.perf_counter() - t0) * 1000.0
            _log_timing(f"fetch_allaria_ms={fetch_allaria_ms:.1f}")

            t0 = time.perf_counter()
            try:
                cr = fetch_rava_option_contracts(underlying)
                ok_r = True
            except Exception as e:
                _log(f"error rava(enrich)={e!r}")
            fetch_rava_ms = (time.perf_counter() - t0) * 1000.0
            _log_timing(f"fetch_rava_ms={fetch_rava_ms:.1f}")
        else:
            _log("enrich_sources=false skip_allaria_rava")
            fetch_allaria_ms = 0.0
            fetch_rava_ms = 0.0
            _log_timing("fetch_allaria_ms=0.0")
            _log_timing("fetch_rava_ms=0.0")

        t_merge = time.perf_counter()
        try:
            chain = build_iol_primary_market_chain(underlying, ci, ca, cr)
            merge_ms = (time.perf_counter() - t_merge) * 1000.0
            _log(f"end iol_primary underlying={underlying!r} contracts={len(chain.contracts)}")
            _log_timing(f"merge_ms={merge_ms:.1f}")
            _log_timing(
                f"get_options_chain_total_ms={(time.perf_counter() - t_all) * 1000.0:.1f} "
                f"underlying={underlying!r}"
            )
            return chain
        except Exception as e:
            _log(f"error iol_primary_build={e!r} fallback_allaria_rava=true")
            chain = _legacy_merge_chain(underlying, ca, cr, ok_a, ok_r)
            merge_ms = (time.perf_counter() - t_merge) * 1000.0
            _log_timing(f"merge_ms={merge_ms:.1f}")
            _log_timing(
                f"get_options_chain_total_ms={(time.perf_counter() - t_all) * 1000.0:.1f} "
                f"underlying={underlying!r}"
            )
            return chain

    _log("iol unavailable fallback_allaria_rava=true")
    t0 = time.perf_counter()
    try:
        ca = fetch_allaria_option_contracts(underlying)
        ok_a = True
    except Exception as e:
        _log(f"error allaria={e!r}")
    fetch_allaria_ms = (time.perf_counter() - t0) * 1000.0
    _log_timing(f"fetch_allaria_ms={fetch_allaria_ms:.1f}")

    t0 = time.perf_counter()
    try:
        cr = fetch_rava_option_contracts(underlying)
        ok_r = True
    except Exception as e:
        _log(f"error rava={e!r}")
    fetch_rava_ms = (time.perf_counter() - t0) * 1000.0
    _log_timing(f"fetch_rava_ms={fetch_rava_ms:.1f}")

    t_merge = time.perf_counter()
    chain = _legacy_merge_chain(underlying, ca, cr, ok_a, ok_r)
    merge_ms = (time.perf_counter() - t_merge) * 1000.0
    _log_timing(f"merge_ms={merge_ms:.1f}")
    _log_timing(
        f"get_options_chain_total_ms={(time.perf_counter() - t_all) * 1000.0:.1f} "
        f"underlying={underlying!r}"
    )
    return chain


def _parallel_worker_chain(underlying: str, enrich_sources: bool) -> tuple[OptionChain, float]:
    """Ejecuta en hilo: construye cadena sin caché. Devuelve (cadena, ms)."""
    t0 = time.perf_counter()
    try:
        ch = _compute_options_chain(underlying, enrich_sources=enrich_sources)
        return ch, (time.perf_counter() - t0) * 1000.0
    except Exception as e:
        _log(f"parallel_chain_worker_error={e!r}")
        return _empty_chain(underlying), (time.perf_counter() - t0) * 1000.0


def _parallel_worker_spot(underlying: str) -> tuple[tuple[float | None, str | None, str | None, dict[str, Any]], float]:
    """Ejecuta en hilo: resuelve spot. Devuelve (((spot, source, symbol, meta), ms))."""
    t0 = time.perf_counter()
    try:
        r = resolve_option_chain_spot(underlying)
        return r, (time.perf_counter() - t0) * 1000.0
    except Exception as e:
        _log_spot(f"parallel_spot_worker_error={type(e).__name__}: {e}")
        m = _empty_spot_meta()
        m["spot_source_detail"] = "resolve_exception"
        return (None, None, None, m), (time.perf_counter() - t0) * 1000.0


def _compose_chain_spot_payload(
    *,
    spot: float | None,
    spot_source: str | None,
    spot_symbol: str | None,
    spot_meta: dict[str, Any],
    spot_fetch_ms: float,
    chain_ttl_cache_hit: bool,
) -> dict[str, Any]:
    """JSON /options/chain: metadata de spot sin alterar el precio."""
    detail_parts: list[str] = []
    if chain_ttl_cache_hit:
        detail_parts.append("options_chain_ttl_cache_hit")
    detail_parts.append(f"spot_resolved_after_chain_cache={'true' if chain_ttl_cache_hit else 'false'}")
    inner = (spot_meta.get("spot_source_detail") or "").strip()
    if inner:
        detail_parts.append(inner)
    spot_source_detail = " | ".join(detail_parts) if detail_parts else (inner or None)
    sym_used = spot_symbol or spot_meta.get("spot_symbol_used")
    return {
        "spot": spot,
        "spot_source": spot_source,
        "spot_symbol": spot_symbol,
        "spot_source_detail": spot_source_detail,
        "spot_cache_hit": spot_meta.get("spot_cache_hit"),
        "spot_fetch_ms": round(float(spot_fetch_ms), 2),
        "spot_symbol_used": sym_used,
        "spot_updated_at": spot_meta.get("spot_updated_at"),
    }


def get_options_chain_with_spot(
    underlying: str, *, enrich_sources: bool = False
) -> tuple[OptionChain, dict[str, Any]]:
    """
    Cadena (con caché TTL como ``get_options_chain``) + spot del subyacente.

    En miss de caché, la cadena y el spot se resuelven en paralelo (hasta 2 hilos).
    Si falla uno de los dos, el otro sigue disponible en la respuesta.
    """
    ensure_iol_credentials_from_env()
    t_ws0 = time.perf_counter()
    t_lookup = time.perf_counter()
    key = _options_chain_cache_key(underlying, enrich_sources)
    u_key, enrich_key = key
    mono_now = time.monotonic()
    ent = _options_chain_cache.get(key)

    if ent is not None:
        ts_mono, cached_chain = ent
        age_seconds = mono_now - ts_mono
        if age_seconds < OPTIONS_CHAIN_CACHE_TTL_SECONDS:
            lookup_ms = (time.perf_counter() - t_lookup) * 1000.0
            _log_cache(
                f"hit underlying={u_key!r} enrich={enrich_key} age_seconds={age_seconds:.2f}"
            )
            _log_timing(f"cache_lookup_ms={lookup_ms:.3f} cache_hit=true")
            chain = cached_chain
            t_spot = time.perf_counter()
            spot_meta: dict[str, Any] = _empty_spot_meta()
            try:
                spot, spot_source, spot_symbol, spot_meta = resolve_option_chain_spot(underlying)
            except Exception as e:
                _log_spot(f"spot_after_cache_hit_error={type(e).__name__}: {e}")
                spot, spot_source, spot_symbol = None, None, None
                spot_meta = _empty_spot_meta()
                spot_meta["spot_source_detail"] = "resolve_after_chain_cache_error"
            spot_ms = (time.perf_counter() - t_spot) * 1000.0
            _log_timing("parallel_chain_ms=0.0")
            _log_timing(f"parallel_spot_ms={spot_ms:.1f}")
            _log_timing(f"chain_with_spot_total_ms={(time.perf_counter() - t_ws0) * 1000.0:.1f}")
            return chain, _compose_chain_spot_payload(
                spot=spot,
                spot_source=spot_source,
                spot_symbol=spot_symbol,
                spot_meta=spot_meta,
                spot_fetch_ms=spot_ms,
                chain_ttl_cache_hit=True,
            )

        _log_cache(
            f"expired underlying={u_key!r} enrich={enrich_key} age_seconds={age_seconds:.2f}"
        )

    _log_cache(f"miss underlying={u_key!r} enrich={enrich_key}")
    lookup_ms = (time.perf_counter() - t_lookup) * 1000.0
    _log_timing(f"cache_lookup_ms={lookup_ms:.3f} cache_hit=false")

    t_parallel_wall = time.perf_counter()
    chain_ms = 0.0
    spot_ms = 0.0
    chain: OptionChain = _empty_chain(underlying)
    spot: float | None = None
    spot_source: str | None = None
    spot_symbol: str | None = None
    spot_meta: dict[str, Any] = _empty_spot_meta()

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_chain = ex.submit(_parallel_worker_chain, underlying, enrich_sources)
        fut_spot = ex.submit(_parallel_worker_spot, underlying)
        try:
            chain, chain_ms = fut_chain.result()
        except Exception as e:
            _log(f"parallel_chain_future_error={e!r}")
            chain = _empty_chain(underlying)
            chain_ms = (time.perf_counter() - t_parallel_wall) * 1000.0
        try:
            (spot, spot_source, spot_symbol, spot_meta), spot_ms = fut_spot.result()
        except Exception as e:
            _log_spot(f"parallel_spot_future_error={type(e).__name__}: {e}")
            spot, spot_source, spot_symbol = None, None, None
            spot_meta = _empty_spot_meta()
            spot_meta["spot_source_detail"] = "parallel_spot_future_error"
            spot_ms = (time.perf_counter() - t_parallel_wall) * 1000.0

    _log_timing(f"parallel_chain_ms={chain_ms:.1f}")
    _log_timing(f"parallel_spot_ms={spot_ms:.1f}")

    if len(chain.contracts) > 0:
        _options_chain_cache[key] = (time.monotonic(), chain)

    _log_timing(f"chain_with_spot_total_ms={(time.perf_counter() - t_ws0) * 1000.0:.1f}")
    return chain, _compose_chain_spot_payload(
        spot=spot,
        spot_source=spot_source,
        spot_symbol=spot_symbol,
        spot_meta=spot_meta,
        spot_fetch_ms=spot_ms,
        chain_ttl_cache_hit=False,
    )


def get_options_chain(underlying: str, *, enrich_sources: bool = True) -> OptionChain:
    """
    Si IOL devuelve contratos, universo operable = IOL y Allaria/Rava solo enriquecen por clave
    (salvo ``enrich_sources=False``, útil para acortar latencia).
    Si IOL no está disponible o devuelve 0 contratos, merge clásico Allaria + Rava.

    Respuestas con al menos un contrato se memorizan en RAM ``OPTIONS_CHAIN_CACHE_TTL_SECONDS``.
    """
    ensure_iol_credentials_from_env()
    t_all = time.perf_counter()
    t_lookup = time.perf_counter()
    key = _options_chain_cache_key(underlying, enrich_sources)
    u_key, enrich_key = key
    mono_now = time.monotonic()
    ent = _options_chain_cache.get(key)
    if ent is not None:
        ts_mono, cached_chain = ent
        age_seconds = mono_now - ts_mono
        if age_seconds < OPTIONS_CHAIN_CACHE_TTL_SECONDS:
            lookup_ms = (time.perf_counter() - t_lookup) * 1000.0
            _log_cache(
                f"hit underlying={u_key!r} enrich={enrich_key} age_seconds={age_seconds:.2f}"
            )
            _log_timing(f"cache_lookup_ms={lookup_ms:.3f} cache_hit=true")
            _log_timing(
                f"get_options_chain_total_ms={(time.perf_counter() - t_all) * 1000.0:.1f} "
                f"underlying={underlying!r}"
            )
            return cached_chain
        _log_cache(
            f"expired underlying={u_key!r} enrich={enrich_key} age_seconds={age_seconds:.2f}"
        )

    _log_cache(f"miss underlying={u_key!r} enrich={enrich_key}")
    lookup_ms = (time.perf_counter() - t_lookup) * 1000.0
    _log_timing(f"cache_lookup_ms={lookup_ms:.3f} cache_hit=false")

    chain = _compute_options_chain(underlying, enrich_sources=enrich_sources)
    if len(chain.contracts) > 0:
        _options_chain_cache[key] = (time.monotonic(), chain)
    return chain
