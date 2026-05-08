"""
Comparar Allaria vs Rava en el modelo OptionContract (misma clave de deduplicación).

Uso:
    python scripts/debug_compare_options_sources.py --underlying GGAL
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.options.chain_builder import build_master_chain, summarize_chain  # noqa: E402
from services.options.models import OptionContract  # noqa: E402
from services.options.normalizer import make_contract_key, normalize_option_type  # noqa: E402
from services.options.providers.allaria import fetch_allaria_option_contracts  # noqa: E402
from services.options.providers.rava import fetch_rava_option_contracts  # noqa: E402
from services.options.strike_scale import compare_scaled_strikes  # noqa: E402


def _contract_key_set(contracts: list[OptionContract]) -> set[tuple[Any, ...]]:
    return {make_contract_key(c) for c in contracts}


def _expiries_from_keys(keys: set[tuple[Any, ...]]) -> set[str]:
    out: set[str] = set()
    for k in keys:
        if len(k) < 2:
            continue
        exp = k[1]
        if exp is not None and str(exp).strip():
            out.add(str(exp).strip())
    return out


def _strikes_by_expiry_type(contracts: list[OptionContract]) -> dict[tuple[str | None, str | None], set[float]]:
    m: dict[tuple[str | None, str | None], set[float]] = defaultdict(set)
    for c in contracts:
        exp = c.expiry
        ot = normalize_option_type(c.option_type) or c.option_type
        if c.strike is not None:
            m[(exp, ot)].add(float(c.strike))
    return m


def _fmt_contract_short(c: OptionContract) -> str:
    return (
        f"{c.symbol} u={c.underlying} exp={c.expiry!r} ot={c.option_type!r} k={c.strike} "
        f"bid={c.bid} ask={c.ask} last={c.last}"
    )


def main() -> int:
    warnings.simplefilter("default", UserWarning)
    ap = argparse.ArgumentParser(description="Comparar fuentes Allaria vs Rava (OptionContract).")
    ap.add_argument("--underlying", default="GGAL")
    args = ap.parse_args()

    print(f"[COMPARE] underlying_param={args.underlying!r}", flush=True)

    ca = fetch_allaria_option_contracts(args.underlying)
    cr = fetch_rava_option_contracts(args.underlying)

    chain_a = build_master_chain(args.underlying, ca)
    chain_r = build_master_chain(args.underlying, cr)

    sa = summarize_chain(chain_a)
    sr = summarize_chain(chain_r)

    print("\n[COMPARE] 1) Resumen Allaria (master chain)")
    print(json.dumps(sa, indent=2, ensure_ascii=False))

    print("\n[COMPARE] 2) Resumen Rava (master chain)")
    print(json.dumps(sr, indent=2, ensure_ascii=False))

    keys_a = _contract_key_set(chain_a.contracts)
    keys_r = _contract_key_set(chain_r.contracts)

    only_a = keys_a - keys_r
    only_r = keys_r - keys_a
    common_keys = keys_a & keys_r

    print(
        f"\n[COMPARE] claves: common_keys={len(common_keys)} "
        f"allaria_only={len(only_a)} rava_only={len(only_r)}"
    )
    print(f"[COMPARE] 3) Claves solo en Allaria: {len(only_a)}")
    print(f"[COMPARE] 4) Claves solo en Rava: {len(only_r)}")

    exp_a = _expiries_from_keys(keys_a)
    exp_r = _expiries_from_keys(keys_r)
    print(f"\n[COMPARE] 5) Vencimientos solo en Allaria: {sorted(exp_a - exp_r)[:40]}")
    print(f"[COMPARE]    Vencimientos solo en Rava: {sorted(exp_r - exp_a)[:40]}")

    strikes_a = _strikes_by_expiry_type(chain_a.contracts)
    strikes_r = _strikes_by_expiry_type(chain_r.contracts)

    print("\n[COMPARE] 6) Strikes en Allaria ausentes en Rava (por expiry + tipo):")
    shown = 0
    for key, strikes in sorted(strikes_a.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        exp, ot = key
        sr_set = strikes_r.get(key, set())
        missing = sorted(strikes - sr_set)
        if missing:
            print(f"    exp={exp!r} ot={ot!r} n_missing={len(missing)} sample={missing[:15]}")
            shown += 1
            if shown >= 25:
                print("    ... (truncado)")
                break

    only_a_keys = only_a
    missing_contracts: list[OptionContract] = []
    for c in chain_a.contracts:
        if make_contract_key(c) in only_a_keys:
            missing_contracts.append(c)
    missing_contracts.sort(key=lambda x: (x.expiry or "", x.option_type or "", x.strike or 0.0, x.symbol or ""))

    print(f"\n[COMPARE] 7) Primeros 30 contratos Allaria no en Rava (por clave):")
    for c in missing_contracts[:30]:
        print(f"    {_fmt_contract_short(c)}")

    print("\n[COMPARE] 8) Diagnóstico de escala de strikes Rava vs Allaria (solo diagnóstico, sin aplicar)")
    tol_scale = 0.01
    scale_keys = sorted(
        set(strikes_a.keys()) | set(strikes_r.keys()),
        key=lambda k: (k[0] or "", k[1] or ""),
    )
    scale_rows = 0
    for exp, ot in scale_keys:
        ref_list = sorted(strikes_a.get((exp, ot), set()))
        cand_list = sorted(strikes_r.get((exp, ot), set()))
        if not ref_list or not cand_list:
            continue
        if scale_rows >= 50:
            print("    ... (truncado: más de 50 filas expiry×tipo con ambos lados)")
            break
        diag = compare_scaled_strikes(ref_list, cand_list, tolerance=tol_scale, log=True)
        scale_rows += 1
        print(
            f"    exp={exp!r} ot={ot!r} | ref_n={diag['reference_count']} cand_n={diag['candidate_count']} | "
            f"matches_1={diag['matches_reference_covered_factor_1']} -> "
            f"after={diag['matches_reference_covered_after']} "
            f"(inferred_factor={diag['inferred_factor']!r}, effective={diag['effective_factor_applied']})"
        )
        print(f"        scores_by_factor={diag['scores_by_factor']}")
        ex = diag.get("examples_scaled") or []
        if ex:
            parts = [f"{e['candidate']}->{e['scaled']}" for e in ex]
            print(f"        ejemplos: {', '.join(parts)}")

    na_inc = sum(1 for c in chain_a.contracts if not c.expiry or c.strike is None or not normalize_option_type(c.option_type))
    nr_inc = sum(1 for c in chain_r.contracts if not c.expiry or c.strike is None or not normalize_option_type(c.option_type))
    if na_inc or nr_inc:
        print(f"\n[COMPARE] WARN incompletos: Allaria={na_inc} Rava={nr_inc}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
