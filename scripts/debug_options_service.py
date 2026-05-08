"""
Depuración de get_options_chain (servicio interno de opciones).

Uso:
    python scripts/debug_options_service.py --underlying GGAL
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.options.chain_builder import summarize_chain  # noqa: E402
from services.options.models import OptionContract  # noqa: E402
from services.options.normalizer import normalize_option_type  # noqa: E402
from services.options.options_service import get_options_chain  # noqa: E402


def _metrics(contracts: list[OptionContract]) -> dict[str, int]:
    n = len(contracts)
    if n == 0:
        return {"con_bid": 0, "con_ask": 0, "con_last": 0, "con_volume": 0}
    return {
        "con_bid": sum(1 for c in contracts if c.bid is not None),
        "con_ask": sum(1 for c in contracts if c.ask is not None),
        "con_last": sum(1 for c in contracts if c.last is not None),
        "con_volume": sum(1 for c in contracts if c.volume is not None),
    }


def _sort_key(c: OptionContract) -> tuple:
    ot = normalize_option_type(c.option_type) or (c.option_type or "")
    return (c.expiry or "", ot, c.strike if c.strike is not None else -1.0, c.symbol or "")


def main() -> int:
    warnings.simplefilter("default", UserWarning)
    ap = argparse.ArgumentParser(description="Debug get_options_chain.")
    ap.add_argument("--underlying", default="GGAL")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    print(f"[DEBUG_SERVICE] underlying={args.underlying!r} limit={args.limit}", flush=True)

    chain = get_options_chain(args.underlying)
    contracts = chain.contracts

    print("\n[DEBUG_SERVICE] summarize_chain")
    print(json.dumps(summarize_chain(chain), indent=2, ensure_ascii=False))

    m = _metrics(contracts)
    print("\n[DEBUG_SERVICE] metricas campos")
    for k in ("con_bid", "con_ask", "con_last", "con_volume"):
        print(f"  {k}: {m[k]}")

    rows = sorted(contracts, key=_sort_key)[: args.limit]
    print(f"\n[DEBUG_SERVICE] primeras {len(rows)} filas")
    print("symbol\texpiry\ttype\tstrike\tbid\task\tlast\tvolume\tsource")
    for c in rows:
        ot = normalize_option_type(c.option_type) or (c.option_type or "")
        print(
            f"{c.symbol}\t{c.expiry or ''}\t{ot}\t{c.strike}\t{c.bid}\t{c.ask}\t{c.last}\t{c.volume}\t{c.source}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
