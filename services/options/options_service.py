"""
Servicio interno: cadena de opciones merged (Allaria + Rava) con fallback por fuente.
"""

from __future__ import annotations

from services.options.chain_builder import build_master_chain
from services.options.market_merge import build_merged_market_chain
from services.options.models import OptionChain, OptionContract
from services.options.normalizer import normalize_underlying
from services.options.providers.allaria import fetch_allaria_option_contracts
from services.options.providers.rava import fetch_rava_option_contracts


def _log(msg: str) -> None:
    print(f"[OPTIONS_SERVICE] {msg}", flush=True)


def _empty_chain(underlying: str) -> OptionChain:
    u_norm = normalize_underlying(underlying) or str(underlying or "").strip().upper()
    return OptionChain(underlying=u_norm, contracts=[])


def get_options_chain(underlying: str) -> OptionChain:
    """
    Obtiene OptionChain merged cuando ambas fuentes responden; si una falla, cadena maestra
    de la otra; si ambas fallan o no hay datos, lista vacía. raw/field_sources se conservan
    en el camino merge; en fallback solo el raw del provider.
    """
    _log(f"start underlying={underlying!r}")

    ca: list[OptionContract] = []
    cr: list[OptionContract] = []
    ok_a = False
    ok_r = False

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
