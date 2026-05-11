"""
Prueba get_options_chain_with_spot (cadena + spot en paralelo en miss de caché).

Uso:
    python scripts/debug_options_chain_with_spot.py --underlying GGAL
    python scripts/debug_options_chain_with_spot.py --underlying GGAL --enrich
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from services.options.options_service import (  # noqa: E402
    clear_options_chain_cache,
    get_options_chain_with_spot,
)


def main() -> int:
    warnings.simplefilter("default", UserWarning)
    ap = argparse.ArgumentParser(description="Debug get_options_chain_with_spot.")
    ap.add_argument("--underlying", default="GGAL")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--enrich", action="store_true", dest="enrich")
    g.add_argument("--no-enrich", action="store_false", dest="enrich")
    ap.set_defaults(enrich=False)
    args = ap.parse_args()

    clear_options_chain_cache()
    print(
        f"[DEBUG_CHAIN_SPOT] underlying={args.underlying!r} enrich_sources={args.enrich} "
        "(cache cleared; expect miss + parallel on 1st call)",
        flush=True,
    )

    t0 = time.perf_counter()
    chain, info = get_options_chain_with_spot(args.underlying, enrich_sources=args.enrich)
    wall_ms = (time.perf_counter() - t0) * 1000.0

    print("", flush=True)
    print("[DEBUG_CHAIN_SPOT] result", flush=True)
    print(f"  wall_ms={wall_ms:.1f}", flush=True)
    print(f"  total_contracts={len(chain.contracts)}", flush=True)
    print(f"  spot={info.get('spot')!r}", flush=True)
    print(f"  spot_source={info.get('spot_source')!r}", flush=True)
    print(f"  spot_symbol={info.get('spot_symbol')!r}", flush=True)
    print("", flush=True)
    print("[DEBUG_CHAIN_SPOT] grep server logs for [OPTIONS_CACHE] hit/miss and [OPTIONS_TIMING] parallel_*", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
