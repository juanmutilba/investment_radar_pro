"""
Cadena merge Allaria + Rava (mercado operativo).

Uso:
    python scripts/debug_options_merged_market.py --underlying GGAL
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.options.chain_builder import summarize_chain  # noqa: E402
from services.options.market_merge import build_merged_market_chain  # noqa: E402
from services.options.models import OptionContract  # noqa: E402
from services.options.normalizer import normalize_option_type  # noqa: E402
from services.options.providers.allaria import fetch_allaria_option_contracts  # noqa: E402
from services.options.providers.rava import fetch_rava_option_contracts  # noqa: E402


def _f(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _is_zero_field(v: float | None) -> bool:
    return v is not None and v == 0.0


def _metrics(contracts: list[OptionContract]) -> dict[str, int]:
    n = len(contracts)
    if n == 0:
        return {k: 0 for k in (
            "total", "common_merged", "allaria_only", "rava_only",
            "con_bid", "con_ask", "con_last", "con_volume", "con_open_interest",
            "bid_zero", "ask_zero", "last_zero", "volume_zero",
            "sin_last", "sin_bid_o_ask",
        )}
    src = [c.source or "" for c in contracts]
    return {
        "total": n,
        "common_merged": sum(1 for s in src if s == "merged"),
        "allaria_only": sum(1 for s in src if s == "allaria"),
        "rava_only": sum(1 for s in src if s == "rava_only"),
        "con_bid": sum(1 for c in contracts if c.bid is not None),
        "con_ask": sum(1 for c in contracts if c.ask is not None),
        "con_last": sum(1 for c in contracts if c.last is not None),
        "con_volume": sum(1 for c in contracts if c.volume is not None),
        "con_open_interest": sum(1 for c in contracts if c.open_interest is not None),
        "bid_zero": sum(1 for c in contracts if _is_zero_field(_f(c.bid))),
        "ask_zero": sum(1 for c in contracts if _is_zero_field(_f(c.ask))),
        "last_zero": sum(1 for c in contracts if _is_zero_field(_f(c.last))),
        "volume_zero": sum(1 for c in contracts if _is_zero_field(_f(c.volume))),
        "sin_last": sum(1 for c in contracts if c.last is None),
        "sin_bid_o_ask": sum(1 for c in contracts if c.bid is None or c.ask is None),
    }


def _sort_key(c: OptionContract) -> tuple:
    ot = normalize_option_type(c.option_type) or (c.option_type or "")
    return (c.expiry or "", ot, c.strike if c.strike is not None else -1.0, c.symbol or "")


def main() -> int:
    warnings.simplefilter("default", UserWarning)
    ap = argparse.ArgumentParser(description="Merge mercado Allaria + Rava.")
    ap.add_argument("--underlying", default="GGAL")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    print(f"[MERGED] underlying={args.underlying!r} limit={args.limit}", flush=True)

    ca = fetch_allaria_option_contracts(args.underlying)
    cr = fetch_rava_option_contracts(args.underlying)
    chain = build_merged_market_chain(args.underlying, ca, cr)
    contracts = chain.contracts

    print("\n[MERGED] summarize_chain")
    print(json.dumps(summarize_chain(chain), indent=2, ensure_ascii=False))

    m = _metrics(contracts)
    print("\n[MERGED] metricas")
    for k in (
        "total",
        "common_merged",
        "allaria_only",
        "rava_only",
        "con_bid",
        "con_ask",
        "con_last",
        "con_volume",
        "con_open_interest",
        "bid_zero",
        "ask_zero",
        "last_zero",
        "volume_zero",
        "sin_last",
        "sin_bid_o_ask",
    ):
        print(f"  {k}: {m[k]}")

    rows = sorted(contracts, key=_sort_key)[: args.limit]
    print(f"\n[MERGED] tabla (primeras {len(rows)})")
    print("symbol\texpiry\ttype\tstrike\tbid\task\tlast\tvolume\tsource\tfield_sources")
    for c in rows:
        fs = {}
        if isinstance(c.raw, dict) and "field_sources" in c.raw:
            fs = c.raw["field_sources"]
        print(
            f"{c.symbol}\t{c.expiry or ''}\t{normalize_option_type(c.option_type) or c.option_type or ''}\t"
            f"{c.strike}\t{c.bid}\t{c.ask}\t{c.last}\t{c.volume}\t{c.source}\t{json.dumps(fs, ensure_ascii=False)}"
        )

    print("\n[MERGED] ejemplos field_sources (merged, hasta 5)")
    shown = 0
    for c in contracts:
        if c.source != "merged" or not isinstance(c.raw, dict):
            continue
        fs = c.raw.get("field_sources")
        if not fs:
            continue
        print(f"  {c.symbol}: {json.dumps(fs, ensure_ascii=False)}")
        shown += 1
        if shown >= 5:
            break

    print("\n[MERGED] primeros 20 sin last")
    n = 0
    for c in sorted(contracts, key=_sort_key):
        if c.last is None:
            print(f"  {c.source}\t{c.symbol}\texp={c.expiry!r}\tk={c.strike}")
            n += 1
            if n >= 20:
                break

    print("\n[MERGED] primeros 20 sin bid o sin ask")
    n = 0
    for c in sorted(contracts, key=_sort_key):
        if c.bid is None or c.ask is None:
            print(f"  {c.source}\t{c.symbol}\tbid={c.bid}\task={c.ask}")
            n += 1
            if n >= 20:
                break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
