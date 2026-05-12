"""
Depuración de get_options_chain (servicio interno de opciones).

Uso:
    python scripts/debug_options_service.py --underlying GGAL --no-enrich
    python scripts/debug_options_service.py --underlying GGAL --enrich
"""

from __future__ import annotations

import argparse
import json
import time
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

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
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--enrich", action="store_true", dest="enrich", help="Incluir Allaria/Rava (más lento).")
    g.add_argument("--no-enrich", action="store_false", dest="enrich", help="Sin Allaria/Rava (default).")
    ap.set_defaults(enrich=False)
    args = ap.parse_args()

    print(
        f"[DEBUG_SERVICE] underlying={args.underlying!r} limit={args.limit} enrich_sources={args.enrich}",
        flush=True,
    )

    t0 = time.perf_counter()
    chain = get_options_chain(args.underlying, enrich_sources=args.enrich)
    get_options_chain_ms = (time.perf_counter() - t0) * 1000.0
    print(f"[DEBUG_SERVICE] get_options_chain_total_ms={get_options_chain_ms:.1f}", flush=True)
    contracts = chain.contracts

    print("\n[DEBUG_SERVICE] summarize_chain")
    print(json.dumps(summarize_chain(chain), indent=2, ensure_ascii=False))

    m = _metrics(contracts)
    print("\n[DEBUG_SERVICE] metricas campos")
    for k in ("con_bid", "con_ask", "con_last", "con_volume"):
        print(f"  {k}: {m[k]}")

    n_iol = n_all = n_rav = n_none = n_missing = 0
    for c in contracts:
        raw = c.raw if isinstance(c.raw, dict) else {}
        mode = raw.get("bidask_source_mode")
        if mode == "iol_live":
            n_iol += 1
        elif mode == "allaria_fallback":
            n_all += 1
        elif mode == "rava_fallback":
            n_rav += 1
        elif mode == "none":
            n_none += 1
        else:
            n_missing += 1
    print("\n[DEBUG_SERVICE] bidask_source_mode")
    print(f"  iol_live={n_iol} allaria_fallback={n_all} rava_fallback={n_rav} none={n_none} sin_clave={n_missing}")

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
