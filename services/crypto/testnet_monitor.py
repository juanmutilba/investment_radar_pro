"""
Monitor Testnet asistido (en memoria): ejecuta periódicamente propuesta de entrada + salidas,
sin enviar órdenes a Binance. El usuario confirma BUY/SELL por los endpoints manuales existentes.

No se arranca al importar la API; sólo tras POST .../monitor/start.
"""
from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

_LOG_PREFIX = "[CRYPTO_TESTNET_MONITOR]"

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_WAKE = threading.Event()

_STATE: dict[str, Any] = {
    "enabled": False,
    "running": False,
    "last_run_at": None,
    "next_run_at": None,
    "last_error": None,
    "last_entry_proposal": None,
    "last_entry_primary_reason": None,
    "last_exit_proposals": [],
    "last_evaluated_entries": [],
    "last_evaluated_exits": [],
    "interval_seconds": 300,
    "params": {},
    "last_cycle_started_at": None,
    "last_cycle_finished_at": None,
    "last_cycle_duration_ms": None,
    "last_cycle_summary": None,
    "best_rejected_candidate": None,
    "last_entry_candidate": None,
    "last_primary_reason": None,
}


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _schedule_next_run_locked(interval_seconds: int) -> None:
    interval_seconds = max(30, int(interval_seconds))
    _STATE["next_run_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)
    ).isoformat(timespec="seconds")


def _apply_entry_diagnostics(entry: dict[str, Any]) -> None:
    from services.crypto.cycle_diagnostics import (
        build_cycle_summary_from_evaluated,
        pick_best_rejected_candidate,
        pick_entry_candidate_from_evaluated,
    )

    evaluated = [e for e in (entry.get("evaluated") or []) if isinstance(e, dict)]
    _STATE["last_cycle_summary"] = build_cycle_summary_from_evaluated(evaluated)
    _STATE["best_rejected_candidate"] = pick_best_rejected_candidate(evaluated)
    _STATE["last_primary_reason"] = entry.get("primary_reason")
    _STATE["last_entry_primary_reason"] = entry.get("primary_reason")

    proposal = entry.get("proposal")
    if isinstance(proposal, dict) and proposal.get("symbol"):
        _STATE["last_entry_candidate"] = {
            "symbol": str(proposal.get("symbol")),
            "score": proposal.get("score"),
            "reason": str(proposal.get("reason") or ""),
            "signal": str(proposal.get("signal") or ""),
        }
    else:
        _STATE["last_entry_candidate"] = pick_entry_candidate_from_evaluated(evaluated)


def _run_cycle() -> None:
    from services.crypto.binance_testnet import propose_testnet_exits
    from services.crypto.bot_runner import propose_testnet_entry_from_strategy

    cycle_started_iso = _utc_now_iso()
    cycle_started_mono = time.monotonic()

    with _LOCK:
        params = dict(_STATE["params"])
        interval_sec = max(30, int(_STATE["interval_seconds"]))
        _STATE["running"] = True
        _STATE["last_cycle_started_at"] = cycle_started_iso

    errs: list[str] = []
    entry: dict[str, Any] | None = None
    exit_payload: dict[str, Any] | None = None

    try:
        tr_raw = params.get("trailing_stop_pct")
        tr_entry_f = 1.5 if tr_raw is None else float(tr_raw)
        trailing_exit: float | None
        if tr_raw is None:
            trailing_exit = None
        else:
            try:
                trailing_exit = float(tr_raw)
            except (TypeError, ValueError):
                trailing_exit = None

        entry = propose_testnet_entry_from_strategy(
            timeframe=str(params.get("timeframe") or "1h"),
            limit=int(params.get("limit") or 200),
            quote_amount_usdt=float(params.get("quote_amount_usdt") or 10),
            stop_loss_pct=float(params.get("stop_loss_pct") or 2),
            take_profit_pct=float(params.get("take_profit_pct") or 4),
            trailing_stop_pct=tr_entry_f,
            max_open_positions=int(params.get("max_open_positions") or 3),
            break_even_trigger_pct=float(params.get("break_even_trigger_pct") or 0),
            break_even_plus_pct=float(params.get("break_even_plus_pct") or 0),
            cooldown_minutes=int(params.get("cooldown_minutes") or 0),
            require_btc_trend_up=bool(params.get("require_btc_trend_up")),
            min_entry_score=float(params.get("min_entry_score") or 0),
        )

        exit_payload = propose_testnet_exits(
            stop_loss_pct=float(params.get("stop_loss_pct") or 2),
            take_profit_pct=float(params.get("take_profit_pct") or 4),
            trailing_stop_pct=trailing_exit,
            min_value_usdt=float(params.get("min_exit_value_usdt") or 5),
        )

        if not exit_payload.get("ok"):
            errs.append(str(exit_payload.get("error") or "exit_propose_failed"))

    except Exception as e:
        errs.append(f"{type(e).__name__}: {e}")
        _log(f"ciclo error {errs[-1]}")
    finally:
        now_iso = _utc_now_iso()
        duration_ms = int((time.monotonic() - cycle_started_mono) * 1000)
        with _LOCK:
            _STATE["running"] = False
            _STATE["last_run_at"] = now_iso
            _STATE["last_cycle_finished_at"] = now_iso
            _STATE["last_cycle_duration_ms"] = duration_ms
            _schedule_next_run_locked(interval_sec)

            if entry is not None:
                _STATE["last_entry_proposal"] = copy.deepcopy(entry.get("proposal"))
                _STATE["last_evaluated_entries"] = copy.deepcopy(entry.get("evaluated") or [])
                _apply_entry_diagnostics(entry)
            else:
                _STATE["last_entry_proposal"] = None
                _STATE["last_entry_primary_reason"] = None
                _STATE["last_evaluated_entries"] = []
                _STATE["last_cycle_summary"] = None
                _STATE["best_rejected_candidate"] = None
                _STATE["last_entry_candidate"] = None
                _STATE["last_primary_reason"] = None

            if exit_payload is not None:
                _STATE["last_exit_proposals"] = copy.deepcopy(exit_payload.get("proposals") or [])
                _STATE["last_evaluated_exits"] = copy.deepcopy(exit_payload.get("evaluated") or [])
            else:
                _STATE["last_exit_proposals"] = []
                _STATE["last_evaluated_exits"] = []

            _STATE["last_error"] = "; ".join(errs) if errs else None


def _worker_loop() -> None:
    global _THREAD
    _log("hilo monitor iniciado")
    try:
        while True:
            with _LOCK:
                if not _STATE["enabled"]:
                    break

            _run_cycle()

            with _LOCK:
                if not _STATE["enabled"]:
                    break
                interval_sec = max(30, int(_STATE["interval_seconds"]))

            _WAKE.wait(timeout=float(interval_sec))
            _WAKE.clear()
    finally:
        with _LOCK:
            _THREAD = None
            _STATE["running"] = False
            _STATE["next_run_at"] = None
        _log("hilo monitor terminado")


def start_testnet_monitor(
    *,
    interval_minutes: float,
    quote_amount_usdt: float,
    timeframe: str,
    limit: int,
    max_open_positions: int,
    cooldown_minutes: int,
    require_btc_trend_up: bool,
    min_entry_score: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_stop_pct: float | None,
    break_even_trigger_pct: float,
    break_even_plus_pct: float,
    min_exit_value_usdt: float,
) -> dict[str, Any]:
    """Arranca o reanuda el monitor; actualiza parámetros si ya estaba activo."""
    if interval_minutes < 1 or interval_minutes > 1440:
        raise ValueError("interval_minutes debe estar entre 1 y 1440")
    interval_seconds = max(30, int(interval_minutes * 60))

    params: dict[str, Any] = {
        "interval_minutes": float(interval_minutes),
        "quote_amount_usdt": float(quote_amount_usdt),
        "timeframe": (timeframe or "1h").strip() or "1h",
        "limit": int(limit),
        "max_open_positions": int(max_open_positions),
        "cooldown_minutes": int(cooldown_minutes),
        "require_btc_trend_up": bool(require_btc_trend_up),
        "min_entry_score": float(min_entry_score),
        "stop_loss_pct": float(stop_loss_pct),
        "take_profit_pct": float(take_profit_pct),
        "trailing_stop_pct": trailing_stop_pct,
        "break_even_trigger_pct": float(break_even_trigger_pct),
        "break_even_plus_pct": float(break_even_plus_pct),
        "min_exit_value_usdt": float(min_exit_value_usdt),
    }

    global _THREAD

    with _LOCK:
        _STATE["enabled"] = True
        _STATE["interval_seconds"] = interval_seconds
        _STATE["params"] = params
        need_spawn = _THREAD is None or not _THREAD.is_alive()

    _WAKE.set()

    if need_spawn:
        t = threading.Thread(target=_worker_loop, name="crypto-testnet-monitor", daemon=True)
        with _LOCK:
            if _THREAD is None or not _THREAD.is_alive():
                _THREAD = t
                t.start()

    _log(f"start interval_s={interval_seconds} timeframe={params['timeframe']}")
    return get_testnet_monitor_status()


def stop_testnet_monitor() -> dict[str, Any]:
    global _THREAD
    with _LOCK:
        _STATE["enabled"] = False
    _WAKE.set()
    th: threading.Thread | None
    with _LOCK:
        th = _THREAD
    if th is not None and th.is_alive():
        th.join(timeout=15.0)
    _log("stop")
    return get_testnet_monitor_status()


def get_testnet_monitor_status() -> dict[str, Any]:
    with _LOCK:
        return {
            "ok": True,
            "enabled": bool(_STATE["enabled"]),
            "running": bool(_STATE["running"]),
            "last_run_at": _STATE["last_run_at"],
            "next_run_at": _STATE["next_run_at"],
            "last_error": _STATE["last_error"],
            "last_entry_proposal": copy.deepcopy(_STATE["last_entry_proposal"]),
            "last_entry_primary_reason": _STATE["last_entry_primary_reason"],
            "last_exit_proposals": copy.deepcopy(_STATE["last_exit_proposals"]),
            "last_evaluated_entries": copy.deepcopy(_STATE["last_evaluated_entries"]),
            "last_evaluated_exits": copy.deepcopy(_STATE["last_evaluated_exits"]),
            "interval_seconds": int(_STATE["interval_seconds"]),
            "params": copy.deepcopy(_STATE["params"]),
            "last_cycle_started_at": _STATE.get("last_cycle_started_at"),
            "last_cycle_finished_at": _STATE.get("last_cycle_finished_at"),
            "last_cycle_duration_ms": _STATE.get("last_cycle_duration_ms"),
            "last_cycle_summary": copy.deepcopy(_STATE.get("last_cycle_summary")),
            "best_rejected_candidate": copy.deepcopy(_STATE.get("best_rejected_candidate")),
            "last_entry_candidate": copy.deepcopy(_STATE.get("last_entry_candidate")),
            "last_primary_reason": _STATE.get("last_primary_reason"),
        }
