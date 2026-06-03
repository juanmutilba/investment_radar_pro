"""
Backtest de parámetros SL/TP/trailing sobre entradas de tendencia alcista BTC (EMA20/50).
Solo diagnóstico; no modifica bot_runner ni ejecución real.
"""
from __future__ import annotations

import itertools
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from statistics import median
from typing import Any

from services.crypto.btc_trend_backtest import (
    TrendRecord,
    _build_indicator_matrix,
    _extract_trends,
    fetch_btc_ohlcv_paginated,
)

_LOG_PREFIX = "[BTC_PARAM_BACKTEST]"

DEFAULT_FEE_ENTRY_PCT = 0.1
DEFAULT_FEE_EXIT_PCT = 0.1
DEFAULT_SLIPPAGE_PCT = 0.03
DEFAULT_MIN_TRADES = 10


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


@dataclass(frozen=True)
class ParamCombo:
    timeframe: str
    take_profit_pct: float
    stop_loss_pct: float
    trailing_stop_pct: float | None
    trailing_activation_pct: float

    def key(self) -> str:
        tr = "none" if self.trailing_stop_pct is None else f"{self.trailing_stop_pct:g}"
        return (
            f"tf={self.timeframe}|tp={self.take_profit_pct:g}|sl={self.stop_loss_pct:g}|"
            f"trail={tr}|act={self.trailing_activation_pct:g}"
        )


def _simulate_long_trade(
    candles: list[list[float]],
    entry_idx: int,
    last_idx: int,
    *,
    entry_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_stop_pct: float | None,
    trailing_activation_pct: float,
    fee_entry_pct: float,
    fee_exit_pct: float,
    slippage_pct: float,
) -> dict[str, Any]:
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in candles]

    sl_px = entry_price * (1.0 - stop_loss_pct / 100.0)
    tp_px = entry_price * (1.0 + take_profit_pct / 100.0)
    highest = entry_price
    trailing_on = False
    exit_reason = "segment_end"
    exit_price = closes[last_idx]
    exit_idx = last_idx
    cost_side = fee_entry_pct + fee_exit_pct + 2.0 * slippage_pct

    for i in range(entry_idx + 1, last_idx + 1):
        h, l = highs[i], lows[i]
        if h > highest:
            highest = h
        fav_pct = (highest - entry_price) / entry_price * 100.0
        if trailing_stop_pct is not None and fav_pct + 1e-12 >= trailing_activation_pct:
            trailing_on = True

        hit_sl = l <= sl_px + 1e-12
        hit_tp = h >= tp_px - 1e-12

        if hit_sl and hit_tp:
            exit_reason = "stop_loss"
            exit_price = sl_px
            exit_idx = i
            break
        if hit_sl:
            exit_reason = "stop_loss"
            exit_price = sl_px
            exit_idx = i
            break
        if hit_tp:
            exit_reason = "take_profit"
            exit_price = tp_px
            exit_idx = i
            break
        if trailing_on and trailing_stop_pct is not None:
            trail_px = highest * (1.0 - trailing_stop_pct / 100.0)
            if l <= trail_px + 1e-12:
                exit_reason = "trailing_stop"
                exit_price = trail_px
                exit_idx = i
                break

    gross_pct = (exit_price - entry_price) / entry_price * 100.0
    net_pct = gross_pct - cost_side
    return {
        "exit_reason": exit_reason,
        "exit_idx": exit_idx,
        "gross_pnl_pct": gross_pct,
        "net_pnl_pct": net_pct,
        "duration_bars": exit_idx - entry_idx,
    }


def _metrics_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "win_rate_pct": None,
            "avg_net_pnl_pct": None,
            "median_net_pnl_pct": None,
            "expectancy": None,
            "profit_factor": None,
            "max_drawdown_pct_approx": None,
            "avg_duration_bars": None,
            "stop_loss_count": 0,
            "take_profit_count": 0,
            "trailing_stop_count": 0,
            "segment_end_count": 0,
        }
    nets = [float(t["net_pnl_pct"]) for t in trades]
    wins = [x for x in nets if x > 1e-9]
    losses = [x for x in nets if x < -1e-9]
    win_rate = len(wins) / len(nets) * 100.0
    avg_net = sum(nets) / len(nets)
    med_net = median(nets)
    expectancy = avg_net
    sum_win = sum(wins) if wins else 0.0
    sum_loss = abs(sum(losses)) if losses else 0.0
    pf = (sum_win / sum_loss) if sum_loss > 1e-9 else None

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in nets:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    reasons = [str(t.get("exit_reason") or "") for t in trades]
    return {
        "trades": len(trades),
        "win_rate_pct": round(win_rate, 2),
        "avg_net_pnl_pct": round(avg_net, 4),
        "median_net_pnl_pct": round(med_net, 4),
        "expectancy": round(expectancy, 4),
        "profit_factor": round(pf, 4) if pf is not None else None,
        "max_drawdown_pct_approx": round(max_dd, 4),
        "avg_duration_bars": round(sum(t["duration_bars"] for t in trades) / len(trades), 2),
        "stop_loss_count": sum(1 for r in reasons if r == "stop_loss"),
        "take_profit_count": sum(1 for r in reasons if r == "take_profit"),
        "trailing_stop_count": sum(1 for r in reasons if r == "trailing_stop"),
        "segment_end_count": sum(1 for r in reasons if r == "segment_end"),
    }


def _bullish_entries(candles: list[list[float]], trends: list[TrendRecord]) -> list[tuple[int, int, float]]:
    """(entry_idx, last_idx, entry_price) por tendencia alcista."""
    out: list[tuple[int, int, float]] = []
    for t in trends:
        if t.direction != "up":
            continue
        out.append((t.start_idx, t.end_idx, t.start_price))
    return out


def _evaluate_combo(
    combo: ParamCombo,
    candles: list[list[float]],
    entries: list[tuple[int, int, float]],
    *,
    fee_entry_pct: float,
    fee_exit_pct: float,
    slippage_pct: float,
) -> dict[str, Any]:
    sims: list[dict[str, Any]] = []
    for entry_idx, last_idx, entry_price in entries:
        if entry_idx >= last_idx:
            continue
        sims.append(
            _simulate_long_trade(
                candles,
                entry_idx,
                last_idx,
                entry_price=entry_price,
                stop_loss_pct=combo.stop_loss_pct,
                take_profit_pct=combo.take_profit_pct,
                trailing_stop_pct=combo.trailing_stop_pct,
                trailing_activation_pct=combo.trailing_activation_pct,
                fee_entry_pct=fee_entry_pct,
                fee_exit_pct=fee_exit_pct,
                slippage_pct=slippage_pct,
            )
        )
    metrics = _metrics_from_trades(sims)
    row = {
        "params_key": combo.key(),
        "timeframe": combo.timeframe,
        "take_profit_pct": combo.take_profit_pct,
        "stop_loss_pct": combo.stop_loss_pct,
        "trailing_stop_pct": combo.trailing_stop_pct,
        "trailing_activation_pct": combo.trailing_activation_pct,
        **metrics,
    }
    return row


def run_btc_param_backtest(
    *,
    days: int = 30,
    symbol: str = "BTCUSDT",
    min_trades: int = DEFAULT_MIN_TRADES,
    fee_entry_pct: float = DEFAULT_FEE_ENTRY_PCT,
    fee_exit_pct: float = DEFAULT_FEE_EXIT_PCT,
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
    max_workers: int = 8,
    timeframes: list[str] | None = None,
) -> dict[str, Any]:
    tfs = timeframes or ["30m", "1h"]
    tp_vals = [0.8, 1.0, 1.25, 1.5, 2.0, 2.5]
    sl_vals = [0.5, 0.8, 1.0, 1.25, 1.5]
    trail_vals: list[float | None] = [None, 0.5, 0.8, 1.0, 1.25]
    act_vals = [0.5, 0.8, 1.0, 1.25]

    candles_by_tf: dict[str, list[list[float]]] = {}
    entries_by_tf: dict[str, list[tuple[int, int, float]]] = {}
    for tf in tfs:
        _log(f"descargando {symbol} tf={tf} days={days}")
        candles = fetch_btc_ohlcv_paginated(symbol=symbol, timeframe=tf, days=days)
        regimes, _ = _build_indicator_matrix(candles)
        trends = _extract_trends(candles, regimes, target_pct=2.5)
        entries = _bullish_entries(candles, trends)
        candles_by_tf[tf] = candles
        entries_by_tf[tf] = entries
        _log(f"tf={tf} velas={len(candles)} entradas_alcistas={len(entries)}")

    combos: list[ParamCombo] = []
    for tf in tfs:
        for tp, sl, tr, act in itertools.product(tp_vals, sl_vals, trail_vals, act_vals):
            if tr is None and act != act_vals[0]:
                continue
            combos.append(
                ParamCombo(
                    timeframe=tf,
                    take_profit_pct=float(tp),
                    stop_loss_pct=float(sl),
                    trailing_stop_pct=None if tr is None else float(tr),
                    trailing_activation_pct=float(act),
                )
            )

    _log(f"evaluando {len(combos)} combinaciones (workers={max_workers})")

    def _job(c: ParamCombo) -> dict[str, Any]:
        return _evaluate_combo(
            c,
            candles_by_tf[c.timeframe],
            entries_by_tf[c.timeframe],
            fee_entry_pct=fee_entry_pct,
            fee_exit_pct=fee_exit_pct,
            slippage_pct=slippage_pct,
        )

    rows: list[dict[str, Any]] = []
    workers = max(1, min(int(max_workers), 16))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_job, c) for c in combos]
        for fut in as_completed(futs):
            try:
                rows.append(fut.result())
            except Exception as e:
                _log(f"combo falló: {type(e).__name__}: {e}")

    eligible = [r for r in rows if int(r.get("trades") or 0) >= min_trades]

    def _sort_key(r: dict[str, Any]) -> tuple:
        pf = r.get("profit_factor")
        pf_v = float(pf) if pf is not None else -1.0
        exp = float(r.get("expectancy") or -999.0)
        wr = float(r.get("win_rate_pct") or 0.0)
        return (-pf_v, -exp, -wr)

    ranked = sorted(eligible, key=_sort_key)
    top20 = ranked[:20]

    by_tf: dict[str, list[dict[str, Any]]] = {tf: [] for tf in tfs}
    for r in eligible:
        by_tf[str(r.get("timeframe"))].append(r)
    tf_best: dict[str, Any] = {}
    for tf, lst in by_tf.items():
        if lst:
            tf_best[tf] = sorted(lst, key=_sort_key)[0]

    rec = _recommend_testnet_params(top20, tf_best, min_trades=min_trades)

    return {
        "ok": True,
        "symbol": symbol,
        "days": days,
        "min_trades": min_trades,
        "fee_entry_pct": fee_entry_pct,
        "fee_exit_pct": fee_exit_pct,
        "slippage_pct": slippage_pct,
        "combinations_total": len(combos),
        "combinations_eligible": len(eligible),
        "entries_per_timeframe": {tf: len(entries_by_tf[tf]) for tf in tfs},
        "candles_per_timeframe": {tf: len(candles_by_tf[tf]) for tf in tfs},
        "top_20": top20,
        "timeframe_best": tf_best,
        "all_ranked_count": len(ranked),
        "recommendations_testnet": rec,
    }


def _recommend_testnet_params(
    top20: list[dict[str, Any]],
    tf_best: dict[str, Any],
    *,
    min_trades: int,
) -> list[str]:
    recs: list[str] = []
    if not top20:
        recs.append(f"Sin combinaciones con >= {min_trades} trades; ampliar days o relajar min_trades.")
        return recs
    best = top20[0]
    recs.append(
        f"Mejor combo global: tf={best.get('timeframe')} TP={best.get('take_profit_pct')}% "
        f"SL={best.get('stop_loss_pct')}% trail={best.get('trailing_stop_pct')} "
        f"act={best.get('trailing_activation_pct')}% PF={best.get('profit_factor')} "
        f"expectancy={best.get('expectancy')}% WR={best.get('win_rate_pct')}% (n={best.get('trades')})."
    )
    for tf, row in tf_best.items():
        recs.append(
            f"Mejor en {tf}: TP={row.get('take_profit_pct')}% SL={row.get('stop_loss_pct')}% "
            f"trail={row.get('trailing_stop_pct')} act={row.get('trailing_activation_pct')}% "
            f"PF={row.get('profit_factor')} expectancy={row.get('expectancy')}%."
        )
    if best.get("take_profit_pct") is not None and float(best["take_profit_pct"]) <= 1.5:
        recs.append(
            "TP optimo <= 1.5% sugiere problema de SALIDA (TP/trailing alto) mas que de entrada."
        )
    if best.get("trailing_stop_count", 0) and int(best.get("trades") or 0) > 0:
        tr_ratio = int(best["trailing_stop_count"]) / int(best["trades"])
        if tr_ratio > 0.4:
            recs.append("Muchas salidas por trailing: revisar trailing_activation_pct o subir TP.")
    recs.append("Aplicar solo en testnet tras validar con bot_trade_audit en trades reales.")
    return recs
