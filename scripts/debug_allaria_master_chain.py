"""
Cadena maestra desde Allaria (real) + resumen.

Uso (raíz del repo):
    python scripts/debug_allaria_master_chain.py
    python scripts/debug_allaria_master_chain.py --underlying ALUA
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.options.chain_builder import build_master_chain, summarize_chain  # noqa: E402
from services.options.models import OptionContract  # noqa: E402
from services.options.providers.allaria import fetch_allaria_option_contracts  # noqa: E402
from services.options.normalizer import normalize_option_type  # noqa: E402


def _sort_key(c: OptionContract) -> tuple:
    exp = c.expiry or ""
    ot = normalize_option_type(c.option_type) or (c.option_type or "")
    strike = c.strike if c.strike is not None else float("inf")
    sym = c.symbol or ""
    return (exp, ot, strike, sym)


def main() -> int:
    p = argparse.ArgumentParser(description="Allaria → OptionContract → cadena maestra (diagnóstico).")
    p.add_argument("--underlying", default="GGAL", help="Ticker acción o prefijo opciones (default GGAL)")
    args = p.parse_args()

    warnings.simplefilter("default", UserWarning)

    contracts = fetch_allaria_option_contracts(args.underlying)
    chain = build_master_chain(args.underlying, contracts)
    summary = summarize_chain(chain)

    print("[OPTIONS_ALLARIA] --- summarize_chain (JSON) ---")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    sorted_contracts = sorted(chain.contracts, key=_sort_key)
    print("[OPTIONS_ALLARIA] --- primeros 20 contratos (expiry, tipo, strike, symbol) ---")
    for c in sorted_contracts[:20]:
        print(
            f"  {c.expiry or '—'} | {c.option_type or '—'} | strike={c.strike} | {c.symbol} | "
            f"bid={c.bid} ask={c.ask} last={c.last} vol={c.volume}"
        )

    n_no_exp = sum(1 for c in chain.contracts if not c.expiry)
    n_no_strike = sum(1 for c in chain.contracts if c.strike is None)
    n_no_ot = sum(1 for c in chain.contracts if not normalize_option_type(c.option_type))
    print("[OPTIONS_ALLARIA] --- incompletos ---")
    print(f"  sin expiry: {n_no_exp}")
    print(f"  sin strike: {n_no_strike}")
    print(f"  sin option_type normalizable: {n_no_ot}")

    if n_no_exp or n_no_strike or n_no_ot:
        print(
            "[OPTIONS_ALLARIA] WARN: hay contratos con campos incompletos "
            f"(expiry={n_no_exp}, strike={n_no_strike}, tipo={n_no_ot})",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
