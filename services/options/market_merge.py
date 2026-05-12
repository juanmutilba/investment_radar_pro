"""
Merge operativo Allaria + Rava por make_contract_key (bid/ask/volumen vs last).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from services.options.models import OptionChain, OptionContract
from services.options.normalizer import make_contract_key, normalize_option_type, normalize_underlying

BidaskSourceMode = Literal["iol_live", "allaria_fallback", "rava_fallback", "none"]


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


def _first_with_label(
    order: tuple[tuple[Any, str], ...],
) -> tuple[Any, str]:
    for val, label in order:
        if val is not None:
            return val, label
    return None, "none"


def _merged_sources_labels(field_sources: dict[str, str]) -> list[str]:
    """IOL es siempre el universo; Allaria/Rava solo si aportaron algún campo."""
    out: list[str] = ["iol"]
    for lab in ("allaria", "rava"):
        if lab in field_sources.values():
            out.append(lab)
    return out


def _numeric_positive(v: Any) -> bool:
    if v is None:
        return False
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return x == x and x > 0


def _iol_primary_pick_traded(
    iol_val: Any,
    allaria_val: Any,
    rava_val: Any,
    *,
    order: tuple[Literal["allaria", "rava"], ...],
) -> tuple[float | None, str, dict[str, str] | None]:
    """
    IOL solo si valor > 0; si no, primer fallback en ``order`` con valor > 0.
    Devuelve (valor, field_source, field_fallback|None).
    """
    if _numeric_positive(iol_val):
        try:
            return float(iol_val), "iol", None
        except (TypeError, ValueError):
            pass

    if iol_val is not None:
        try:
            z = float(iol_val)
            fb_from: str = "iol_zero" if z == z and z <= 0 else "iol_none"
        except (TypeError, ValueError):
            fb_from = "iol_none"
    else:
        fb_from = "iol_none"

    for lab in order:
        val = allaria_val if lab == "allaria" else rava_val
        if _numeric_positive(val):
            try:
                return float(val), lab, {"from": fb_from, "to": lab}
            except (TypeError, ValueError):
                continue
    return None, "none", None


def _iol_primary_volume(
    iol_val: Any,
    allaria_val: Any,
    rava_val: Any,
) -> tuple[float | None, str, dict[str, str] | None]:
    """
    Volumen: prioriza IOL si viene informado (incluye 0); si no, Allaria → Rava.
    """
    if iol_val is not None:
        try:
            x = float(iol_val)
            if x == x:
                return x, "iol", None
        except (TypeError, ValueError):
            pass
    fb_from = "iol_none"
    for val, lab in ((allaria_val, "allaria"), (rava_val, "rava")):
        if val is not None:
            try:
                y = float(val)
                if y == y:
                    return y, lab, {"from": fb_from, "to": lab}
            except (TypeError, ValueError):
                continue
    return None, "none", None


def _compute_bidask_source_mode(
    bid: float | None,
    ask: float | None,
    bid_fs: str,
    ask_fs: str,
) -> BidaskSourceMode:
    """
    Resume el origen de las puntas (solo lados > 0 cuentan).
    Si hubo aporte de Allaria en cualquier lado → ``allaria_fallback`` salvo que ambos lados sean solo IOL.
    """
    bp = _numeric_positive(bid)
    ap = _numeric_positive(ask)
    if not bp and not ap:
        return "none"
    sources: set[str] = set()
    if bp:
        sources.add(bid_fs)
    if ap:
        sources.add(ask_fs)
    if sources <= {"iol"}:
        return "iol_live"
    if "allaria" in sources:
        return "allaria_fallback"
    if "rava" in sources:
        return "rava_fallback"
    return "none"


def _iol_primary_open_interest(
    iol_val: Any,
    allaria_val: Any,
    rava_val: Any,
) -> tuple[float | None, str]:
    """IOL si no es None (incluso 0); si no, Allaria > Rava con primer no-None."""
    if iol_val is not None:
        try:
            return float(iol_val), "iol"
        except (TypeError, ValueError):
            pass
    v, lab = _first_with_label(
        (
            (allaria_val, "allaria"),
            (rava_val, "rava"),
        )
    )
    if v is not None:
        try:
            return float(v), lab
        except (TypeError, ValueError):
            pass
    return None, "none"


def build_iol_primary_market_chain(
    underlying: str,
    iol_contracts: list[OptionContract],
    allaria_contracts: list[OptionContract],
    rava_contracts: list[OptionContract],
) -> OptionChain:
    """
    Universo estructural = IOL; Allaria/Rava rellenan por ``make_contract_key`` sin agregar filas.

    Bid/ask: IOL solo si > 0; si no, Allaria > Rava. Last: IOL > 0 si no Rava > Allaria.
    Volumen: valor IOL si está informado (incluye 0); si no, Allaria → Rava.

    ``raw`` incluye ``field_sources``, ``bidask_source_mode`` (iol_live | allaria_fallback | rava_fallback | none).
    """
    iol_p = _prep_contracts_for_keys(underlying, iol_contracts)
    a_p = _prep_contracts_for_keys(underlying, allaria_contracts)
    r_p = _prep_contracts_for_keys(underlying, rava_contracts)
    idx_a = _index_by_key(a_p)
    idx_r = _index_by_key(r_p)

    matched_a = 0
    matched_r = 0
    out: list[OptionContract] = []
    fb_bid = fb_ask = fb_last = fb_vol = 0
    n_ba_iol = n_ba_allaria = n_ba_rava = n_ba_none = 0

    for c in iol_p:
        k = make_contract_key(c)
        ca = idx_a.get(k)
        cr = idx_r.get(k)
        if ca is not None:
            matched_a += 1
        if cr is not None:
            matched_r += 1

        ab = ca.bid if ca else None
        rb = cr.bid if cr else None
        bid, bid_fs, bid_fb = _iol_primary_pick_traded(c.bid, ab, rb, order=("allaria", "rava"))
        if bid_fb is not None:
            fb_bid += 1

        aa = ca.ask if ca else None
        ra = cr.ask if cr else None
        ask, ask_fs, ask_fb = _iol_primary_pick_traded(c.ask, aa, ra, order=("allaria", "rava"))
        if ask_fb is not None:
            fb_ask += 1

        al = ca.last if ca else None
        rl = cr.last if cr else None
        last, last_fs, last_fb = _iol_primary_pick_traded(c.last, al, rl, order=("rava", "allaria"))
        if last_fb is not None:
            fb_last += 1

        av = ca.volume if ca else None
        rv = cr.volume if cr else None
        volume, vol_fs, vol_fb = _iol_primary_volume(c.volume, av, rv)
        if vol_fb is not None:
            fb_vol += 1

        ao = ca.open_interest if ca else None
        ro = cr.open_interest if cr else None
        oi, oi_fs = _iol_primary_open_interest(c.open_interest, ao, ro)

        field_sources: dict[str, str] = {
            "bid": bid_fs,
            "ask": ask_fs,
            "last": last_fs,
            "volume": vol_fs,
            "open_interest": oi_fs,
        }
        merged_sources = _merged_sources_labels(field_sources)

        field_fallbacks: dict[str, Any] = {}
        if bid_fb is not None:
            field_fallbacks["bid"] = bid_fb
        if ask_fb is not None:
            field_fallbacks["ask"] = ask_fb
        if last_fb is not None:
            field_fallbacks["last"] = last_fb
        if vol_fb is not None:
            field_fallbacks["volume"] = vol_fb

        raw_out: dict[str, Any] = dict(c.raw) if isinstance(c.raw, dict) else {}
        raw_out["field_sources"] = field_sources
        raw_out["merged_sources"] = merged_sources
        raw_out["iol_universe"] = True
        if field_fallbacks:
            raw_out["field_fallbacks"] = field_fallbacks

        ba_mode = _compute_bidask_source_mode(bid, ask, bid_fs, ask_fs)
        raw_out["bidask_source_mode"] = ba_mode
        if ba_mode == "iol_live":
            n_ba_iol += 1
        elif ba_mode == "allaria_fallback":
            n_ba_allaria += 1
        elif ba_mode == "rava_fallback":
            n_ba_rava += 1
        else:
            n_ba_none += 1

        out.append(
            replace(
                c,
                bid=bid,
                ask=ask,
                last=last,
                volume=volume,
                open_interest=oi,
                source="iol_primary",
                raw=raw_out,
            )
        )

    out.sort(
        key=lambda x: (
            x.expiry or "",
            x.option_type or "",
            x.strike is None,
            x.strike or 0.0,
            x.symbol or "",
        )
    )
    _log(
        f"iol_primary total_iol={len(iol_p)} matched_allaria={matched_a} matched_rava={matched_r} out={len(out)} "
        f"fallback_bid={fb_bid} fallback_ask={fb_ask} fallback_last={fb_last} fallback_volume={fb_vol}"
    )
    _log(
        f"iol_bidask_real={n_ba_iol} allaria_bidask_fallback={n_ba_allaria} "
        f"rava_bidask_fallback={n_ba_rava} none_bidask={n_ba_none}"
    )
    u_norm = normalize_underlying(underlying) or str(underlying).strip().upper()
    return OptionChain(underlying=u_norm, contracts=out)
