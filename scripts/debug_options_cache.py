"""
Prueba la caché TTL de get_options_chain (3 llamadas + sleep).

Uso:
    python scripts/debug_options_cache.py --underlying GGAL
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
    OPTIONS_CHAIN_CACHE_TTL_SECONDS,
    clear_options_chain_cache,
    get_options_chain,
)


def main() -> int:
    warnings.simplefilter("default", UserWarning)
    ap = argparse.ArgumentParser(description="Debug TTL cache options chain.")
    ap.add_argument("--underlying", default="GGAL")
    args = ap.parse_args()
    u = args.underlying
    enrich = False

    print(
        f"[DEBUG_OPTIONS_CACHE] underlying={u!r} enrich_sources={enrich} "
        f"TTL={OPTIONS_CHAIN_CACHE_TTL_SECONDS}s",
        flush=True,
    )
    clear_options_chain_cache()
    print("[DEBUG_OPTIONS_CACHE] cache cleared", flush=True)

    def run(label: str) -> tuple[float, int]:
        t0 = time.perf_counter()
        chain = get_options_chain(u, enrich_sources=enrich)
        ms = (time.perf_counter() - t0) * 1000.0
        print(f"[DEBUG_OPTIONS_CACHE] {label} wall_ms={ms:.1f} contracts={len(chain.contracts)}", flush=True)
        return ms, len(chain.contracts)

    ms1, n1 = run("1st_call (expect miss)")
    ms2, n2 = run("2nd_call (expect hit)")
    sleep_s = OPTIONS_CHAIN_CACHE_TTL_SECONDS + 1.0
    print(f"[DEBUG_OPTIONS_CACHE] sleep {sleep_s:.1f}s", flush=True)
    time.sleep(sleep_s)
    ms3, n3 = run("3rd_call (expect miss after TTL)")

    print("", flush=True)
    print("[DEBUG_OPTIONS_CACHE] summary", flush=True)
    print(f"  1st_ms={ms1:.1f} contracts={n1}", flush=True)
    print(f"  2nd_ms={ms2:.1f} contracts={n2}", flush=True)
    print(f"  3rd_ms={ms3:.1f} contracts={n3}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
