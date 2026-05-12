"""
Cobertura bid/ask en la cadena de opciones IOL para un subyacente.

Uso:
    python scripts/debug_iol_bidask_coverage.py --underlying GGAL

Requiere IOL_USERNAME / IOL_PASSWORD.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services.market_data.providers.iol import ensure_iol_credentials_from_env, is_iol_enabled
from services.options.providers.iol import _collect_puntas_lists, fetch_iol_option_contracts


def _puntas_len_from_row(row: object) -> int:
    if not isinstance(row, dict):
        return 0
    return sum(len(pl) for pl in _collect_puntas_lists(row))


def main() -> int:
    p = argparse.ArgumentParser(description="Cobertura bid/ask opciones IOL por subyacente.")
    p.add_argument("--underlying", default="GGAL", help="Subyacente (default: GGAL)")
    args = p.parse_args()
    und = (args.underlying or "").strip() or "GGAL"

    ensure_iol_credentials_from_env()
    if not is_iol_enabled():
        print("[DEBUG_IOL_BIDASK] IOL deshabilitado: faltan credenciales.")
        return 1

    contracts = fetch_iol_option_contracts(und)
    n = len(contracts)

    bid_not_null = sum(1 for c in contracts if c.bid is not None)
    ask_not_null = sum(1 for c in contracts if c.ask is not None)
    bid_gt0 = sum(1 for c in contracts if c.bid is not None and c.bid > 0)
    ask_gt0 = sum(1 for c in contracts if c.ask is not None and c.ask > 0)
    both_gt0 = sum(1 for c in contracts if (c.bid or 0) > 0 and (c.ask or 0) > 0)

    puntas_empty_count = 0
    puntas_with_data_count = 0
    empty_syms: list[str] = []
    puntas_but_bad: list[str] = []
    good: list[tuple[str, float, float]] = []

    for c in contracts:
        raw = c.raw if isinstance(c.raw, dict) else {}
        plen = _puntas_len_from_row(raw)
        if plen == 0:
            puntas_empty_count += 1
            if len(empty_syms) < 30:
                empty_syms.append(c.symbol)
        else:
            puntas_with_data_count += 1

        bad_parse = (
            plen > 0
            and (
                c.bid is None
                or c.ask is None
                or c.bid == 0
                or c.ask == 0
            )
        )
        if bad_parse and len(puntas_but_bad) < 30:
            puntas_but_bad.append(c.symbol)

        if (c.bid or 0) > 0 and (c.ask or 0) > 0:
            good.append((c.symbol, float(c.bid or 0), float(c.ask or 0)))

    good.sort(key=lambda t: t[1] + t[2], reverse=True)
    top30 = good[:30]

    print("\n[DEBUG_IOL_BIDASK] cobertura underlying=%r" % (und,))
    print("  total=%s" % n)
    print("  bid_not_null=%s" % bid_not_null)
    print("  ask_not_null=%s" % ask_not_null)
    print("  bid_gt_zero=%s" % bid_gt0)
    print("  ask_gt_zero=%s" % ask_gt0)
    print("  both_bid_ask_gt_zero=%s" % both_gt0)
    print("  puntas_empty_count=%s" % puntas_empty_count)
    print("  puntas_with_data_count=%s" % puntas_with_data_count)

    print("\n--- primeras 30 especies con puntas vacías (API/cadena) ---")
    for s in empty_syms:
        print(" ", s)

    print("\n--- primeras 30 con puntas pero bid/ask parseado null o 0 ---")
    for s in puntas_but_bad:
        print(" ", s)

    print("\n--- top 30 bid>0 y ask>0 (orden por bid+ask) ---")
    for s, b, a in top30:
        print(" ", s, "bid=", b, "ask=", a)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
