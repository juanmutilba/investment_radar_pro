"""
Análisis de rendimiento Testnet (solo datos locales: órdenes, ciclos auto, posiciones app).
No modifica parámetros ni ejecuta órdenes.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_ORDERS_JSON = _DATA_DIR / "crypto_testnet_orders.json"
_AUTO_CYCLES_JSONL = _DATA_DIR / "crypto_testnet_auto_cycles.jsonl"
_AUTO_TAIL = 2500
_EPS = 1e-8


def _safe_float(x: Any) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _row_created_at_iso(row: dict[str, Any]) -> str | None:
    raw = str(row.get("created_at") or "").strip()
    if raw:
        return raw
    ts_ex = row.get("timestamp_exchange")
    if isinstance(ts_ex, (int, float)) and math.isfinite(float(ts_ex)):
        v = float(ts_ex)
        if v < 1e11:
            v *= 1000.0
        try:
            return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc).isoformat(timespec="seconds")
        except (OSError, OverflowError, ValueError):
            pass
    return None


def _order_usdt_notional(row: dict[str, Any], qty: float) -> float | None:
    if not (qty > 0):
        return None
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


def _load_orders_rows() -> list[dict[str, Any]]:
    if not _ORDERS_JSON.is_file():
        return []
    try:
        raw = json.loads(_ORDERS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    return []


def _load_recent_auto_cycles(max_lines: int = _AUTO_TAIL) -> list[dict[str, Any]]:
    if not _AUTO_CYCLES_JSONL.is_file():
        return []
    try:
        lines = _AUTO_CYCLES_JSONL.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    tail = lines[-max_lines:]
    out: list[dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except json.JSONDecodeError:
            continue
    return out


def _closed_cycles_with_setup_from_orders(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Replica FIFO por símbolo (misma idea que reconstrucción app) y asigna setup/score
    del primer BUY del ciclo cerrado.
    """
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sym = str(row.get("symbol") or "").strip()
        if sym:
            by_sym[sym].append(row)
    closed: list[dict[str, Any]] = []
    for sym, sym_rows in by_sym.items():
        sym_rows.sort(key=lambda r: (_parse_iso_dt(_row_created_at_iso(r)) or datetime.min.replace(tzinfo=timezone.utc),))
        base_inv = 0.0
        cost_inv = 0.0
        cycle_buy_base = 0.0
        cycle_buy_cost = 0.0
        cycle_sell_base = 0.0
        cycle_sell_proceeds = 0.0
        cycle_setup: str | None = None
        cycle_score: float | None = None
        opened_at: str | None = None

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
                    cycle_buy_base = 0.0
                    cycle_buy_cost = 0.0
                    cycle_sell_base = 0.0
                    cycle_sell_proceeds = 0.0
                    st = str(row.get("setup_type") or "").strip()
                    cycle_setup = st or None
                    cycle_score = _safe_float(row.get("entry_score"))
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
                cost_inv -= cost_sold
                base_inv -= sell_qty
                cycle_sell_base += sell_qty
                cycle_sell_proceeds += proceeds
                if cost_inv < 0:
                    cost_inv = 0.0
                if base_inv <= _EPS:
                    base_inv = 0.0
                    cost_inv = 0.0
                    pnl_cycle = cycle_sell_proceeds - cycle_buy_cost
                    pnl_pct = (
                        (pnl_cycle / cycle_buy_cost) * 100.0
                        if cycle_buy_cost > 0 and math.isfinite(pnl_cycle)
                        else None
                    )
                    closed.append(
                        {
                            "symbol": sym,
                            "pnl_usdt": round(pnl_cycle, 8),
                            "pnl_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
                            "opened_at": opened_at,
                            "closed_at": ts,
                            "setup_type": cycle_setup or "unknown",
                            "entry_score": cycle_score,
                        }
                    )
                    opened_at = None
                    cycle_buy_base = 0.0
                    cycle_buy_cost = 0.0
                    cycle_sell_base = 0.0
                    cycle_sell_proceeds = 0.0
                    cycle_setup = None
                    cycle_score = None
    return closed


def _recommendations(
    *,
    win_rate_pct: float | None,
    total_closed: int,
    avg_pnl: float | None,
    worst: float | None,
    best: float | None,
    by_setup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    if total_closed < 3:
        recs.append(
            {
                "code": "low_sample",
                "text": "Pocos trades cerrados en historial local; las métricas son orientativas.",
                "severity": "info",
            }
        )
    if win_rate_pct is not None and win_rate_pct < 40 and total_closed >= 5:
        recs.append(
            {
                "code": "low_win_rate",
                "text": "Win rate bajo: considerá subir min_entry_score o endurecer filtros de entrada.",
                "severity": "warn",
            }
        )
    if worst is not None and worst < -5 and total_closed >= 3:
        recs.append(
            {
                "code": "large_losses",
                "text": "Hay pérdidas grandes vs ganancias: revisá SL más ajustado o tamaño de posición.",
                "severity": "warn",
            }
        )
    if best is not None and avg_pnl is not None and best > 0 and avg_pnl > 0 and best > avg_pnl * 4 and total_closed >= 5:
        recs.append(
            {
                "code": "giveback",
                "text": "Ganancias puntuales altas pero promedio modesto: trailing o break-even más agresivo puede proteger profits.",
                "severity": "info",
            }
        )
    if total_closed >= 5 and win_rate_pct is not None and win_rate_pct > 55 and avg_pnl is not None and avg_pnl < 0.5:
        recs.append(
            {
                "code": "small_wins",
                "text": "Muchos aciertos con poco PnL medio: podés probar TP algo mayor o filtrar setups con poco recorrido.",
                "severity": "info",
            }
        )
    for setup, agg in by_setup.items():
        if setup in ("", "unknown"):
            continue
        n = int(agg.get("trades") or 0)
        if n < 3:
            continue
        wr = _safe_float(agg.get("win_rate_pct"))
        if wr is not None and wr < 35:
            recs.append(
                {
                    "code": f"setup_weak_{setup}",
                    "text": f"El setup «{setup}» muestra win rate bajo ({wr:g}%). Considerá exigir más score en ese tipo o evitarlo.",
                    "severity": "warn",
                }
            )
    if not recs:
        recs.append(
            {
                "code": "neutral",
                "text": "Sin señales fuertes de ajuste: mantené el diagnóstico y seguí acumulando trades testnet.",
                "severity": "info",
            }
        )
    return recs


def analyze_testnet_strategy_performance() -> dict[str, Any]:
    from services.crypto.binance_testnet import get_testnet_app_positions

    orders = _load_orders_rows()
    attr_closed = _closed_cycles_with_setup_from_orders(orders)

    app = get_testnet_app_positions()
    closed_app: list[dict[str, Any]] = []
    if app.get("ok"):
        closed_app = [c for c in (app.get("closed_positions") or []) if isinstance(c, dict)]

    if attr_closed:
        closed_src = attr_closed
        closed_trades_source = "orders_json_fifo_with_setup"
    else:
        closed_src = closed_app
        closed_trades_source = "app_positions_fifo"

    pnls: list[float] = []
    durations_hours: list[float] = []
    by_symbol: dict[str, list[float]] = defaultdict(list)
    hour_pnl: dict[int, list[float]] = defaultdict(list)
    by_setup: dict[str, dict[str, Any]] = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
    scores: list[float] = []

    for c in closed_src:
        pnl = _safe_float(c.get("pnl_usdt"))
        if pnl is None:
            continue
        pnls.append(pnl)
        sym = str(c.get("symbol") or "").strip().upper() or "UNKNOWN"
        by_symbol[sym].append(pnl)
        ca = _parse_iso_dt(str(c.get("closed_at") or "") or None)
        if ca:
            hour_pnl[ca.hour].append(pnl)
        oa = _parse_iso_dt(str(c.get("opened_at") or "") or None)
        if oa and ca:
            durations_hours.append(max(0.0, (ca - oa).total_seconds() / 3600.0))
        st = str(c.get("setup_type") or "unknown").strip() or "unknown"
        by_setup[st]["pnl"] += pnl
        by_setup[st]["trades"] += 1
        if pnl > 1e-9:
            by_setup[st]["wins"] += 1
        sc = _safe_float(c.get("entry_score"))
        if sc is not None:
            scores.append(sc)

    total_closed = len(pnls)
    total_pnl = sum(pnls) if pnls else 0.0
    wins = sum(1 for p in pnls if p > 1e-9)
    losses = sum(1 for p in pnls if p < -1e-9)
    win_rate_pct = round((wins / total_closed) * 100.0, 2) if total_closed else None
    avg_pnl = round(total_pnl / total_closed, 6) if total_closed else None
    best = max(pnls) if pnls else None
    worst = min(pnls) if pnls else None
    avg_dur_h = round(sum(durations_hours) / len(durations_hours), 4) if durations_hours else None

    by_symbol_summary: dict[str, Any] = {}
    for sym, vals in by_symbol.items():
        by_symbol_summary[sym] = {
            "trades": len(vals),
            "pnl_usdt": round(sum(vals), 6),
            "win_rate_pct": round(sum(1 for x in vals if x > 1e-9) / len(vals) * 100.0, 2) if vals else None,
        }

    hour_summary: dict[str, Any] = {}
    for h, vals in sorted(hour_pnl.items()):
        if not vals:
            continue
        hour_summary[str(h)] = {
            "trades": len(vals),
            "pnl_usdt": round(sum(vals), 6),
        }

    setup_summary: dict[str, Any] = {}
    for setup, agg in by_setup.items():
        n = int(agg["trades"])
        if n <= 0:
            continue
        wr = round(float(agg["wins"]) / n * 100.0, 2) if n else None
        setup_summary[setup] = {
            "trades": n,
            "pnl_usdt": round(float(agg["pnl"]), 6),
            "win_rate_pct": wr,
        }

    cycles = _load_recent_auto_cycles()
    mode_counts: dict[str, int] = defaultdict(int)
    buy_actions = 0
    sell_ok = 0
    for cy in cycles:
        ps = cy.get("params_snapshot")
        if isinstance(ps, dict) and ps.get("strategy_mode"):
            mode_counts[str(ps.get("strategy_mode"))] += 1
        for a in cy.get("actions_taken") or []:
            if not isinstance(a, dict):
                continue
            if a.get("type") == "buy_market":
                buy_actions += 1
            if a.get("type") == "sell_market" and a.get("ok"):
                sell_ok += 1

    recs = _recommendations(
        win_rate_pct=win_rate_pct,
        total_closed=total_closed,
        avg_pnl=avg_pnl,
        worst=worst,
        best=best,
        by_setup={k: v for k, v in by_setup.items()},
    )

    return {
        "ok": True,
        "source": "testnet_local_only",
        "closed_trades_source": closed_trades_source,
        "note": "Diagnóstico basado en operaciones Testnet (órdenes locales y/o posiciones app). No modifica parámetros automáticamente.",
        "closed_trades_count": total_closed,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate_pct,
        "total_pnl_usdt": round(total_pnl, 8) if pnls else 0.0,
        "avg_pnl_per_trade_usdt": avg_pnl,
        "best_trade_usdt": round(best, 8) if best is not None else None,
        "worst_trade_usdt": round(worst, 8) if worst is not None else None,
        "avg_hold_duration_hours": avg_dur_h,
        "by_symbol": by_symbol_summary,
        "by_hour_utc": hour_summary,
        "by_setup": setup_summary,
        "entry_score_samples": len(scores),
        "entry_score_avg": round(sum(scores) / len(scores), 4) if scores else None,
        "auto_cycles_sampled": len(cycles),
        "auto_cycles_strategy_mode_counts": dict(mode_counts),
        "auto_cycles_buy_actions_count": buy_actions,
        "auto_cycles_sell_ok_count": sell_ok,
        "recommendations": recs,
    }
