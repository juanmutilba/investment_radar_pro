"""
Auditoría de trades cerrados (testnet local + paper) con excursión MFE/MAE vía velas Binance públicas.
Solo diagnóstico; no modifica ejecución del bot.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Literal

from services.crypto.btc_trend_backtest import (
    compute_long_excursion_from_candles,
    fetch_ohlcv_for_window,
    timeframe_to_ms,
)
from services.crypto.testnet_strategy_analysis import (
    _load_orders_rows,
    _parse_iso_dt,
    _row_created_at_iso,
)

_LOG_PREFIX = "[BOT_TRADE_AUDIT]"

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_ORDERS_JSON = _DATA_DIR / "crypto_testnet_orders.json"
_PAPER_JSON = _DATA_DIR / "crypto_paper_portfolio.json"

_EPS = 1e-12
SourceKind = Literal["testnet", "paper"]


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _safe_float(x: Any) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _iso_to_ms(value: str | None) -> int | None:
    dt = _parse_iso_dt(value)
    if dt is None:
        return None
    return int(dt.timestamp() * 1000)


def _order_usdt_notional(row: dict[str, Any], qty: float) -> float | None:
    filled = _safe_float(row.get("filled"))
    cost_raw = _safe_float(row.get("cost"))
    if cost_raw is not None and cost_raw > 0:
        if filled is not None and filled > 0 and abs(filled - qty) > 1e-12:
            return cost_raw * (qty / filled)
        return cost_raw
    avg = _safe_float(row.get("average"))
    if avg is not None and avg > 0:
        return avg * qty
    return None


def _load_testnet_closed_trades() -> list[dict[str, Any]]:
    """Ciclos cerrados desde data/crypto_testnet_orders.json (FIFO por símbolo)."""
    rows = _load_orders_rows()
    if not rows:
        return []

    by_sym: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").strip()
        if sym:
            by_sym.setdefault(sym, []).append(row)

    closed: list[dict[str, Any]] = []
    for sym, sym_rows in by_sym.items():
        sym_rows.sort(
            key=lambda r: (_parse_iso_dt(_row_created_at_iso(r)) or datetime.min.replace(tzinfo=timezone.utc),)
        )
        base_inv = 0.0
        cost_inv = 0.0
        cycle_buy_cost = 0.0
        cycle_buy_base = 0.0
        cycle_sell_base = 0.0
        cycle_sell_proceeds = 0.0
        opened_at: str | None = None
        entry_source: str | None = None
        entry_strategy: str | None = None
        entry_setup: str | None = None
        entry_score: float | None = None
        last_sell_row: dict[str, Any] | None = None

        for row in sym_rows:
            side = str(row.get("side") or "").lower().strip()
            filled = _safe_float(row.get("filled"))
            if filled is None or filled <= 0:
                continue
            ts = _row_created_at_iso(row)

            if side == "buy":
                c_usdt = _order_usdt_notional(row, filled)
                if c_usdt is None or c_usdt <= 0:
                    continue
                if base_inv <= _EPS:
                    opened_at = ts
                    cycle_buy_cost = 0.0
                    cycle_buy_base = 0.0
                    cycle_sell_base = 0.0
                    cycle_sell_proceeds = 0.0
                    entry_source = str(row.get("source") or "").strip() or None
                    entry_strategy = str(row.get("strategy_mode") or "").strip() or None
                    entry_setup = str(row.get("setup_type") or "").strip() or None
                    entry_score = _safe_float(row.get("entry_score"))
                cycle_buy_base += filled
                cycle_buy_cost += c_usdt
                base_inv += filled
                cost_inv += c_usdt
            elif side == "sell":
                if base_inv <= _EPS:
                    continue
                sell_qty = min(filled, base_inv)
                proceeds = _order_usdt_notional(row, sell_qty)
                if proceeds is None or proceeds <= 0:
                    continue
                unit_cost = cost_inv / base_inv
                cost_sold = sell_qty * unit_cost
                base_inv -= sell_qty
                cost_inv -= cost_sold
                cycle_sell_base += sell_qty
                cycle_sell_proceeds += proceeds
                last_sell_row = row
                if base_inv <= _EPS:
                    entry_px = cycle_buy_cost / cycle_buy_base if cycle_buy_base > 0 else None
                    exit_px = cycle_sell_proceeds / cycle_sell_base if cycle_sell_base > 0 else None
                    pnl_usdt = cycle_sell_proceeds - cycle_buy_cost
                    pnl_pct = (
                        (pnl_usdt / cycle_buy_cost) * 100.0
                        if cycle_buy_cost > 0 and math.isfinite(pnl_usdt)
                        else None
                    )
                    exit_reason = None
                    if last_sell_row:
                        exit_reason = str(last_sell_row.get("exit_reason") or "").strip() or None
                        if not exit_reason:
                            exit_reason = str(last_sell_row.get("reason") or "").strip() or None
                    sell_source = str(last_sell_row.get("source") or "").strip() if last_sell_row else ""
                    closed.append(
                        {
                            "source_kind": "testnet",
                            "symbol": sym,
                            "entry_time": opened_at,
                            "exit_time": ts,
                            "entry_price": entry_px,
                            "exit_price": exit_px,
                            "exit_reason": exit_reason or "unknown",
                            "pnl_usdt": round(pnl_usdt, 8),
                            "pnl_pct": round(pnl_pct, 6) if pnl_pct is not None else None,
                            "order_source_entry": entry_source,
                            "order_source_exit": sell_source or None,
                            "strategy_mode": entry_strategy,
                            "setup_type": entry_setup,
                            "entry_score": entry_score,
                        }
                    )
                    opened_at = None
                    cycle_buy_cost = 0.0
                    cycle_buy_base = 0.0
                    cycle_sell_base = 0.0
                    cycle_sell_proceeds = 0.0
                    last_sell_row = None
    return closed


def _load_paper_closed_trades() -> list[dict[str, Any]]:
    if not _PAPER_JSON.is_file():
        return []
    try:
        raw = json.loads(_PAPER_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    out: list[dict[str, Any]] = []
    for t in raw.get("trades") or []:
        if not isinstance(t, dict):
            continue
        pnl = _safe_float(t.get("pnl_usdt"))
        if pnl is None:
            continue
        out.append(
            {
                "source_kind": "paper",
                "symbol": str(t.get("symbol") or "").strip(),
                "entry_time": t.get("entry_time"),
                "exit_time": t.get("exit_time"),
                "entry_price": _safe_float(t.get("entry_price")),
                "exit_price": _safe_float(t.get("exit_price")),
                "exit_reason": str(t.get("exit_reason") or "unknown").strip() or "unknown",
                "pnl_usdt": pnl,
                "pnl_pct": _safe_float(t.get("pnl_pct")),
                "order_source_entry": "paper",
                "order_source_exit": "paper",
                "strategy_mode": None,
                "setup_type": None,
                "entry_score": None,
            }
        )
    return out


def _enrich_trade_with_candles(
    trade: dict[str, Any],
    *,
    candle_timeframe: str,
    candle_cache: dict[tuple[str, str], list[list[float]]],
) -> dict[str, Any]:
    sym = str(trade.get("symbol") or "").strip()
    entry_ms = _iso_to_ms(str(trade.get("entry_time") or ""))
    exit_ms = _iso_to_ms(str(trade.get("exit_time") or ""))
    entry_price = _safe_float(trade.get("entry_price"))
    out = dict(trade)
    if not sym or entry_ms is None or exit_ms is None or entry_price is None or entry_price <= 0:
        out["path_error"] = "missing_symbol_or_times_or_entry_price"
        return out

    cache_key = (sym, candle_timeframe)
    if cache_key not in candle_cache:
        try:
            candle_cache[cache_key] = fetch_ohlcv_for_window(
                symbol=sym,
                timeframe=candle_timeframe,
                start_ms=entry_ms,
                end_ms=exit_ms,
            )
        except Exception as e:
            out["path_error"] = f"{type(e).__name__}: {e}"
            return out
    candles = candle_cache[cache_key]
    path = compute_long_excursion_from_candles(candles, entry_ms, exit_ms, entry_price)
    out.update(path)
    tf_ms = timeframe_to_ms(candle_timeframe)
    dur_ms = max(0, exit_ms - entry_ms)
    out["duration_bars_est"] = int(dur_ms / tf_ms) + 1 if tf_ms > 0 else None
    return out


def _diagnose_trades(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [t for t in enriched if t.get("max_favorable_pct") is not None]
    mfes = [float(t["max_favorable_pct"]) for t in valid]
    pnls = [float(t["pnl_pct"]) for t in valid if t.get("pnl_pct") is not None]

    avg_mfe = mean(mfes) if mfes else None
    bad_entry = bool(avg_mfe is not None and avg_mfe < 0.5)

    bad_exit_cases = [
        t
        for t in valid
        if float(t.get("max_favorable_pct") or 0) > 0.8
        and float(t.get("pnl_pct") or 0) <= 0.0
    ]
    bad_exit = len(bad_exit_cases) >= max(2, len(valid) // 4)

    trailing_rows = [
        t
        for t in valid
        if str(t.get("exit_reason") or "").lower() == "trailing_stop"
    ]
    premature_trailing = [
        t
        for t in trailing_rows
        if float(t.get("max_favorable_pct") or 0) < 1.0
        or int(t.get("bars_to_exit") or 999) < 3
    ]
    premature_trailing_flag = len(premature_trailing) >= max(1, len(trailing_rows) // 2) if trailing_rows else False

    verdict_parts: list[str] = []
    if bad_entry:
        verdict_parts.append("entrada_mala_probable (MFE promedio < 0.5%)")
    if bad_exit:
        verdict_parts.append("salida_mala_probable (MFE>0.8% pero PnL final <= 0)")
    if premature_trailing_flag:
        verdict_parts.append("trailing_prematuro_probable")
    if not verdict_parts:
        verdict_parts.append("sin_patron_dominante_claro_en_muestra")

    return {
        "avg_mfe_pct": round(avg_mfe, 4) if avg_mfe is not None else None,
        "bad_entry_signal": bad_entry,
        "bad_exit_signal": bad_exit,
        "bad_exit_count": len(bad_exit_cases),
        "trailing_stop_count": len(trailing_rows),
        "premature_trailing_count": len(premature_trailing),
        "premature_trailing_signal": premature_trailing_flag,
        "verdict": "; ".join(verdict_parts),
    }


def audit_bot_trades(
    *,
    sources: list[str] | None = None,
    candle_timeframe: str = "30m",
    filter_symbol: str | None = None,
) -> dict[str, Any]:
    """
    Audita trades cerrados de testnet (crypto_testnet_orders.json) y paper (crypto_paper_portfolio.json).
    """
    want = {s.strip().lower() for s in (sources or ["testnet", "paper"])}
    trades: list[dict[str, Any]] = []
    if "testnet" in want:
        tn = _load_testnet_closed_trades()
        trades.extend(tn)
        _log(f"testnet cerrados: {len(tn)}")
    if "paper" in want:
        paper = _load_paper_closed_trades()
        trades.extend(paper)
        _log(f"paper cerrados: {len(paper)} total={len(trades)}")

    if filter_symbol:
        fs = filter_symbol.strip().upper().replace(" ", "")
        if "/" not in fs and fs.endswith("USDT"):
            fs = f"{fs[:-4]}/USDT"
        trades = [t for t in trades if str(t.get("symbol") or "").upper().replace(" ", "") == fs.replace(" ", "")]

    candle_cache: dict[tuple[str, str], list[list[float]]] = {}
    enriched: list[dict[str, Any]] = []
    for t in trades:
        enriched.append(
            _enrich_trade_with_candles(t, candle_timeframe=candle_timeframe, candle_cache=candle_cache)
        )

    valid = [t for t in enriched if t.get("max_favorable_pct") is not None]
    wins = sum(1 for t in valid if float(t.get("pnl_pct") or 0) > 1e-9)
    losses = sum(1 for t in valid if float(t.get("pnl_pct") or 0) < -1e-9)
    total = len(valid)
    win_rate = (wins / total * 100.0) if total else None
    pnls = [float(t["pnl_pct"]) for t in valid if t.get("pnl_pct") is not None]

    reason_ctr = Counter(str(t.get("exit_reason") or "unknown").lower() for t in valid)

    return {
        "ok": True,
        "sources": sorted(want),
        "candle_timeframe": candle_timeframe,
        "orders_json_path": str(_ORDERS_JSON),
        "paper_json_path": str(_PAPER_JSON),
        "trades_count": total,
        "trades_raw_count": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 2) if win_rate is not None else None,
        "avg_pnl_pct": round(mean(pnls), 4) if pnls else None,
        "median_pnl_pct": round(median(pnls), 4) if pnls else None,
        "exit_reason_counts": dict(reason_ctr),
        "stop_loss_count": reason_ctr.get("stop_loss", 0),
        "take_profit_count": reason_ctr.get("take_profit", 0),
        "trailing_stop_count": reason_ctr.get("trailing_stop", 0),
        "diagnosis": _diagnose_trades(valid),
        "trades": enriched,
    }
