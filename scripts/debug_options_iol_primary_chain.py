"""
Construye cadena IOL-primary + enriquecimiento Allaria/Rava (mismo criterio que options_service).

Uso:
    python scripts/debug_options_iol_primary_chain.py --underlying GGAL
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from services.market_data.providers.iol import configure_iol_credentials  # noqa: E402
from services.options.market_merge import (  # noqa: E402
    _index_by_key,
    _prep_contracts_for_keys,
    build_iol_primary_market_chain,
)
from services.options.models import OptionContract  # noqa: E402
from services.options.normalizer import make_contract_key  # noqa: E402
from services.options.providers.allaria import fetch_allaria_option_contracts  # noqa: E402
from services.options.providers.iol import fetch_iol_option_contracts  # noqa: E402
from services.options.providers.rava import fetch_rava_option_contracts  # noqa: E402


def _is_pos(v: object) -> bool:
    if v is None:
        return False
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return x == x and x > 0


def _metrics(rows: list[OptionContract]) -> dict[str, int]:
    if not rows:
        return {k: 0 for k in ("bid", "ask", "last", "volume", "open_interest", "bid_pos", "ask_pos", "last_pos", "vol_pos")}
    return {
        "bid": sum(1 for c in rows if c.bid is not None),
        "ask": sum(1 for c in rows if c.ask is not None),
        "last": sum(1 for c in rows if c.last is not None),
        "volume": sum(1 for c in rows if c.volume is not None),
        "open_interest": sum(1 for c in rows if c.open_interest is not None),
        "bid_pos": sum(1 for c in rows if _is_pos(c.bid)),
        "ask_pos": sum(1 for c in rows if _is_pos(c.ask)),
        "last_pos": sum(1 for c in rows if _is_pos(c.last)),
        "vol_pos": sum(1 for c in rows if _is_pos(c.volume)),
    }


def _source_counter(rows: list[OptionContract], field: str) -> dict[str, int]:
    cnt: Counter[str] = Counter()
    for c in rows:
        raw = c.raw if isinstance(c.raw, dict) else {}
        fs = raw.get("field_sources")
        if isinstance(fs, dict) and isinstance(fs.get(field), str):
            cnt[fs[field]] += 1
        else:
            cnt["?"] += 1
    return dict(cnt)


def _fallback_totals(rows: list[OptionContract]) -> dict[str, int]:
    fb_b = fb_a = fb_l = fb_v = 0
    for c in rows:
        raw = c.raw if isinstance(c.raw, dict) else {}
        fb = raw.get("field_fallbacks")
        if not isinstance(fb, dict):
            continue
        if "bid" in fb:
            fb_b += 1
        if "ask" in fb:
            fb_a += 1
        if "last" in fb:
            fb_l += 1
        if "volume" in fb:
            fb_v += 1
    return {"fallback_bid": fb_b, "fallback_ask": fb_a, "fallback_last": fb_l, "fallback_volume": fb_v}


def main() -> int:
    ap = argparse.ArgumentParser(description="Debug build_iol_primary_market_chain.")
    ap.add_argument("--underlying", default="GGAL")
    args = ap.parse_args()

    u = (os.environ.get("IOL_USERNAME") or "").strip()
    pw = (os.environ.get("IOL_PASSWORD") or "").strip()
    configure_iol_credentials(u, pw)

    und = args.underlying
    ci = fetch_iol_option_contracts(und)
    ca = fetch_allaria_option_contracts(und)
    cr = fetch_rava_option_contracts(und)

    print(f"[DEBUG_IOL_PRIMARY] underlying={und!r} iol={len(ci)} allaria={len(ca)} rava={len(cr)}", flush=True)
    iol_p = _prep_contracts_for_keys(und, ci)
    idx_a = _index_by_key(_prep_contracts_for_keys(und, ca))
    idx_r = _index_by_key(_prep_contracts_for_keys(und, cr))
    matched_a = sum(1 for c in iol_p if make_contract_key(c) in idx_a)
    matched_r = sum(1 for c in iol_p if make_contract_key(c) in idx_r)
    print(f"[DEBUG_IOL_PRIMARY] matched_allaria={matched_a} matched_rava={matched_r}", flush=True)

    chain = build_iol_primary_market_chain(und, ci, ca, cr)
    rows = chain.contracts
    m = _metrics(rows)
    fbt = _fallback_totals(rows)
    print(f"[DEBUG_IOL_PRIMARY] total_iol={len(ci)} total_final={len(rows)}", flush=True)
    print(
        f"[DEBUG_IOL_PRIMARY] con_bid={m['bid']} con_ask={m['ask']} con_last={m['last']} "
        f"con_volume={m['volume']} con_open_interest={m['open_interest']}",
        flush=True,
    )
    print(
        f"[DEBUG_IOL_PRIMARY] con_bid>0={m['bid_pos']} con_ask>0={m['ask_pos']} con_last>0={m['last_pos']} con_volume>0={m['vol_pos']}",
        flush=True,
    )
    print(
        f"[DEBUG_IOL_PRIMARY] fallback_bid={fbt['fallback_bid']} fallback_ask={fbt['fallback_ask']} "
        f"fallback_last={fbt['fallback_last']} fallback_volume={fbt['fallback_volume']}",
        flush=True,
    )
    for fld in ("bid", "ask", "last", "volume", "open_interest"):
        print(f"[DEBUG_IOL_PRIMARY] field_sources.{fld}={_source_counter(rows, fld)!r}", flush=True)

    examples = [c for c in rows if isinstance(c.raw, dict) and c.raw.get("field_fallbacks")]
    print(f"[DEBUG_IOL_PRIMARY] rows_con_field_fallbacks={len(examples)}", flush=True)
    for c in examples[:5]:
        print(f"  symbol={c.symbol!r} fallbacks={c.raw.get('field_fallbacks')!r} bid={c.bid} ask={c.ask} last={c.last} vol={c.volume}", flush=True)

    print("", flush=True)
    print("symbol\texpiry\ttype\tstrike\tbid\task\tlast\tvolume\topen_interest\tsource", flush=True)
    for c in rows[:30]:
        print(
            f"{c.symbol}\t{c.expiry or ''}\t{c.option_type or ''}\t{c.strike}\t{c.bid}\t{c.ask}\t{c.last}\t{c.volume}\t{c.open_interest}\t{c.source}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
