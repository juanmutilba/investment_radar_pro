"""
Merge operativo Allaria + Rava por make_contract_key (bid/ask/volumen vs last).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from services.options.models import OptionChain, OptionContract
from services.options.normalizer import make_contract_key, normalize_option_type, normalize_underlying


def _log(msg: str) -> None:
    print(f"[OPTIONS_MERGE] {msg}", flush=True)


def _field_source(primary_val: Any, secondary_val: Any, primary_name: str, secondary_name: str) -> str:
    if primary_val is not None:
        return primary_name
    if secondary_val is not None:
        return secondary_name
    return "none"


def _prep_contracts_for_keys(underlying: str, contracts: list[OptionContract]) -> list[OptionContract]:
    """Alinea underlying/option_type como build_master_chain; copia superficial de raw."""
    u_norm = normalize_underlying(underlying) or str(underlying).strip().upper()
    out: list[OptionContract] = []
    for c in contracts:
        nc = replace(c, underlying=u_norm)
        ot = normalize_option_type(nc.option_type)
        if ot is not None:
            nc = replace(nc, option_type=ot)
        nc = replace(nc, raw=dict(nc.raw) if nc.raw else None)
        out.append(nc)
    return out


def _index_by_key(contracts: list[OptionContract]) -> dict[tuple[Any, ...], OptionContract]:
    idx: dict[tuple[Any, ...], OptionContract] = {}
    for c in contracts:
        k = make_contract_key(c)
        if k not in idx:
            idx[k] = c
    return idx


def _merge_two(p: OptionContract, s: OptionContract) -> OptionContract:
    bid = p.bid if p.bid is not None else s.bid
    ask = p.ask if p.ask is not None else s.ask
    volume = p.volume if p.volume is not None else s.volume
    last = s.last if s.last is not None else p.last
    oi = p.open_interest if p.open_interest is not None else s.open_interest

    field_sources = {
        "bid": _field_source(p.bid, s.bid, "allaria", "rava"),
        "ask": _field_source(p.ask, s.ask, "allaria", "rava"),
        "volume": _field_source(p.volume, s.volume, "allaria", "rava"),
        "last": _field_source(s.last, p.last, "rava", "allaria"),
        "open_interest": _field_source(p.open_interest, s.open_interest, "allaria", "rava"),
    }

    raw_out: dict[str, Any] = dict(p.raw) if p.raw else {}
    raw_out["merged_sources"] = ["allaria", "rava"]
    raw_out["field_sources"] = field_sources

    return OptionContract(
        underlying=p.underlying,
        expiry=p.expiry,
        strike=p.strike,
        option_type=p.option_type,
        symbol=p.symbol,
        bid=bid,
        ask=ask,
        last=last,
        volume=volume,
        open_interest=oi,
        source="merged",
        raw=raw_out,
    )


def _single_allaria(p: OptionContract) -> OptionContract:
    fs = {
        "bid": "allaria" if p.bid is not None else "none",
        "ask": "allaria" if p.ask is not None else "none",
        "volume": "allaria" if p.volume is not None else "none",
        "last": "allaria" if p.last is not None else "none",
        "open_interest": "allaria" if p.open_interest is not None else "none",
    }
    raw_out = dict(p.raw) if p.raw else {}
    raw_out["merged_sources"] = ["allaria"]
    raw_out["field_sources"] = fs
    return replace(p, source="allaria", raw=raw_out)


def _single_rava_only(s: OptionContract) -> OptionContract:
    fs = {
        "bid": "rava" if s.bid is not None else "none",
        "ask": "rava" if s.ask is not None else "none",
        "volume": "rava" if s.volume is not None else "none",
        "last": "rava" if s.last is not None else "none",
        "open_interest": "rava" if s.open_interest is not None else "none",
    }
    raw_out = dict(s.raw) if s.raw else {}
    raw_out["merged_sources"] = ["rava_only"]
    raw_out["field_sources"] = fs
    return replace(s, source="rava_only", raw=raw_out)


def merge_option_market_data(
    primary: list[OptionContract],
    secondary: list[OptionContract],
) -> list[OptionContract]:
    """
    primary = Allaria, secondary = Rava.
    Clave: make_contract_key (contratos ya alineados en underlying/tipo).
    """
    pri = _index_by_key(primary)
    sec = _index_by_key(secondary)
    pri_keys = set(pri)
    sec_keys = set(sec)
    common = pri_keys & sec_keys
    allaria_only = pri_keys - sec_keys
    rava_only = sec_keys - pri_keys

    _log(
        f"total_allaria={len(primary)} total_rava={len(secondary)} "
        f"common={len(common)} allaria_only={len(allaria_only)} rava_only={len(rava_only)}"
    )

    out: list[OptionContract] = []
    for k in common:
        out.append(_merge_two(pri[k], sec[k]))
    for k in allaria_only:
        out.append(_single_allaria(pri[k]))
    for k in rava_only:
        out.append(_single_rava_only(sec[k]))

    out.sort(
        key=lambda x: (
            x.expiry or "",
            x.option_type or "",
            x.strike is None,
            x.strike or 0.0,
            x.symbol or "",
        )
    )
    _log(f"out={len(out)}")
    return out


def build_merged_market_chain(
    underlying: str,
    allaria_contracts: list[OptionContract],
    rava_contracts: list[OptionContract],
) -> OptionChain:
    """Normaliza claves y fusiona mercado Allaria + Rava."""
    p = _prep_contracts_for_keys(underlying, allaria_contracts)
    s = _prep_contracts_for_keys(underlying, rava_contracts)
    merged = merge_option_market_data(p, s)
    u_norm = normalize_underlying(underlying) or str(underlying).strip().upper()
    return OptionChain(underlying=u_norm, contracts=merged)
