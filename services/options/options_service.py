"""
Servicio interno: cadena de opciones merged (Allaria + Rava) con fallback por fuente.
"""

from __future__ import annotations

from services.market_data.facade import get_argentina_price
from services.market_data.providers.iol import get_iol_quote, is_iol_enabled
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


def resolve_option_chain_spot(underlying: str | None) -> tuple[float | None, str | None, str | None]:
    """
    Precio spot del subyacente (acción local) vía market_data.

    Prioriza IOL (BCBA) con ticker BYMA (p. ej. GGAL). Si no hay precio válido,
    usa Yahoo Finance con símbolo BYMA ``*.BA`` (p. ej. GGAL.BA). Si Yahoo falla,
    reutiliza la cadena export → IOL → Yahoo(ticker BYMA) de ``get_argentina_price``.

    Returns
    -------
    spot, spot_source, spot_symbol
        Si no hay precio: spot y spot_source en None; spot_symbol puede ser el ticker consultado.
    """
    sym = option_underlying_to_spot_symbol(underlying)
    ysym = option_underlying_to_yahoo_symbol(underlying)
    _log_spot(
        f"underlying_received={underlying!r} spot_symbol={sym!r} yahoo_symbol={ysym!r} "
        f"get_argentina_ticker_in={sym!r}"
    )
    if not sym:
        _log_spot("abort empty_spot_symbol fallback_applied=none")
        return None, None, None

    # 1) IOL primero (precio válido > 0)
    _log_spot(f"iol_attempt ticker={sym}")
    if not is_iol_enabled():
        _log_spot(f"iol_miss ticker={sym} reason=disabled")
    else:
        try:
            iq = get_iol_quote(sym)
        except Exception as ex:
            iq = None
            _log_spot(f"iol_miss ticker={sym} reason=exception detail={type(ex).__name__}")
        if iq is not None and iq.is_valid and iq.value is not None:
            try:
                val_iol = float(iq.value)
            except (TypeError, ValueError):
                val_iol = None
            if val_iol is not None and val_iol == val_iol and val_iol > 0:
                _log_spot(f"iol_ok ticker={sym} price={val_iol!r} source=IOL")
                return val_iol, "IOL", sym
        _log_spot(f"iol_miss ticker={sym} reason=no_valid_quote")

    # 2) Yahoo .BA (fallback explícito)
    if ysym:
        _log_spot(f"yahoo_fallback ticker={ysym}")
        try:
            yq = yahoo_last_price(ysym, "ARS")
        except Exception as ex:
            yq = None
            _log_spot(f"yahoo_miss ticker={ysym} reason=exception detail={type(ex).__name__}")
        if yq is not None and yq.is_valid and yq.value is not None:
            try:
                val_y = float(yq.value)
            except (TypeError, ValueError):
                val_y = None
            if val_y is not None and val_y == val_y and val_y > 0:
                _log_spot(f"yahoo_ok ticker={ysym} price={val_y!r} source=Yahoo")
                return val_y, "Yahoo", ysym
        _log_spot(f"yahoo_miss ticker={ysym} reason=no_valid_price")

    # 3) Fallbacks existentes (export → IOL → Yahoo ticker BYMA)
    try:
        q = get_argentina_price(sym, prefer_export=True, options_spot_yahoo_symbol=None)
    except Exception as ex:
        _log_spot(f"error get_argentina_price={ex!r} fallback_applied=none")
        return None, None, sym
    if not q.is_valid or q.value is None:
        _log_spot(
            f"no_price underlying_received={underlying!r} spot_symbol={sym!r} "
            f"yahoo_symbol={ysym!r} fallback_applied=unresolved"
        )
        return None, None, sym
    try:
        val = float(q.value)
    except (TypeError, ValueError):
        _log_spot("no_price invalid_float fallback_applied=unresolved")
        return None, None, sym
    if val != val or val <= 0:
        _log_spot("no_price non_positive fallback_applied=unresolved")
        return None, None, sym
    src = _spot_source_label(str(q.source))
    used = (q.symbol_used or sym).strip().upper() or sym
    fb = str(q.source).lower() or "unknown"
    _log_spot(
        f"ok underlying_received={underlying!r} spot_symbol={sym!r} yahoo_symbol={ysym!r} "
        f"source={src!r} provider={str(q.source)!r} price={val!r} symbol_used={used!r} "
        f"fallback_applied={fb!r}"
    )
    return val, src, used


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


def get_options_chain(underlying: str) -> OptionChain:
    """
    Si IOL devuelve contratos, universo operable = IOL y Allaria/Rava solo enriquecen por clave.
    Si IOL no está disponible o devuelve 0 contratos, merge clásico Allaria + Rava.
    """
    _log(f"start underlying={underlying!r}")

    ci: list[OptionContract] = []
    try:
        ci = fetch_iol_option_contracts(underlying)
    except Exception as e:
        _log(f"error iol={e!r}")

    ca: list[OptionContract] = []
    cr: list[OptionContract] = []
    ok_a = False
    ok_r = False

    if len(ci) > 0:
        _log(f"iol available contracts={len(ci)} using_iol_primary=true")
        try:
            ca = fetch_allaria_option_contracts(underlying)
            ok_a = True
        except Exception as e:
            _log(f"error allaria(enrich)={e!r}")
        try:
            cr = fetch_rava_option_contracts(underlying)
            ok_r = True
        except Exception as e:
            _log(f"error rava(enrich)={e!r}")
        try:
            chain = build_iol_primary_market_chain(underlying, ci, ca, cr)
            _log(f"end iol_primary underlying={underlying!r} contracts={len(chain.contracts)}")
            return chain
        except Exception as e:
            _log(f"error iol_primary_build={e!r} fallback_allaria_rava=true")
            return _legacy_merge_chain(underlying, ca, cr, ok_a, ok_r)

    _log("iol unavailable fallback_allaria_rava=true")
    try:
        ca = fetch_allaria_option_contracts(underlying)
        ok_a = True
    except Exception as e:
        _log(f"error allaria={e!r}")
    try:
        cr = fetch_rava_option_contracts(underlying)
        ok_r = True
    except Exception as e:
        _log(f"error rava={e!r}")
    return _legacy_merge_chain(underlying, ca, cr, ok_a, ok_r)
