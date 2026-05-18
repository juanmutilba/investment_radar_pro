"""
Monitor Testnet asistido (en memoria): ejecuta periódicamente propuesta de entrada + salidas,
sin enviar órdenes a Binance. El usuario confirma BUY/SELL por los endpoints manuales existentes.

No se arranca al importar la API; sólo tras POST .../monitor/start.
"""
from __future__ import annotations

import copy
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_LOG_PREFIX = "[CRYPTO_TESTNET_MONITOR]"
_CYCLE_HISTORY_LOG_PREFIX = "[CRYPTO_TESTNET_MONITOR_CYCLE_HISTORY]"
_MONITOR_CYCLES_JSONL = (
    Path(__file__).resolve().parents[2] / "data" / "crypto_testnet_monitor_cycles.jsonl"
)
_MONITOR_CYCLES_READ_CAP = 50_000
_MONITOR_CYCLES_FILE_MAX_LINES = 5000

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
    "last_scan_debug": None,
    "last_watchlist_count": None,
    "last_scan_count": None,
    "last_candidates_count": None,
    "last_exit_proposals_count": 0,
    "last_entry_proposal_generated": False,
    "last_no_entry_reason": None,
    "last_no_exit_reason": None,
}


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _log_cycle_history(msg: str) -> None:
    print(f"{_CYCLE_HISTORY_LOG_PREFIX} {msg}", flush=True)


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
        merge_scan_meta_into_summary,
        pick_best_rejected_candidate,
        pick_entry_candidate_from_evaluated,
    )

    evaluated = [e for e in (entry.get("evaluated") or []) if isinstance(e, dict)]
    summary = build_cycle_summary_from_evaluated(evaluated)
    scan_meta = entry.get("scan_debug")
    if isinstance(scan_meta, dict):
        summary = merge_scan_meta_into_summary(summary, scan_meta)
        full_dbg = dict(scan_meta)
        full_dbg["updated_at"] = _utc_now_iso()
        _STATE["last_scan_debug"] = full_dbg
    else:
        _STATE["last_scan_debug"] = None
    _STATE["last_cycle_summary"] = summary
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


def _slim_scan_debug_for_cycle_history(scan_debug: Any) -> dict[str, Any] | None:
    """Subset de scan_debug sin filas OHLCV ni payloads pesados de Binance."""
    if not isinstance(scan_debug, dict):
        return None
    keys = (
        "watchlist_count",
        "scan_count",
        "scan_ok_count",
        "scan_error_count",
        "candidates_count",
        "scan_error",
        "scan_duration_ms",
        "scan_scenario",
        "scan_diagnosis",
        "first_symbols_sample",
        "updated_at",
        "strategy_mode",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in scan_debug:
            out[k] = scan_debug[k]
    sample = out.get("first_symbols_sample")
    if isinstance(sample, list):
        out["first_symbols_sample"] = [str(s) for s in sample[:8]]
    err = out.get("scan_error")
    if isinstance(err, str) and len(err) > 240:
        out["scan_error"] = err[:240] + "…"
    return out or None


def _summarize_entry_proposal_for_cycle(proposal: Any) -> dict[str, Any] | None:
    if not isinstance(proposal, dict):
        return None
    sym = proposal.get("symbol")
    if not sym:
        return None
    out: dict[str, Any] = {
        "symbol": str(sym),
        "side": proposal.get("side"),
        "signal": proposal.get("signal"),
        "score": proposal.get("score"),
        "reason": proposal.get("reason"),
    }
    qa = proposal.get("quote_amount_usdt")
    if isinstance(qa, (int, float)) and qa == qa:
        out["quote_amount_usdt"] = round(float(qa), 4)
    return out


def _summarize_exit_proposals_for_cycle(proposals: Any) -> list[dict[str, Any]]:
    if not isinstance(proposals, list):
        return []
    out: list[dict[str, Any]] = []
    for p in proposals[:20]:
        if not isinstance(p, dict):
            continue
        asset = p.get("asset")
        sym = p.get("symbol")
        if not asset and not sym:
            continue
        row: dict[str, Any] = {
            "asset": asset,
            "symbol": sym,
            "exit_reason": p.get("exit_reason") or p.get("reason"),
        }
        pnl = p.get("pnl_pct")
        if isinstance(pnl, (int, float)) and pnl == pnl:
            row["pnl_pct"] = round(float(pnl), 4)
        out.append(row)
    return out


def _cycle_history_status(errs: list[str], entry: dict[str, Any] | None, exit_payload: dict[str, Any] | None) -> str:
    if not errs:
        return "ok"
    if entry is None and exit_payload is None:
        return "failed"
    return "partial"


def _build_monitor_cycle_history_record(
    *,
    timestamp: str,
    cycle_started_at: str,
    duration_ms: int,
    params: dict[str, Any],
    errs: list[str],
    entry: dict[str, Any] | None,
    exit_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    interval_min = params.get("interval_minutes")
    try:
        interval_min_f = float(interval_min) if interval_min is not None else None
    except (TypeError, ValueError):
        interval_min_f = None

    entry_prop_raw = entry.get("proposal") if isinstance(entry, dict) else None
    exit_props_raw = exit_payload.get("proposals") if isinstance(exit_payload, dict) else None
    has_entry = bool(isinstance(entry_prop_raw, dict) and entry_prop_raw.get("symbol"))
    exit_count = len(exit_props_raw) if isinstance(exit_props_raw, list) else 0

    scan_dbg = None
    if isinstance(entry, dict):
        scan_dbg = _slim_scan_debug_for_cycle_history(entry.get("scan_debug"))
    if scan_dbg is None:
        scan_dbg = _slim_scan_debug_for_cycle_history(_STATE.get("last_scan_debug"))

    no_entry = None if has_entry else (
        entry.get("primary_reason") if isinstance(entry, dict) else _STATE.get("last_no_entry_reason")
    )
    no_exit = None
    if isinstance(exit_payload, dict):
        if exit_count == 0:
            no_exit = str(exit_payload.get("primary_reason") or exit_payload.get("error") or "no_exit_proposals")
    elif exit_payload is None:
        no_exit = "exit_propose_failed"

    watchlist = None
    scan_count = None
    candidates = None
    strat_from_scan = None
    if isinstance(scan_dbg, dict):
        strat_from_scan = scan_dbg.get("strategy_mode")
        watchlist = scan_dbg.get("watchlist_count")
        scan_count = scan_dbg.get("scan_count")
        candidates = scan_dbg.get("candidates_count")
    if watchlist is None:
        watchlist = _STATE.get("last_watchlist_count")
    if scan_count is None:
        scan_count = _STATE.get("last_scan_count")
    if candidates is None:
        candidates = _STATE.get("last_candidates_count")

    strat = (
        str(params.get("strategy_mode") or strat_from_scan or "trend_swing").strip()
        or "trend_swing"
    )

    record: dict[str, Any] = {
        "timestamp": timestamp,
        "cycle_started_at": cycle_started_at,
        "cycle_finished_at": timestamp,
        "duration_ms": int(duration_ms),
        "interval_minutes": interval_min_f,
        "strategy_mode": strat,
        "status": _cycle_history_status(errs, entry, exit_payload),
        "watchlist_count": watchlist,
        "scan_count": scan_count,
        "candidates_count": candidates,
        "entry_proposal_generated": has_entry,
        "exit_proposals_count": exit_count,
        "no_entry_reason": no_entry,
        "no_exit_reason": no_exit,
        "scan_debug": scan_dbg,
        "entry_proposal": _summarize_entry_proposal_for_cycle(entry_prop_raw),
        "exit_proposals": _summarize_exit_proposals_for_cycle(exit_props_raw),
    }
    if errs:
        record["errors"] = errs[:5]
    return record


def _append_monitor_cycle_record(record: dict[str, Any]) -> None:
    _MONITOR_CYCLES_JSONL.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with _MONITOR_CYCLES_JSONL.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line)
    try:
        if _MONITOR_CYCLES_JSONL.stat().st_size > 4_000_000:
            lines = _MONITOR_CYCLES_JSONL.read_text(encoding="utf-8").splitlines()
            if len(lines) > _MONITOR_CYCLES_FILE_MAX_LINES:
                tail = lines[-_MONITOR_CYCLES_FILE_MAX_LINES :]
                _MONITOR_CYCLES_JSONL.write_text(
                    "\n".join(tail) + ("\n" if tail else ""),
                    encoding="utf-8",
                )
    except OSError:
        pass
    _log_cycle_history(
        f"append status={record.get('status')} scan={record.get('scan_count')} "
        f"entry={record.get('entry_proposal_generated')} exits={record.get('exit_proposals_count')}"
    )


def get_testnet_monitor_cycles(*, limit: int = 50) -> dict[str, Any]:
    """Últimos ciclos del monitor (más reciente primero)."""
    lim = max(1, min(int(limit), 500))
    if not _MONITOR_CYCLES_JSONL.is_file():
        return {"ok": True, "cycles": [], "total": 0}
    try:
        lines = _MONITOR_CYCLES_JSONL.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        return {"ok": False, "error": str(e), "cycles": [], "total": 0}
    total = 0
    parsed: list[dict[str, Any]] = []
    for line in lines[-_MONITOR_CYCLES_READ_CAP:]:
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                parsed.append(obj)
        except json.JSONDecodeError:
            continue
    tail = parsed[-lim:]
    tail.reverse()
    return {"ok": True, "cycles": tail, "total": total}


def _apply_cycle_scan_counts(entry: dict[str, Any] | None) -> None:
    scan_dbg = entry.get("scan_debug") if isinstance(entry, dict) else None
    if isinstance(scan_dbg, dict):
        _STATE["last_watchlist_count"] = scan_dbg.get("watchlist_count")
        _STATE["last_scan_count"] = scan_dbg.get("scan_count")
        _STATE["last_candidates_count"] = scan_dbg.get("candidates_count")
        return
    if not isinstance(entry, dict):
        _STATE["last_watchlist_count"] = None
        _STATE["last_scan_count"] = None
        _STATE["last_candidates_count"] = None
        return
    _STATE["last_watchlist_count"] = entry.get("watchlist_count")
    _STATE["last_scan_count"] = entry.get("scan_count") or entry.get("scanned_count")
    _STATE["last_candidates_count"] = entry.get("candidates_count")


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
            strategy_mode=str(params.get("strategy_mode") or "trend_swing"),
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
                _apply_cycle_scan_counts(entry)
                has_entry_prop = bool(entry.get("proposal"))
                _STATE["last_entry_proposal_generated"] = has_entry_prop
                _STATE["last_no_entry_reason"] = (
                    None if has_entry_prop else entry.get("primary_reason")
                )
            else:
                _STATE["last_entry_proposal"] = None
                _STATE["last_entry_primary_reason"] = None
                _STATE["last_evaluated_entries"] = []
                _STATE["last_cycle_summary"] = None
                _STATE["best_rejected_candidate"] = None
                _STATE["last_entry_candidate"] = None
                _STATE["last_primary_reason"] = None
                _STATE["last_scan_debug"] = None
                _STATE["last_watchlist_count"] = None
                _STATE["last_scan_count"] = None
                _STATE["last_candidates_count"] = None
                _STATE["last_entry_proposal_generated"] = False
                _STATE["last_no_entry_reason"] = "entry_scan_failed"

            if exit_payload is not None:
                exit_props = exit_payload.get("proposals") or []
                _STATE["last_exit_proposals"] = copy.deepcopy(exit_props)
                _STATE["last_evaluated_exits"] = copy.deepcopy(exit_payload.get("evaluated") or [])
                _STATE["last_exit_proposals_count"] = len(exit_props)
                _STATE["last_no_exit_reason"] = (
                    None
                    if exit_props
                    else str(exit_payload.get("primary_reason") or "no_exit_proposals")
                )
            else:
                _STATE["last_exit_proposals"] = []
                _STATE["last_evaluated_exits"] = []
                _STATE["last_exit_proposals_count"] = 0
                _STATE["last_no_exit_reason"] = "exit_propose_failed"

            _STATE["last_error"] = "; ".join(errs) if errs else None

            cycle_record = _build_monitor_cycle_history_record(
                timestamp=now_iso,
                cycle_started_at=cycle_started_iso,
                duration_ms=duration_ms,
                params=params,
                errs=errs,
                entry=entry,
                exit_payload=exit_payload,
            )

            _log(
                "ciclo testnet fin "
                f"watchlist={_STATE.get('last_watchlist_count')} "
                f"scan={_STATE.get('last_scan_count')} "
                f"candidates={_STATE.get('last_candidates_count')} "
                f"entry_prop={_STATE.get('last_entry_proposal_generated')} "
                f"exit_props={_STATE.get('last_exit_proposals_count')} "
                f"no_entry={_STATE.get('last_no_entry_reason')}"
            )

        try:
            _append_monitor_cycle_record(cycle_record)
        except Exception as e:
            _log_cycle_history(f"append falló: {type(e).__name__}: {e}")


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
    strategy_mode: str = "trend_swing",
) -> dict[str, Any]:
    """Arranca o reanuda el monitor; actualiza parámetros si ya estaba activo."""
    from services.crypto.strategy_modes import normalize_strategy_mode

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
        "strategy_mode": normalize_strategy_mode(strategy_mode),
    }

    global _THREAD

    with _LOCK:
        _STATE["enabled"] = True
        _STATE["interval_seconds"] = interval_seconds
        _STATE["params"] = params
        _schedule_next_run_locked(interval_seconds)
        need_spawn = _THREAD is None or not _THREAD.is_alive()

    _WAKE.set()

    if need_spawn:
        t = threading.Thread(target=_worker_loop, name="crypto-testnet-monitor", daemon=True)
        with _LOCK:
            if _THREAD is None or not _THREAD.is_alive():
                _THREAD = t
                t.start()

    _log(
        f"start interval_s={interval_seconds} timeframe={params['timeframe']} "
        f"strategy_mode={params.get('strategy_mode')}"
    )
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
            "last_scan_debug": copy.deepcopy(_STATE.get("last_scan_debug")),
            "last_watchlist_count": _STATE.get("last_watchlist_count"),
            "last_scan_count": _STATE.get("last_scan_count"),
            "last_candidates_count": _STATE.get("last_candidates_count"),
            "last_exit_proposals_count": int(_STATE.get("last_exit_proposals_count") or 0),
            "last_entry_proposal_generated": bool(_STATE.get("last_entry_proposal_generated")),
            "last_no_entry_reason": _STATE.get("last_no_entry_reason"),
            "last_no_exit_reason": _STATE.get("last_no_exit_reason"),
        }
