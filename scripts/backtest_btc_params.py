#!/usr/bin/env python3
"""
Backtest de parametros SL/TP/trailing BTC + auditoria opcional de trades reales.

Uso:
    python scripts/backtest_btc_params.py
    python scripts/backtest_btc_params.py --days 45 --min-trades 10 --audit
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.crypto.btc_param_backtest import run_btc_param_backtest  # noqa: E402
from services.crypto.bot_trade_audit import audit_bot_trades  # noqa: E402


def _print_table(title: str, rows: list[dict], columns: list[tuple[str, str, int]]) -> None:
    print()
    print(title)
    print("-" * 100)
    hdr = " ".join(h.ljust(w) for _, h, w in columns)
    print(hdr)
    print("-" * 100)
    for row in rows:
        parts = []
        for key, _, w in columns:
            val = row.get(key)
            if isinstance(val, float):
                s = f"{val:.3f}" if abs(val) < 100 else f"{val:.1f}"
            else:
                s = str(val) if val is not None else "-"
            parts.append(s[:w].ljust(w))
        print(" ".join(parts))


def _print_audit_summary(audit: dict) -> None:
    print()
    print("=" * 72)
    print("AUDITORIA trades reales (testnet + paper)")
    print("=" * 72)
    print(f"Trades con path OK: {audit.get('trades_count')}")
    print(f"Win rate:         {audit.get('win_rate_pct')}%")
    print(f"Avg PnL:          {audit.get('avg_pnl_pct')}%")
    print(f"Stop loss:        {audit.get('stop_loss_count')}")
    print(f"Take profit:      {audit.get('take_profit_count')}")
    print(f"Trailing stop:    {audit.get('trailing_stop_count')}")
    diag = audit.get("diagnosis") or {}
    print(f"Diagnostico:      {diag.get('verdict')}")
    print(f"  MFE promedio:   {diag.get('avg_mfe_pct')}%")
    print(f"  Salida mala?:   {diag.get('bad_exit_signal')} ({diag.get('bad_exit_count')} casos)")
    print(f"  Entrada mala?:  {diag.get('bad_entry_signal')}")
    print(f"  Trail premat?:  {diag.get('premature_trailing_signal')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest parametros BTC + auditoria")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--min-trades", type=int, default=10)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--audit", action="store_true", help="Incluir auditoria de trades reales")
    ap.add_argument("--audit-symbol", default=None, help="Filtrar auditoria a un simbolo (ej. BTC/USDT)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.audit:
        try:
            audit = audit_bot_trades(
                sources=["testnet", "paper"],
                candle_timeframe="30m",
                filter_symbol=args.audit_symbol,
            )
            _print_audit_summary(audit)
        except Exception as e:
            print(f"Auditoria fallo: {type(e).__name__}: {e}", file=sys.stderr)

    print()
    print("=" * 72)
    print("BACKTEST parametros BTC (tendencias alcistas EMA)")
    print("=" * 72)

    try:
        result = run_btc_param_backtest(
            days=args.days,
            symbol=args.symbol,
            min_trades=args.min_trades,
            max_workers=args.workers,
        )
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"Combinaciones evaluadas: {result.get('combinations_total')}")
    print(f"Elegibles (>={args.min_trades} trades): {result.get('combinations_eligible')}")
    for tf, n in (result.get("entries_per_timeframe") or {}).items():
        print(f"  Entradas alcistas {tf}: {n}")

    _print_table(
        "Top 20 combinaciones (orden: profit_factor, expectancy, win_rate)",
        result.get("top_20") or [],
        [
            ("timeframe", "TF", 4),
            ("take_profit_pct", "TP", 5),
            ("stop_loss_pct", "SL", 5),
            ("trailing_stop_pct", "Tr", 5),
            ("trailing_activation_pct", "Act", 5),
            ("trades", "N", 4),
            ("profit_factor", "PF", 6),
            ("expectancy", "Exp", 7),
            ("win_rate_pct", "WR", 6),
            ("avg_net_pnl_pct", "Avg", 7),
        ],
    )

    print()
    print("Mejor por timeframe")
    print("-" * 72)
    for tf, row in (result.get("timeframe_best") or {}).items():
        print(
            f"  {tf}: TP={row.get('take_profit_pct')} SL={row.get('stop_loss_pct')} "
            f"trail={row.get('trailing_stop_pct')} act={row.get('trailing_activation_pct')} "
            f"PF={row.get('profit_factor')} exp={row.get('expectancy')}% n={row.get('trades')}"
        )

    print()
    print("Recomendaciones testnet (no aplicadas al bot)")
    print("-" * 72)
    for line in result.get("recommendations_testnet") or []:
        print(f"  - {line}")

    if args.json:
        print()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
