from __future__ import annotations

from typing import Any

from services.options.models import OptionChain, OptionContract
from services.options.normalizer import make_contract_key, normalize_option_type, normalize_underlying

# Menor = más prioridad al deduplicar (Allaria gana sobre Rava).
_SOURCE_PRIORITY: dict[str, int] = {
    "allaria": 0,
    "rava": 1,
}


def _source_rank(source: str) -> int:
    s = (source or "").strip().lower()
    return _SOURCE_PRIORITY.get(s, 10)


def _merge_contract_fields(primary: OptionContract, secondary: OptionContract) -> OptionContract:
    """Completa campos None en primary con valores de secondary; no sobrescribe no-None."""
    def pick(a: Any, b: Any) -> Any:
        return a if a is not None else b

    return OptionContract(
        underlying=primary.underlying,
        expiry=primary.expiry if primary.expiry is not None else secondary.expiry,
        strike=primary.strike if primary.strike is not None else secondary.strike,
        option_type=primary.option_type if primary.option_type is not None else secondary.option_type,
        symbol=primary.symbol or secondary.symbol,
        bid=pick(primary.bid, secondary.bid),
        ask=pick(primary.ask, secondary.ask),
        last=pick(primary.last, secondary.last),
        volume=pick(primary.volume, secondary.volume),
        open_interest=pick(primary.open_interest, secondary.open_interest),
        source=primary.source or secondary.source,
        raw=primary.raw if primary.raw is not None else secondary.raw,
    )


def deduplicate_contracts(contracts: list[OptionContract]) -> list[OptionContract]:
    """
    Deduplica por make_contract_key.
    Prioridad: Allaria > Rava > otras.
    Entre duplicados, fusiona campos faltantes sin inventar strike/expiry/tipo.
    """
    if not contracts:
        return []

    buckets: dict[tuple[Any, ...], list[OptionContract]] = {}
    for c in contracts:
        key = make_contract_key(c)
        buckets.setdefault(key, []).append(c)

    out: list[OptionContract] = []
    for key, group in buckets.items():
        ordered = sorted(group, key=lambda x: (_source_rank(x.source), x.symbol or ""))
        merged = ordered[0]
        for other in ordered[1:]:
            merged = _merge_contract_fields(merged, other)
        out.append(merged)

    out.sort(key=lambda x: (x.expiry or "", x.option_type or "", x.strike is None, x.strike or 0.0, x.symbol or ""))
    return out


def build_master_chain(underlying: str, contracts: list[OptionContract]) -> OptionChain:
    """Construye cadena maestra normalizando subyacente y deduplicando contratos."""
    u_norm = normalize_underlying(underlying) or str(underlying).strip().upper()
    print(f"[OPTIONS_CHAIN] build_master_chain underlying_in={underlying!r} underlying_norm={u_norm!r} n_in={len(contracts)}", flush=True)
    deduped = deduplicate_contracts(contracts)
    for c in deduped:
        c.underlying = u_norm
        ot = normalize_option_type(c.option_type)
        if ot is not None:
            c.option_type = ot
    print(f"[OPTIONS_CHAIN] deduplicated n_out={len(deduped)}", flush=True)
    return OptionChain(underlying=u_norm, contracts=deduped)


def summarize_chain(chain: OptionChain) -> dict[str, Any]:
    """Resumen para diagnóstico y APIs futuras."""
    calls = 0
    puts = 0
    expiries_set: set[str] = set()
    strikes_by_expiry_type: dict[str, dict[str, list[float]]] = {}

    for c in chain.contracts:
        ot = normalize_option_type(c.option_type)
        if ot == "CALL":
            calls += 1
        elif ot == "PUT":
            puts += 1

        exp_key = c.expiry if c.expiry else "__null__"
        if c.expiry:
            expiries_set.add(c.expiry)

        if exp_key not in strikes_by_expiry_type:
            strikes_by_expiry_type[exp_key] = {"CALL": [], "PUT": []}
        if c.strike is not None and ot in ("CALL", "PUT"):
            strikes_by_expiry_type[exp_key][ot].append(c.strike)

    for exp_key in strikes_by_expiry_type:
        for side in ("CALL", "PUT"):
            strikes_by_expiry_type[exp_key][side] = sorted(set(strikes_by_expiry_type[exp_key][side]))

    return {
        "underlying": chain.underlying,
        "total_contracts": len(chain.contracts),
        "calls": calls,
        "puts": puts,
        "expiries": sorted(expiries_set),
        "strikes_by_expiry_type": strikes_by_expiry_type,
    }
