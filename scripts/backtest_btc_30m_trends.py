#!/usr/bin/env python3
"""
Backtest tendencias BTC/USDT 30m (últimos N días, Binance público).

Uso:
    python scripts/backtest_btc_30m_trends.py
    python scripts/backtest_btc_30m_trends.py --days 30 --target 2.5 --min-samples 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.crypto.btc_trend_backtest import run_btc_30m_trend_backtest  # noqa: E402


def _fmt_pct(v: object) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f}%"
    except (TypeError, ValueError):
        return str(v)


def _print_table(title: str, rows: list[dict], columns: list[tuple[str, str, int]]) -> None:
    print()
    print(title)
    print("-" * 72)
    hdr = " ".join(h.ljust(w) for _, h, w in columns)
    print(hdr)
    print("-" * 72)
    for row in rows:
        parts = []
        for key, _, w in columns:
            val = row.get(key)
            if isinstance(val, float):
                s = f"{val:.2f}" if abs(val) < 1000 else f"{val:.1f}"
            else:
                s = str(val) if val is not None else "—"
            parts.append(s[:w].ljust(w))
        print(" ".join(parts))


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest tendencias BTC 30m")
    ap.add_argument("--days", type=int, default=30, help="Días de historia (default 30)")
    ap.add_argument("--target", type=float, default=2.5, help="%% mínimo favorable alcista (default 2.5)")
    ap.add_argument("--symbol", default="BTCUSDT", help="Par (default BTCUSDT)")
    ap.add_argument("--min-samples", type=int, default=5, help="Mínimo señales para ranking combos")
    ap.add_argument("--workers", type=int, default=8, help="ThreadPool workers")
    ap.add_argument("--json", action="store_true", help="Volcar JSON completo al final")
    args = ap.parse_args()

    print("=" * 72)
    print("BTC 30m trend backtest (Binance spot público)")
    print("=" * 72)

    try:
        result = run_btc_30m_trend_backtest(
            days=args.days,
            target_pct=args.target,
            symbol=args.symbol,
            min_samples=args.min_samples,
            max_workers=args.workers,
        )
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print()
    print(f"Rango UTC:     {result.get('range_from')} -> {result.get('range_to')}")
    print(f"Velas:         {result.get('candles_count')}")
    print(f"Tendencias up: {result.get('bullish_trends_count')}")
    print(
        f"Alcistas >={args.target}%: {result.get('bullish_success_count')}  "
        f"({_fmt_pct(result.get('bullish_success_rate_pct'))} de alcistas)"
    )
    print(f"Tendencias down: {result.get('bearish_trends_count')}")

    ind_rows = result.get("indicators_at_bull_start") or []
    _print_table(
        "Top indicadores al INICIO de tendencia alcista",
        ind_rows[:12],
        [
            ("indicator", "Indicador", 22),
            ("true_at_bull_start", "N", 4),
            ("within_successful", "OK", 4),
            ("precision_pct", "Prec%", 7),
            ("recall_on_successful_pct", "Rec%", 7),
            ("avg_max_favorable_pct", "AvgFav%", 9),
        ],
    )

    filt_ind = result.get("filter_metrics_individual") or []
    _print_table(
        f"Top filtros individuales (por barra, min_samples={args.min_samples})",
        filt_ind[:12],
        [
            ("name", "Filtro", 28),
            ("total_signals", "N", 5),
            ("precision_pct", "Prec%", 7),
            ("recall_on_successful_pct", "Rec%", 7),
            ("profit_factor_approx", "PF~", 6),
        ],
    )

    combos = result.get("filter_metrics_combinations") or []
    _print_table(
        f"Top combinaciones 2-3 condiciones (min_samples={args.min_samples})",
        combos[:12],
        [
            ("name", "Combo", 36),
            ("total_signals", "N", 5),
            ("precision_pct", "Prec%", 7),
            ("recall_on_successful_pct", "Rec%", 7),
            ("profit_factor_approx", "PF~", 6),
        ],
    )

    print()
    print("Recomendaciones (bot_runner / testnet — no aplicadas automáticamente)")
    print("-" * 72)
    for line in result.get("recommendations_for_bot_runner") or []:
        print(f"  - {line}")

    if args.json:
        print()
        print("JSON completo:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
