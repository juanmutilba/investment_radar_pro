#!/usr/bin/env python3
"""
Auditoría v2 de trades del bot (paper + testnet): estadísticas, equity, score, indicadores, combos.

Uso (desde la raíz del repo):
  python scripts/analyze_bot_trades.py

Opciones:
  --skip-network   No descarga OHLCV (indicadores vacíos; útil en CI sin red).
  --timeframe 30m  Timeframe para reconstruir indicadores (default 30m).
  --output DIR     Carpeta de salida (default data/trade_analysis/).
  --max-trades N   Sólo los N trades más recientes (por exit_time), para pruebas rápidas.
  --symbols LIST  Filtrar símbolos separados por coma (ej. BTC/USDT,ETH/USDT).
  --ohlcv-timeout-ms MS  Timeout ccxt por request (default 30000).
  --ohlcv-retries N     Reintentos por página OHLCV (default 3).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.crypto.bot_trade_analyzer_v2 import (  # noqa: E402
    print_executive_summary,
    print_indicator_context_footer,
    run_bot_trade_analysis_v2,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Análisis histórico de trades bot (paper + testnet).")
    ap.add_argument(
        "--skip-network",
        action="store_true",
        help="Omitir descarga de velas (sin indicadores ni combos basados en OHLCV).",
    )
    ap.add_argument("--timeframe", default="30m", help="Timeframe para reconstrucción de indicadores.")
    ap.add_argument("--output", type=Path, default=None, help="Directorio de salida (default data/trade_analysis/).")
    ap.add_argument(
        "--sources",
        default="testnet,paper",
        help="Fuentes separadas por coma: testnet,paper (default ambas).",
    )
    ap.add_argument(
        "--max-trades",
        type=int,
        default=None,
        help="Limitar a los N trades más recientes (orden por exit_time).",
    )
    ap.add_argument(
        "--symbols",
        default=None,
        help="Filtrar por símbolo, separados por coma (ej. BTC/USDT,ETH/USDT).",
    )
    ap.add_argument(
        "--ohlcv-timeout-ms",
        type=int,
        default=30_000,
        help="Timeout por request ccxt al bajar OHLCV (milisegundos).",
    )
    ap.add_argument(
        "--ohlcv-retries",
        type=int,
        default=3,
        help="Reintentos por página al fallar timeout/red.",
    )
    args = ap.parse_args()
    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    sym_list = [x.strip() for x in str(args.symbols or "").split(",") if x.strip()] or None
    out = run_bot_trade_analysis_v2(
        sources=sources,
        default_timeframe=str(args.timeframe).strip() or "30m",
        output_dir=args.output,
        skip_network=bool(args.skip_network),
        max_trades=args.max_trades,
        symbols=sym_list,
        ohlcv_timeout_ms=max(1000, int(args.ohlcv_timeout_ms)),
        ohlcv_max_retries=max(1, int(args.ohlcv_retries)),
    )
    print_executive_summary(out)
    print_indicator_context_footer(out)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
