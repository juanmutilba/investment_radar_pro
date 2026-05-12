"""
Muestra bid/ask mergeados y bidask_source_mode (IOL primario + fallback Allaria/Rava).

Uso:
    python scripts/debug_bidask_sources.py --underlying GGAL
    python scripts/debug_bidask_sources.py --underlying GGAL --no-enrich

Por defecto enrich_sources=true (hace falta para fallbacks).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from services.options.options_service import clear_options_chain_cache, get_options_chain  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Bid/ask y bidask_source_mode post-merge.")
    ap.add_argument("--underlying", default="GGAL")
    ap.add_argument("--limit", type=int, default=0, help="0 = todos")
    ap.add_argument(
        "--no-enrich",
        action="store_true",
        help="Sin Allaria/Rava (solo IOL; los modos serán iol_live o none salvo datos IOL).",
    )
    args = ap.parse_args()
    und = (args.underlying or "").strip() or "GGAL"
    enrich = not args.no_enrich

    clear_options_chain_cache()
    chain = get_options_chain(und, enrich_sources=enrich)
    contracts = chain.contracts

    n_iol = n_all = n_rav = n_none = 0
    rows: list[tuple[str, object, object, str, object]] = []

    for c in contracts:
        raw = c.raw if isinstance(c.raw, dict) else {}
        mode = raw.get("bidask_source_mode")
        if mode == "iol_live":
            n_iol += 1
        elif mode == "allaria_fallback":
            n_all += 1
        elif mode == "rava_fallback":
            n_rav += 1
        else:
            n_none += 1
        fs = raw.get("field_sources")
        rows.append((c.symbol or "", c.bid, c.ask, str(mode or ""), fs))

    rows.sort(key=lambda t: t[0])
    lim = args.limit or len(rows)
    lim = min(lim, len(rows))

    print(f"[DEBUG_BIDASK_SOURCES] underlying={und!r} enrich_sources={enrich} total={len(rows)}")
    print("conteos bidask_source_mode:")
    print(f"  iol_live={n_iol}")
    print(f"  allaria_fallback={n_all}")
    print(f"  rava_fallback={n_rav}")
    print(f"  none={n_none}")
    print()
    print("symbol\tbid\task\tbidask_source_mode\tfield_sources")
    for sym, bid, ask, mode, fs in rows[:lim]:
        fs_s = json.dumps(fs, ensure_ascii=False, separators=(",", ":")) if fs is not None else ""
        print(f"{sym}\t{bid}\t{ask}\t{mode}\t{fs_s}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
