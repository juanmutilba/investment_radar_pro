#!/usr/bin/env python3
"""
Depuración del motor de oportunidades de opciones (sin API).

  python scripts/debug_options_opportunities.py --underlying GGAL --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.options.opportunity_scanner import scan_options_opportunities  # noqa: E402


def _trim_list(rows: list, limit: int) -> list:
    return rows[:limit] if limit > 0 else rows


def _rr_str(m: dict) -> str:
    rr = m.get("risk_reward")
    if rr is None:
        return "-"
    return f"{rr:.6g}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Oportunidades de opciones (covered calls, bull spreads).")
    ap.add_argument("--underlying", default="GGAL", help="Subyacente (ej. GGAL, YPFD, ALUA)")
    ap.add_argument("--limit", type=int, default=10, help="Cuántas filas mostrar por bloque")
    ap.add_argument("--json", action="store_true", help="Volcar JSON completo a stdout")
    args = ap.parse_args()

    out = scan_options_opportunities(args.underlying.strip())

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return

    lim = max(0, args.limit)
    print("=== options opportunities ===")
    print(f"underlying (chain): {out['underlying']}")
    print(f"spot: {out['spot']}")
    print(f"generated_at: {out['generated_at']}")
    print(f"quality_flags: {out['quality_flags']}")
    print()

    cc = _trim_list(out["covered_calls"], lim)
    print(f"--- covered calls (top {len(cc)} de {len(out['covered_calls'])}) - tna_premium desc ---")
    for i, row in enumerate(cc, 1):
        m = row["metrics"]
        leg = row["legs"][0]
        print(
            f"  {i}. sym={leg.get('symbol')} expiry={row['expiry']} strike={m['strike']} "
            f"bid={m['premium']} vol={m['volume']} "
            f"prem_yield={m['premium_yield']:.6g} tna_premium={m['tna_premium']:.4f} "
            f"upside_pct={m['upside_pct']:.6g} assigned_tna={m.get('assigned_tna')}"
        )
    print()

    bf = _trim_list(out["bull_spreads_free"], lim)
    print(f"--- bull spreads credito / costo cero (top {len(bf)} de {len(out['bull_spreads_free'])}) ---")
    for i, row in enumerate(bf, 1):
        m = row["metrics"]
        lb = row["legs"][0]
        ls = row["legs"][1]
        print(
            f"  {i}. buy={lb.get('symbol')} sell={ls.get('symbol')} expiry={row['expiry']} "
            f"K {lb.get('strike')}/{ls.get('strike')} debit={m['debit']:.4f} credit={m['credit']:.4f} "
            f"max_profit={m['max_profit']:.4f} max_loss={m['max_loss']:.4f} RR={_rr_str(m)} "
            f"vol {m['buy_volume']}/{m['sell_volume']} notes={row.get('notes')}"
        )
    print()

    br = _trim_list(out["bull_spreads_best_rr"], lim)
    print(
        f"--- bull spreads mejor RR (solo max_loss>0; top {len(br)} de {len(out['bull_spreads_best_rr'])}) ---"
    )
    for i, row in enumerate(br, 1):
        m = row["metrics"]
        lb = row["legs"][0]
        ls = row["legs"][1]
        print(
            f"  {i}. buy={lb.get('symbol')} sell={ls.get('symbol')} expiry={row['expiry']} "
            f"K {lb.get('strike')}/{ls.get('strike')} debit={m['debit']:.4f} credit={m['credit']:.4f} "
            f"max_profit={m['max_profit']:.4f} max_loss={m['max_loss']:.4f} RR={_rr_str(m)} "
            f"vol {m['buy_volume']}/{m['sell_volume']} notes={row.get('notes')}"
        )


if __name__ == "__main__":
    main()
