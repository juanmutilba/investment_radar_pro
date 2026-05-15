"""Scheduler en memoria para auto-run del bot paper cripto (sin trading real)."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

DEFAULT_EXITS_INTERVAL_SECONDS = 5 * 60
DEFAULT_STRATEGY_INTERVAL_SECONDS = 30 * 60
_TICK_SECONDS = 30
_MAX_LAST_ACTIONS = 100

_state_lock = threading.Lock()
_cycle_lock = threading.Lock()
_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None

_state: dict[str, Any] = {
    "enabled": False,
    "running": False,
    "last_run_at": None,
    "next_run_at": None,
    "last_error": None,
    "last_actions": [],
    "auto_session_buys_count": 0,
    "auto_session_sells_count": 0,
    "auto_session_last_buy_symbol": None,
    "auto_session_last_sell_symbol": None,
    "strategy_interval_seconds": DEFAULT_STRATEGY_INTERVAL_SECONDS,
    "exits_interval_seconds": DEFAULT_EXITS_INTERVAL_SECONDS,
    "strategy_params": None,
    "_last_exits_mono": None,
    "_last_strategy_mono": None,
}


def _reset_auto_session_counters() -> None:
    _state["auto_session_buys_count"] = 0
    _state["auto_session_sells_count"] = 0
    _state["auto_session_last_buy_symbol"] = None
    _state["auto_session_last_sell_symbol"] = None


def _accumulate_auto_session_counts(actions: list[dict[str, Any]]) -> None:
    """Cuenta entradas/salidas ejecutadas del ciclo (sin modificar lógica de trading)."""
    for a in actions:
        if a.get("phase") == "strategy_summary":
            continue
        action = a.get("action")
        status = a.get("status")
        sym = a.get("symbol")
        if not sym or not isinstance(sym, str):
            continue
        sym = sym.strip()
        if not sym:
            continue
        if action == "entry" and status == "executed":
            _state["auto_session_buys_count"] = int(_state.get("auto_session_buys_count") or 0) + 1
            _state["auto_session_last_buy_symbol"] = sym
        elif action == "exit" and status == "executed":
            _state["auto_session_sells_count"] = int(_state.get("auto_session_sells_count") or 0) + 1
            _state["auto_session_last_sell_symbol"] = sym


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _refresh_next_run_at() -> None:
    now_mono = time.monotonic()
    with _state_lock:
        if not _state["enabled"]:
            _state["next_run_at"] = None
            return
        exits_iv = int(_state["exits_interval_seconds"])
        strat_iv = int(_state["strategy_interval_seconds"])
        last_exits = _state.get("_last_exits_mono")
        last_strat = _state.get("_last_strategy_mono")
        candidates: list[float] = []
        if last_exits is None:
            candidates.append(now_mono)
        else:
            candidates.append(last_exits + exits_iv)
        if last_strat is None:
            candidates.append(now_mono)
        else:
            candidates.append(last_strat + strat_iv)
        delay = max(0.0, min(candidates) - now_mono)
        _state["next_run_at"] = datetime.fromtimestamp(
            time.time() + delay, tz=timezone.utc
        ).isoformat()


def _run_cycle() -> None:
    if not _cycle_lock.acquire(blocking=False):
        return
    try:
        with _state_lock:
            if not _state["enabled"]:
                return
            if _state["running"]:
                return
            _state["running"] = True
            exits_iv = int(_state["exits_interval_seconds"])
            strat_iv = int(_state["strategy_interval_seconds"])
            last_exits = _state.get("_last_exits_mono")
            last_strat = _state.get("_last_strategy_mono")
            params = dict(_state["strategy_params"] or {})

        now = time.monotonic()
        do_exits = last_exits is None or (now - float(last_exits)) >= exits_iv
        do_strategy = last_strat is None or (now - float(last_strat)) >= strat_iv

        if not do_exits and not do_strategy:
            return

        actions_accum: list[dict[str, Any]] = []

        if do_exits:
            from services.crypto.paper_portfolio import review_paper_positions_for_exit

            for a in review_paper_positions_for_exit():
                row = dict(a) if isinstance(a, dict) else {"detail": a}
                row["phase"] = "exit_review"
                actions_accum.append(row)
            with _state_lock:
                _state["_last_exits_mono"] = now

        if do_strategy:
            from services.crypto.bot_runner import execute_paper_strategy

            result = execute_paper_strategy(**params)
            for a in result.get("actions") or []:
                row = dict(a) if isinstance(a, dict) else {"detail": a}
                row["phase"] = "strategy"
                actions_accum.append(row)
            actions_accum.append(
                {
                    "phase": "strategy_summary",
                    "status": result.get("status"),
                    "opened_count": result.get("opened_count"),
                    "primary_reason": result.get("primary_reason"),
                    "message": result.get("message"),
                }
            )
            with _state_lock:
                _state["_last_strategy_mono"] = now

        with _state_lock:
            _state["last_run_at"] = _utc_iso()
            _state["last_actions"] = actions_accum[-_MAX_LAST_ACTIONS:]
            _accumulate_auto_session_counts(actions_accum)
            _state["last_error"] = None
    except Exception as e:
        with _state_lock:
            _state["last_error"] = str(e)
    finally:
        with _state_lock:
            _state["running"] = False
        _refresh_next_run_at()
        _cycle_lock.release()


def _scheduler_loop(stop: threading.Event) -> None:
    while not stop.wait(_TICK_SECONDS):
        with _state_lock:
            enabled = bool(_state["enabled"])
        if enabled:
            _run_cycle()


def _stop_thread() -> None:
    global _thread, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=5.0)
    _thread = None
    _stop_event = None


def start_paper_bot_scheduler(
    *,
    exits_interval_seconds: int = DEFAULT_EXITS_INTERVAL_SECONDS,
    strategy_interval_seconds: int = DEFAULT_STRATEGY_INTERVAL_SECONDS,
    strategy_params: dict[str, Any],
) -> dict[str, Any]:
    """Activa el scheduler con parámetros de estrategia paper."""
    exits_iv = max(60, int(exits_interval_seconds))
    strat_iv = max(60, int(strategy_interval_seconds))

    _stop_thread()

    with _state_lock:
        _state["enabled"] = True
        _state["running"] = False
        _state["last_run_at"] = None
        _state["last_error"] = None
        _state["last_actions"] = []
        _reset_auto_session_counters()
        _state["exits_interval_seconds"] = exits_iv
        _state["strategy_interval_seconds"] = strat_iv
        _state["strategy_params"] = dict(strategy_params)
        _state["_last_exits_mono"] = None
        _state["_last_strategy_mono"] = None

    _refresh_next_run_at()

    stop = threading.Event()
    t = threading.Thread(target=_scheduler_loop, args=(stop,), daemon=True, name="paper-bot-scheduler")
    t.start()

    global _thread, _stop_event
    _stop_event = stop
    _thread = t

    threading.Thread(target=_run_cycle, daemon=True, name="paper-bot-scheduler-kick").start()

    return get_paper_bot_scheduler_status()


def stop_paper_bot_scheduler() -> dict[str, Any]:
    """Detiene el scheduler (estado en memoria)."""
    with _state_lock:
        _state["enabled"] = False
        _state["running"] = False
        _reset_auto_session_counters()
    _stop_thread()
    with _state_lock:
        _state["next_run_at"] = None
    return get_paper_bot_scheduler_status()


def get_paper_bot_scheduler_status() -> dict[str, Any]:
    with _state_lock:
        return {
            "enabled": bool(_state["enabled"]),
            "running": bool(_state["running"]),
            "last_run_at": _state["last_run_at"],
            "next_run_at": _state["next_run_at"],
            "last_error": _state["last_error"],
            "last_actions": list(_state["last_actions"]),
            "auto_session_buys_count": int(_state.get("auto_session_buys_count") or 0),
            "auto_session_sells_count": int(_state.get("auto_session_sells_count") or 0),
            "auto_session_last_buy_symbol": _state.get("auto_session_last_buy_symbol"),
            "auto_session_last_sell_symbol": _state.get("auto_session_last_sell_symbol"),
            "strategy_interval_seconds": int(_state["strategy_interval_seconds"]),
            "exits_interval_seconds": int(_state["exits_interval_seconds"]),
        }
