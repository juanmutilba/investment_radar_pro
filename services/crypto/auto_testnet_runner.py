"""
Auto Testnet (Binance Spot Sandbox únicamente): hilo en memoria que evalúa entrada/salidas
y ejecuta órdenes MARKET en testnet con guardas de sandbox antes de cada orden.

Separado del monitor asistido (testnet_monitor.py). No opera Binance real.
"""
from __future__ import annotations

import copy
import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.crypto.strategy_modes import normalize_strategy_mode

_LOG_PREFIX = "[CRYPTO_TESTNET_AUTO]"
_CYCLE_LOG_PREFIX = "[CRYPTO_TESTNET_AUTO_CYCLE]"

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_AUTO_CYCLES_JSONL = _DATA_DIR / "crypto_testnet_auto_cycles.jsonl"
_COUNTERS_JSON = _DATA_DIR / "crypto_testnet_auto_counters.json"
_AUTO_CYCLES_READ_CAP = 50_000
_AUTO_CYCLES_FILE_MAX_LINES = 5000

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_WAKE = threading.Event()

_DEFAULT_PARAMS: dict[str, Any] = {
    "strategy_mode": "daily_intraday",
    "timeframe": "30m",
    "limit": 200,
    "min_entry_score": 65.0,
    "require_btc_trend_up": False,
    "cooldown_minutes": 60,
    "max_open_positions": 3,
    "quote_amount_usdt": 15.0,
    "cycle_interval_minutes": 5.0,
    "stop_loss_pct": 0.8,
    "take_profit_pct": 1.0,
    "trailing_stop_pct": 0.5,
    "trailing_activation_pct": 1.0,
    "break_even_trigger_pct": 0.0,
    "break_even_plus_pct": 0.0,
    "min_exit_value_usdt": 5.0,
    "max_trades_per_day": 5,
    "max_daily_loss_usdt": 10.0,
    "max_total_exposure_usdt": 50.0,
    "max_quote_per_order_usdt": 100.0,
}

_STATE: dict[str, Any] = {
    "enabled": False,
    "running": False,
    "last_run_at": None,
    "next_run_at": None,
    "last_error": None,
    "last_action": None,
    "stop_reason": None,
    "params": dict(_DEFAULT_PARAMS),
    "interval_seconds": 300,
    "last_cycle_started_at": None,
    "last_cycle_finished_at": None,
    "last_cycle_duration_ms": None,
    "last_cycle_record": None,
    "utc_day": None,
    "auto_entries_today": 0,
    "auto_daily_pnl_usdt": 0.0,
    "last_app_total_pnl_usdt": None,
    "last_sandbox_status": None,
    "guard_first_failure_cycle_at": None,
    "guard_last_failure_snapshot": None,
    "last_guard_error_code": None,
    "last_params_request": None,
    "params_clamp_audit": [],
    "params_last_update_at": None,
    "params_last_update_changed_fields": [],
}


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _log_cycle(msg: str) -> None:
    print(f"{_CYCLE_LOG_PREFIX} {msg}", flush=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utc_day_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _hydrate_counters_from_disk_locked() -> None:
    """Con lock: restaura contadores del JSON si coincide el día UTC actual."""
    if not _COUNTERS_JSON.is_file():
        return
    try:
        obj = json.loads(_COUNTERS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(obj, dict):
        return
    day = str(obj.get("utc_day") or "").strip()
    if day != _utc_day_str():
        return
    try:
        entries = int(obj.get("auto_entries_today") or 0)
    except (TypeError, ValueError):
        entries = 0
    try:
        pnl = float(obj.get("auto_daily_pnl_usdt") or 0.0)
    except (TypeError, ValueError):
        pnl = 0.0
    _STATE["utc_day"] = day
    _STATE["auto_entries_today"] = max(0, entries)
    if math.isfinite(pnl):
        _STATE["auto_daily_pnl_usdt"] = pnl


def _save_counters_locked() -> None:
    _ensure_data_dir()
    payload = {
        "utc_day": _STATE.get("utc_day"),
        "auto_entries_today": int(_STATE.get("auto_entries_today") or 0),
        "auto_daily_pnl_usdt": float(_STATE.get("auto_daily_pnl_usdt") or 0.0),
        "updated_at": _utc_now_iso(),
    }
    try:
        _COUNTERS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        _log(f"contadores: no se pudo guardar {_COUNTERS_JSON}: {e}")


def _reset_daily_counters_if_needed_locked() -> None:
    today = _utc_day_str()
    if _STATE.get("utc_day") is None:
        _hydrate_counters_from_disk_locked()
    if _STATE.get("utc_day") == today:
        return
    _STATE["utc_day"] = today
    _STATE["auto_entries_today"] = 0
    _STATE["auto_daily_pnl_usdt"] = 0.0
    _STATE["stop_reason"] = None
    _save_counters_locked()


def _hard_guard_testnet_trading() -> tuple[bool, str, dict[str, Any]]:
    """
    Guarda obligatoria: sólo continuar si testnet está habilitado, configurado,
    y el cliente ccxt reporta sandbox/testnet (nunca urls_api_safe=real).
    """
    from services.crypto.binance_testnet import get_testnet_status

    st = get_testnet_status()
    snippet = {
        "configured": st.get("configured"),
        "enabled": st.get("enabled"),
        "sandbox_mode": st.get("sandbox_mode"),
        "urls_api_safe": st.get("urls_api_safe"),
        "diagnosis": st.get("diagnosis"),
        "can_read_balance": st.get("can_read_balance"),
        "can_read_ticker": st.get("can_read_ticker"),
        "message": st.get("message"),
        "balance_error": st.get("balance_error"),
        "ticker_error": st.get("ticker_error"),
    }
    if not st.get("enabled"):
        return False, "testnet_disabled", snippet
    if not st.get("configured"):
        return False, "testnet_not_configured", snippet
    if not st.get("sandbox_mode"):
        return False, "sandbox_mode_not_detected", snippet
    urls = str(st.get("urls_api_safe") or "").strip().lower()
    if urls == "real":
        return False, "urls_classified_as_real_abort", snippet
    if urls not in ("sandbox", "testnet"):
        return False, f"urls_api_safe_unsafe:{urls or 'unknown'}", snippet
    if st.get("diagnosis") != "ok":
        return False, f"diagnosis_not_ok:{st.get('diagnosis')}", snippet
    if not st.get("can_read_balance"):
        return False, "cannot_read_balance", snippet
    return True, "ok", snippet


def _open_exposure_usdt(app_payload: dict[str, Any]) -> float:
    total = 0.0
    for pos in app_payload.get("open_positions") or []:
        if not isinstance(pos, dict):
            continue
        amt = float(pos.get("amount_base") or 0.0)
        av = pos.get("avg_entry_price")
        try:
            av_f = float(av) if av is not None else 0.0
        except (TypeError, ValueError):
            av_f = 0.0
        if amt > 0 and av_f > 0 and math.isfinite(amt) and math.isfinite(av_f):
            total += amt * av_f
    return total


def _estimate_sell_pnl_usdt(proposal: dict[str, Any]) -> float | None:
    vu = proposal.get("value_usdt")
    pp = proposal.get("pnl_pct")
    try:
        v = float(vu) if vu is not None else None
        p = float(pp) if pp is not None else None
    except (TypeError, ValueError):
        return None
    if v is None or p is None or not math.isfinite(v) or not math.isfinite(p):
        return None
    return v * (p / 100.0)


def _append_auto_cycle_record(record: dict[str, Any]) -> None:
    _ensure_data_dir()
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with _AUTO_CYCLES_JSONL.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line)
    try:
        if _AUTO_CYCLES_JSONL.stat().st_size > 4_000_000:
            lines = _AUTO_CYCLES_JSONL.read_text(encoding="utf-8").splitlines()
            if len(lines) > _AUTO_CYCLES_FILE_MAX_LINES:
                tail = lines[-_AUTO_CYCLES_FILE_MAX_LINES :]
                _AUTO_CYCLES_JSONL.write_text(
                    "\n".join(tail) + ("\n" if tail else ""),
                    encoding="utf-8",
                )
    except OSError:
        pass
    _log_cycle(f"jsonl status={record.get('status')} actions={record.get('actions_taken')}")


def _merge_params(prior_state: dict[str, Any] | None, request: dict[str, Any] | None) -> dict[str, Any]:
    """
    Capas: defaults → estado previo del runner → body del último POST /auto/start.
    Acepta alias max_entries_per_day → max_trades_per_day.
    """
    out = dict(_DEFAULT_PARAMS)
    for layer in (prior_state, request):
        if not layer:
            continue
        for k, v in layer.items():
            if v is None:
                continue
            kk = k
            if kk == "max_entries_per_day":
                kk = "max_trades_per_day"
            if kk not in _DEFAULT_PARAMS:
                continue
            out[kk] = v
    out["strategy_mode"] = normalize_strategy_mode(str(out.get("strategy_mode") or "daily_intraday"))
    return out


def _clamp_params(p: dict[str, Any]) -> dict[str, Any]:
    from services.crypto.binance_testnet import MAX_MARKET_ORDER_QUOTE_USDT, MIN_MARKET_ORDER_QUOTE_USDT

    out = dict(p)
    out["quote_amount_usdt"] = max(
        MIN_MARKET_ORDER_QUOTE_USDT,
        min(float(out.get("quote_amount_usdt") or 10), float(out.get("max_quote_per_order_usdt") or MAX_MARKET_ORDER_QUOTE_USDT), MAX_MARKET_ORDER_QUOTE_USDT),
    )
    out["max_quote_per_order_usdt"] = min(float(out.get("max_quote_per_order_usdt") or MAX_MARKET_ORDER_QUOTE_USDT), MAX_MARKET_ORDER_QUOTE_USDT)
    out["max_open_positions"] = max(1, min(int(out.get("max_open_positions") or 3), 50))
    out["cooldown_minutes"] = max(0, int(out.get("cooldown_minutes") or 0))
    out["limit"] = max(50, min(int(out.get("limit") or 200), 1000))
    out["max_trades_per_day"] = max(1, min(int(out.get("max_trades_per_day") or 5), 100))
    out["max_daily_loss_usdt"] = max(0.1, float(out.get("max_daily_loss_usdt") or 10))
    out["max_total_exposure_usdt"] = max(1.0, float(out.get("max_total_exposure_usdt") or 50))
    out["cycle_interval_minutes"] = max(1.0, min(float(out.get("cycle_interval_minutes") or 5), 1440.0))
    out["min_exit_value_usdt"] = max(0.0, float(out.get("min_exit_value_usdt") or 5))
    return out


def _clamp_params_with_audit(p: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    before = copy.deepcopy(dict(p))
    after = _clamp_params(dict(p))
    diffs: list[dict[str, Any]] = []
    for k in sorted(_DEFAULT_PARAMS.keys()):
        b, a = before.get(k), after.get(k)
        if b != a:
            diffs.append({"field": k, "requested": b, "applied": a})
    return after, diffs


def _schedule_next_run_locked(interval_seconds: int) -> None:
    interval_seconds = max(60, int(interval_seconds))
    _STATE["interval_seconds"] = interval_seconds
    _STATE["next_run_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)
    ).isoformat(timespec="seconds")


def _run_cycle() -> None:
    from services.crypto.binance_testnet import (
        MAX_MARKET_ORDER_QUOTE_USDT,
        get_testnet_app_positions,
        place_testnet_market_order,
        propose_testnet_exits,
    )
    from services.crypto.bot_runner import propose_testnet_entry_from_strategy

    cycle_started = _utc_now_iso()
    t0 = time.monotonic()

    with _LOCK:
        params = _clamp_params(dict(_STATE["params"]))
        _STATE["params"] = params
        interval_sec = max(60, int(_STATE["interval_seconds"]))
        _STATE["running"] = True
        _STATE["last_cycle_started_at"] = cycle_started
        _reset_daily_counters_if_needed_locked()

    actions: list[dict[str, Any]] = []
    errs: list[str] = []

    exit_scan_count = 0
    exit_proposals_count = 0
    exit_execution_attempted_count = 0
    exit_execution_success_count = 0
    exit_execution_error_count = 0
    last_exit_block_reason: str | None = None
    exit_position_evaluations: list[dict[str, Any]] = []

    ok_sand, sand_reason, sand_snip = _hard_guard_testnet_trading()
    with _LOCK:
        _STATE["last_sandbox_status"] = sand_snip
        if not ok_sand:
            if _STATE.get("guard_first_failure_cycle_at") is None:
                _STATE["guard_first_failure_cycle_at"] = cycle_started
            _STATE["guard_last_failure_snapshot"] = copy.deepcopy(sand_snip)
            _STATE["last_guard_error_code"] = str(sand_reason)
        else:
            _STATE["guard_first_failure_cycle_at"] = None
            _STATE["guard_last_failure_snapshot"] = None
            _STATE["last_guard_error_code"] = None

    sandbox_guard_record: dict[str, Any] = {
        "ok": ok_sand,
        "reason": sand_reason,
        "diagnosis": sand_snip.get("diagnosis"),
        "enabled": sand_snip.get("enabled"),
        "configured": sand_snip.get("configured"),
        "sandbox_mode": sand_snip.get("sandbox_mode"),
        "urls_api_safe": sand_snip.get("urls_api_safe"),
        "can_read_balance": sand_snip.get("can_read_balance"),
        "can_read_ticker": sand_snip.get("can_read_ticker"),
        "message": sand_snip.get("message"),
        "balance_error": sand_snip.get("balance_error"),
        "ticker_error": sand_snip.get("ticker_error"),
    }
    if not ok_sand:
        errs.append(f"sandbox_guard:{sand_reason}")
        _log(f"abort ciclo: {sand_reason} snippet={sand_snip}")
        last_exit_block_reason = "guard_fail"
        with _LOCK:
            _STATE["last_action"] = f"abort:{sand_reason}"
    else:
        with _LOCK:
            loss_cap = float(_STATE["params"].get("max_daily_loss_usdt") or 10)
            daily_pnl = float(_STATE.get("auto_daily_pnl_usdt") or 0.0)

        if daily_pnl <= -loss_cap - 1e-9:
            msg = f"daily_loss_cap daily_pnl={daily_pnl:.4f} cap={-loss_cap:.4f}"
            errs.append(msg)
            _log(msg)
            with _LOCK:
                _STATE["enabled"] = False
                _STATE["stop_reason"] = "daily_loss_cap"
                _STATE["last_action"] = "auto_stopped:daily_loss_cap"
            actions.append({"type": "kill", "reason": "daily_loss_cap"})
        else:
            app_pos = get_testnet_app_positions()
            summary = app_pos.get("summary") if isinstance(app_pos.get("summary"), dict) else {}
            total_pnl = summary.get("total_pnl_usdt")
            try:
                total_pnl_f = float(total_pnl) if total_pnl is not None else None
            except (TypeError, ValueError):
                total_pnl_f = None
            with _LOCK:
                if total_pnl_f is not None and math.isfinite(total_pnl_f):
                    _STATE["last_app_total_pnl_usdt"] = round(total_pnl_f, 8)

            if not app_pos.get("ok"):
                errs.append(str(app_pos.get("error") or "app_positions_failed"))
                last_exit_block_reason = "no_app_position"
            else:
                # --- Salidas ---
                ok2, sand_reason2, _ = _hard_guard_testnet_trading()
                if not ok2:
                    errs.append(f"sandbox_guard_pre_exits:{sand_reason2}")
                    last_exit_block_reason = "guard_fail"
                else:
                    exit_payload = propose_testnet_exits(
                        stop_loss_pct=float(params["stop_loss_pct"]),
                        take_profit_pct=float(params["take_profit_pct"]),
                        trailing_stop_pct=float(params["trailing_stop_pct"]),
                        trailing_activation_pct=float(params["trailing_activation_pct"]),
                        min_value_usdt=float(params["min_exit_value_usdt"]),
                        break_even_trigger_pct=float(params["break_even_trigger_pct"]),
                        break_even_plus_pct=float(params["break_even_plus_pct"]),
                    )
                    if not exit_payload.get("ok"):
                        errs.append(str(exit_payload.get("error") or "exit_propose_failed"))
                        last_exit_block_reason = "proposal_missing"
                    else:
                        evaluated_raw = exit_payload.get("evaluated") or []
                        evaluated_list = [e for e in evaluated_raw if isinstance(e, dict)]
                        exit_scan_count = len(evaluated_list)
                        proposals = [p for p in (exit_payload.get("proposals") or []) if isinstance(p, dict)]
                        exit_proposals_count = len(proposals)
                        for ev in evaluated_list:
                            ev_out = {k: v for k, v in ev.items() if k != "proposal"}
                            exit_position_evaluations.append(ev_out)
                            br = ev.get("blocked_reason")
                            if last_exit_block_reason is None and br:
                                last_exit_block_reason = str(br)
                        if exit_proposals_count == 0 and last_exit_block_reason is None:
                            if exit_payload.get("balances_fetch_ok") is False:
                                last_exit_block_reason = "guard_fail"
                        for prop in proposals:
                            ok3, sand_reason3, _ = _hard_guard_testnet_trading()
                            if not ok3:
                                errs.append(f"sandbox_guard_pre_sell:{sand_reason3}")
                                last_exit_block_reason = "guard_fail"
                                break
                            sym = str(prop.get("symbol") or "").strip()
                            amt_base = prop.get("amount_base")
                            try:
                                amt_f = float(amt_base) if amt_base is not None else 0.0
                            except (TypeError, ValueError):
                                amt_f = 0.0
                            if not sym or amt_f <= 0:
                                actions.append(
                                    {
                                        "type": "sell_skip",
                                        "symbol": sym,
                                        "reason": "invalid_proposal",
                                        "blocked_reason": "proposal_missing",
                                    }
                                )
                                if last_exit_block_reason is None:
                                    last_exit_block_reason = "proposal_missing"
                                continue
                            exit_execution_attempted_count += 1
                            pnl_est = _estimate_sell_pnl_usdt(prop)
                            sell_ctx: dict[str, Any] = {
                                "order_origin": "auto_testnet",
                                "strategy_mode": str(params.get("strategy_mode") or ""),
                                "timeframe": str(params.get("timeframe") or ""),
                            }
                            er_sell = prop.get("exit_reason")
                            if er_sell:
                                sell_ctx["exit_reason"] = str(er_sell).strip()
                            sell_res = place_testnet_market_order(
                                sym,
                                "sell",
                                amount_base=amt_f,
                                max_quote_usdt=float(params.get("max_quote_per_order_usdt") or MAX_MARKET_ORDER_QUOTE_USDT),
                                order_context=sell_ctx,
                            )
                            rec = {
                                "type": "sell_market",
                                "symbol": sym,
                                "amount_base": amt_f,
                                "ok": bool(sell_res.get("ok")),
                                "error": sell_res.get("error"),
                                "exit_reason": prop.get("exit_reason"),
                                "blocked_reason": None if sell_res.get("ok") else "exchange_error",
                            }
                            actions.append(rec)
                            if sell_res.get("ok"):
                                exit_execution_success_count += 1
                                _log(
                                    f"SELL OK symbol={sym} base={amt_f} reason={prop.get('exit_reason')} "
                                    f"pnl_est={pnl_est}"
                                )
                                dpnl_out: float | None = None
                                with _LOCK:
                                    if pnl_est is not None and math.isfinite(pnl_est):
                                        _STATE["auto_daily_pnl_usdt"] = float(_STATE.get("auto_daily_pnl_usdt") or 0.0) + pnl_est
                                    _STATE["last_action"] = f"sell_market:{sym}:{prop.get('exit_reason')}"
                                    _save_counters_locked()
                                    loss_cap2 = float(_STATE["params"].get("max_daily_loss_usdt") or 10)
                                    dpnl_out = float(_STATE.get("auto_daily_pnl_usdt") or 0.0)
                                    if dpnl_out <= -loss_cap2 - 1e-9:
                                        _STATE["enabled"] = False
                                        _STATE["stop_reason"] = "daily_loss_cap"
                                        _STATE["last_action"] = "auto_stopped:daily_loss_cap_after_sell"
                                    still_go = bool(_STATE["enabled"])
                                actions.append({"type": "post_sell_guard", "daily_pnl": dpnl_out})
                                if not still_go:
                                    break
                            else:
                                exit_execution_error_count += 1
                                last_exit_block_reason = "exchange_error"
                                errs.append(f"sell_failed:{sym}:{sell_res.get('error')}")
                                with _LOCK:
                                    _STATE["last_action"] = f"sell_failed:{sym}"

                            with _LOCK:
                                if not _STATE["enabled"]:
                                    break

                # --- Entradas ---
                with _LOCK:
                    still_enabled = bool(_STATE["enabled"])
                    entries_ct = int(_STATE.get("auto_entries_today") or 0)
                    max_entries = int(_STATE["params"].get("max_trades_per_day") or 5)

                if still_enabled and entries_ct >= max_entries:
                    actions.append({"type": "entry_skip", "reason": "max_trades_per_day"})
                    with _LOCK:
                        _STATE["last_action"] = "skip_entry:max_trades_per_day"
                elif still_enabled:
                    ok4, sand_reason4, _ = _hard_guard_testnet_trading()
                    if not ok4:
                        errs.append(f"sandbox_guard_pre_entry:{sand_reason4}")
                    else:
                        app_pos2 = get_testnet_app_positions()
                        if not app_pos2.get("ok"):
                            errs.append(str(app_pos2.get("error") or "app_positions_failed_2"))
                        else:
                            exposure2 = _open_exposure_usdt(app_pos2)
                            max_exp = float(params["max_total_exposure_usdt"])
                            quote = float(params["quote_amount_usdt"])
                            if exposure2 + quote > max_exp + 1e-6:
                                actions.append(
                                    {
                                        "type": "entry_skip",
                                        "reason": "max_total_exposure",
                                        "exposure": exposure2,
                                        "quote": quote,
                                        "max": max_exp,
                                    }
                                )
                                with _LOCK:
                                    _STATE["last_action"] = "skip_entry:max_total_exposure"
                            else:
                                entry = propose_testnet_entry_from_strategy(
                                    timeframe=str(params.get("timeframe") or "30m"),
                                    limit=int(params.get("limit") or 200),
                                    quote_amount_usdt=float(params.get("quote_amount_usdt") or 15),
                                    stop_loss_pct=float(params["stop_loss_pct"]),
                                    take_profit_pct=float(params["take_profit_pct"]),
                                    trailing_stop_pct=float(params["trailing_stop_pct"]),
                                    max_open_positions=int(params["max_open_positions"]),
                                    break_even_trigger_pct=float(params["break_even_trigger_pct"]),
                                    break_even_plus_pct=float(params["break_even_plus_pct"]),
                                    cooldown_minutes=int(params["cooldown_minutes"]),
                                    require_btc_trend_up=bool(params.get("require_btc_trend_up")),
                                    min_entry_score=float(params.get("min_entry_score") or 0),
                                    strategy_mode=str(params.get("strategy_mode") or "daily_intraday"),
                                )
                                prop = entry.get("proposal") if isinstance(entry.get("proposal"), dict) else None
                                if prop and prop.get("symbol"):
                                    sym_b = str(prop["symbol"]).strip()
                                    q_buy = float(prop.get("quote_amount_usdt") or quote)
                                    ok5, sand_reason5, _ = _hard_guard_testnet_trading()
                                    if not ok5:
                                        errs.append(f"sandbox_guard_pre_buy:{sand_reason5}")
                                    else:
                                        buy_ctx: dict[str, Any] = {
                                            "order_origin": "auto_testnet",
                                            "strategy_mode": str(params.get("strategy_mode") or ""),
                                            "timeframe": str(params.get("timeframe") or ""),
                                        }
                                        st_prop = prop.get("setup_type")
                                        if st_prop:
                                            buy_ctx["setup_type"] = str(st_prop).strip()
                                        if prop.get("score") is not None:
                                            buy_ctx["entry_score"] = prop.get("score")
                                        buy_res = place_testnet_market_order(
                                            sym_b,
                                            "buy",
                                            quote_amount_usdt=q_buy,
                                            max_quote_usdt=float(params.get("max_quote_per_order_usdt") or MAX_MARKET_ORDER_QUOTE_USDT),
                                            order_context=buy_ctx,
                                        )
                                        actions.append(
                                            {
                                                "type": "buy_market",
                                                "symbol": sym_b,
                                                "quote_amount_usdt": q_buy,
                                                "ok": bool(buy_res.get("ok")),
                                                "error": buy_res.get("error"),
                                                "setup_type": buy_ctx.get("setup_type"),
                                                "entry_score": buy_ctx.get("entry_score"),
                                            }
                                        )
                                        if buy_res.get("ok"):
                                            _log(f"BUY OK symbol={sym_b} quote_usdt={q_buy}")
                                            with _LOCK:
                                                _STATE["auto_entries_today"] = int(_STATE.get("auto_entries_today") or 0) + 1
                                                _STATE["last_action"] = f"buy_market:{sym_b}"
                                                _save_counters_locked()
                                        else:
                                            errs.append(f"buy_failed:{sym_b}:{buy_res.get('error')}")
                                            with _LOCK:
                                                _STATE["last_action"] = f"buy_failed:{sym_b}"
                                else:
                                    actions.append(
                                        {
                                            "type": "no_entry",
                                            "primary_reason": entry.get("primary_reason"),
                                        }
                                    )
                                    with _LOCK:
                                        _STATE["last_action"] = f"no_entry:{entry.get('primary_reason')}"

    finished = _utc_now_iso()
    duration_ms = int((time.monotonic() - t0) * 1000)

    record = {
        "timestamp": finished,
        "cycle_started_at": cycle_started,
        "cycle_finished_at": finished,
        "duration_ms": duration_ms,
        "sandbox_guard": sandbox_guard_record,
        "sandbox_ok_initial": ok_sand,
        "sandbox_reason_initial": sand_reason,
        "sandbox_snippet": sand_snip,
        "actions_taken": actions,
        "errors": errs[:12],
        "params_snapshot": {k: params.get(k) for k in sorted(params.keys())},
        "exit_scan_count": exit_scan_count,
        "exit_proposals_count": exit_proposals_count,
        "exit_execution_attempted_count": exit_execution_attempted_count,
        "exit_execution_success_count": exit_execution_success_count,
        "exit_execution_error_count": exit_execution_error_count,
        "last_exit_block_reason": last_exit_block_reason,
        "exit_position_evaluations": exit_position_evaluations,
    }
    status = "error" if errs and not actions else "ok"
    if any(a.get("type") == "kill" for a in actions):
        status = "stopped_loss_cap"
    record["status"] = status

    try:
        _append_auto_cycle_record(record)
    except Exception as e:
        _log(f"cycle jsonl falló: {type(e).__name__}: {e}")

    with _LOCK:
        _STATE["running"] = False
        _STATE["last_run_at"] = finished
        _STATE["last_cycle_finished_at"] = finished
        _STATE["last_cycle_duration_ms"] = duration_ms
        _STATE["last_cycle_record"] = copy.deepcopy(record)
        _STATE["last_error"] = "; ".join(errs) if errs else None
        if _STATE["enabled"]:
            _schedule_next_run_locked(interval_sec)
        else:
            _STATE["next_run_at"] = None


def _worker_loop() -> None:
    global _THREAD
    _log("hilo auto testnet iniciado")
    try:
        while True:
            with _LOCK:
                if not _STATE["enabled"]:
                    break
                interval_sec = max(60, int(_STATE["interval_seconds"]))

            _run_cycle()

            with _LOCK:
                if not _STATE["enabled"]:
                    break
                interval_sec = max(60, int(_STATE["interval_seconds"]))

            _WAKE.wait(timeout=float(interval_sec))
            _WAKE.clear()
    finally:
        with _LOCK:
            _THREAD = None
            _STATE["running"] = False
            _STATE["next_run_at"] = None
        _log("hilo auto testnet terminado")


def start_testnet_auto(*, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Activa el auto runner; actualiza parámetros si ya estaba activo."""
    global _THREAD
    with _LOCK:
        prior = copy.deepcopy(_STATE.get("params") or {})
    merged_raw = _merge_params(prior, params)
    merged, audits = _clamp_params_with_audit(merged_raw)
    _log(
        f"start merge max_open={merged.get('max_open_positions')} max_trades_day={merged.get('max_trades_per_day')} "
        f"clamp_diffs={len(audits)}"
    )

    with _LOCK:
        _STATE["enabled"] = True
        _STATE["stop_reason"] = None
        _STATE["params"] = merged
        _STATE["last_params_request"] = copy.deepcopy(merged_raw)
        _STATE["params_clamp_audit"] = audits
        _reset_daily_counters_if_needed_locked()
        interval_sec = max(60, int(float(merged["cycle_interval_minutes"]) * 60))
        _STATE["interval_seconds"] = interval_sec
        _schedule_next_run_locked(interval_sec)
        need_spawn = _THREAD is None or not _THREAD.is_alive()

    _WAKE.set()

    if need_spawn:
        t = threading.Thread(target=_worker_loop, name="crypto-testnet-auto", daemon=True)
        with _LOCK:
            if _THREAD is None or not _THREAD.is_alive():
                _THREAD = t
                t.start()

    _log(f"start interval_s={interval_sec} mode={merged.get('strategy_mode')} tf={merged.get('timeframe')}")
    return get_testnet_auto_status()


def update_testnet_auto_params(*, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Actualiza parámetros en caliente sin reiniciar el hilo ni cambiar enabled.
    _run_cycle ya relee _STATE['params'] al inicio de cada ciclo.
    """
    with _LOCK:
        prior = copy.deepcopy(_STATE.get("params") or {})
    merged_raw = _merge_params(prior, params)
    merged, audits = _clamp_params_with_audit(merged_raw)
    changed = sorted([k for k in _DEFAULT_PARAMS if prior.get(k) != merged.get(k)])

    with _LOCK:
        _STATE["params"] = merged
        _STATE["last_params_request"] = copy.deepcopy(merged_raw)
        _STATE["params_clamp_audit"] = audits
        _STATE["params_last_update_at"] = _utc_now_iso()
        _STATE["params_last_update_changed_fields"] = copy.deepcopy(changed)
        new_interval = max(60, int(float(merged["cycle_interval_minutes"]) * 60))
        old_interval = max(60, int(_STATE.get("interval_seconds") or 300))
        if new_interval != old_interval:
            _STATE["interval_seconds"] = new_interval
            if _STATE.get("enabled"):
                _schedule_next_run_locked(new_interval)

    if changed:
        _log(
            f"update_params changed={changed} max_open={merged.get('max_open_positions')} "
            f"max_trades_day={merged.get('max_trades_per_day')} clamp_diffs={len(audits)}"
        )
    else:
        _log("update_params: sin cambios efectivos respecto al estado actual")

    _WAKE.set()
    return get_testnet_auto_status()


def stop_testnet_auto() -> dict[str, Any]:
    """Detiene el auto runner (kill switch)."""
    global _THREAD
    with _LOCK:
        _STATE["enabled"] = False
        _STATE["stop_reason"] = "user_stop"
    _WAKE.set()
    th: threading.Thread | None
    with _LOCK:
        th = _THREAD
    if th is not None and th.is_alive():
        th.join(timeout=20.0)
    _log("stop manual")
    return get_testnet_auto_status()


def _derive_auto_risk_status(ev: dict[str, Any], *, sl_pct: float, tp_pct: float) -> tuple[str, str | None]:
    """
    Estado UI agregado (no altera propose_testnet_exits):
    salida_sugerida | cerca_sl | cerca_tp | trailing_activo | holding | sin_evaluar
    """
    st = str(ev.get("status") or "")
    if st == "proposed":
        er = str(ev.get("exit_reason") or ev.get("reason") or "").strip() or None
        return "salida_sugerida", er
    if st == "skipped":
        return "sin_evaluar", str(ev.get("reason") or ev.get("message") or "").strip() or None

    def _f(x: Any) -> float | None:
        try:
            v = float(x)
            return v if math.isfinite(v) else None
        except (TypeError, ValueError):
            return None

    dsl = _f(ev.get("distance_to_stop_loss_pct"))
    dtp = _f(ev.get("distance_to_take_profit_pct"))
    near_sl_thr = max(0.05, float(sl_pct) * 0.35) if sl_pct > 0 else 0.05
    near_tp_thr = max(0.05, float(tp_pct) * 0.35) if tp_pct > 0 else 0.05
    if dsl is not None and dsl >= 0 and dsl <= near_sl_thr:
        return "cerca_sl", None
    if dtp is not None and dtp >= 0 and dtp <= near_tp_thr:
        return "cerca_tp", None

    hi_f = _f(ev.get("highest_price"))
    avg_f = _f(ev.get("avg_entry_price"))
    tr_f = _f(ev.get("trailing_stop_price"))
    pnl_f = _f(ev.get("pnl_pct"))
    if ev.get("trailing_activated") is True:
        return "trailing_activo", None
    if tr_f is not None and avg_f is not None and avg_f > 0 and hi_f is not None and hi_f > avg_f * 1.0002:
        if pnl_f is None or pnl_f > -1e-6:
            return "trailing_activo", None

    if st == "evaluated" or st == "holding":
        return "holding", None
    return "sin_evaluar", str(ev.get("reason") or st or "").strip() or None


def _open_position_risk_from_params(params: dict[str, Any]) -> dict[str, Any]:
    from services.crypto.binance_testnet import propose_testnet_exits

    p = _clamp_params(dict(params))
    try:
        payload = propose_testnet_exits(
            stop_loss_pct=float(p["stop_loss_pct"]),
            take_profit_pct=float(p["take_profit_pct"]),
            trailing_stop_pct=float(p["trailing_stop_pct"]),
            trailing_activation_pct=float(p["trailing_activation_pct"]),
            min_value_usdt=float(p["min_exit_value_usdt"]),
            break_even_trigger_pct=float(p["break_even_trigger_pct"]),
            break_even_plus_pct=float(p["break_even_plus_pct"]),
            persist_trailing_state=False,
        )
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "positions": [],
            "evaluated_at": _utc_now_iso(),
            "persist_trailing_state": False,
        }

    if not payload.get("ok"):
        return {
            "ok": False,
            "error": str(payload.get("error") or "exit_propose_failed"),
            "positions": [],
            "evaluated_at": _utc_now_iso(),
            "persist_trailing_state": False,
        }

    sl_pct = float(payload.get("stop_loss_pct") or 0)
    tp_pct = float(payload.get("take_profit_pct") or 0)
    rows: list[dict[str, Any]] = []
    for ev in payload.get("evaluated") or []:
        if not isinstance(ev, dict):
            continue
        sym = str(ev.get("symbol") or "").strip()
        if not sym:
            continue
        risk_status, risk_detail = _derive_auto_risk_status(ev, sl_pct=sl_pct, tp_pct=tp_pct)
        row: dict[str, Any] = {
            "symbol": sym,
            "asset": ev.get("asset"),
            "avg_entry_price": ev.get("avg_entry_price"),
            "current_price": ev.get("current_price"),
            "unrealized_pnl_pct": ev.get("pnl_pct") if ev.get("pnl_pct") is not None else ev.get("unrealized_pnl_pct"),
            "stop_loss_price": ev.get("stop_loss_price"),
            "take_profit_price": ev.get("take_profit_price"),
            "trailing_stop_price": ev.get("trailing_stop_price"),
            "trailing_activation_pct": ev.get("trailing_activation_pct"),
            "trailing_activated": ev.get("trailing_activated"),
            "max_favorable_pct": ev.get("max_favorable_pct"),
            "exit_rule_version": ev.get("exit_rule_version"),
            "break_even_price": ev.get("break_even_price"),
            "highest_price": ev.get("highest_price"),
            "distance_to_stop_loss_pct": ev.get("distance_to_stop_loss_pct"),
            "distance_to_take_profit_pct": ev.get("distance_to_take_profit_pct"),
            "exit_reason": ev.get("exit_reason") if str(ev.get("status") or "") == "proposed" else None,
            "position_status": ev.get("position_status"),
            "evaluation_status": ev.get("status"),
            "risk_status": risk_status,
            "risk_detail": risk_detail,
            "message": ev.get("message"),
            "stop_loss_pct": ev.get("stop_loss_pct"),
            "take_profit_pct": ev.get("take_profit_pct"),
            "free_balance_base": ev.get("free_balance_base"),
            "sell_amount_base": ev.get("sell_amount_base"),
            "eligible_for_auto_sell": ev.get("eligible_for_auto_sell"),
            "blocked_reason": ev.get("blocked_reason"),
            "take_profit_triggered": ev.get("take_profit_triggered"),
            "value_usdt": ev.get("value_usdt"),
        }
        rows.append(row)

    return {
        "ok": True,
        "error": None,
        "evaluated_at": _utc_now_iso(),
        "persist_trailing_state": False,
        "open_positions_count": int(payload.get("open_positions_count") or 0),
        "trailing_stop_pct_effective": payload.get("trailing_stop_pct_effective"),
        "trailing_activation_pct": payload.get("trailing_activation_pct"),
        "exit_rule_version": payload.get("exit_rule_version"),
        "balances_fetch_ok": payload.get("balances_fetch_ok"),
        "balances_fetch_error": payload.get("balances_fetch_error"),
        "positions": rows,
    }


def _guard_advice_text(error_code: str | None, snapshot: dict[str, Any] | None) -> str | None:
    """Texto UI (no relaja la guarda): orienta según último fallo del ciclo."""
    if not error_code:
        return None
    ec = str(error_code).strip()
    snap = snapshot if isinstance(snapshot, dict) else {}
    diag = str(snap.get("diagnosis") or "").strip()
    bal_err = str(snap.get("balance_error") or "").strip()
    tick_err = str(snap.get("ticker_error") or "").strip()

    if ec.startswith("diagnosis_not_ok:") and diag == "keys_or_permissions":
        parts = [
            "El guardia detuvo el auto: en testnet el ticker responde pero la lectura de balance falla (típico de API keys,"
            " permisos de lectura, IP whitelist o claves expiradas en testnet.binance.vision).",
            "Revisá credenciales/permisos Testnet o regenerá claves si expiraron.",
        ]
        if bal_err:
            parts.append(f"Detalle balance: {bal_err}")
        return " ".join(parts)

    if ec == "cannot_read_balance":
        msg = "No se pudo leer balance testnet; sin balance no se opera. Revisá permisos de la API key y el error devuelto por el exchange."
        return f"{msg} {('Detalle: ' + bal_err) if bal_err else ''}".strip()

    if ec.startswith("diagnosis_not_ok:"):
        return (
            f"Diagnosis testnet «{diag or ec}»: el auto no opera hasta que el estado vuelva a diagnosis=ok "
            f"(ver Estado testnet). {('Balance: ' + bal_err) if bal_err else ''} {('Ticker: ' + tick_err) if tick_err else ''}"
        ).strip()

    if "urls_api_safe" in ec or ec.startswith("urls_api_safe_unsafe"):
        return "URLs del cliente no clasificadas como sandbox/testnet; no se reactiva trading hasta corregir configuración ccxt."

    if ec == "testnet_disabled":
        return "Testnet deshabilitado por configuración (BINANCE_TESTNET_ENABLED)."

    if ec == "testnet_not_configured":
        return "Faltan API key/secret de testnet en .env."

    if ec == "sandbox_mode_not_detected":
        return "Sandbox mode no detectado en el exchange ccxt; revisá que sólo se use Binance Spot Testnet."

    return f"Guardia sandbox: «{ec}». Corregí el estado testnet antes de reactivar el auto."


def get_testnet_auto_status() -> dict[str, Any]:
    from services.crypto.binance_testnet import get_testnet_app_positions

    with _LOCK:
        guard_snap = copy.deepcopy(_STATE.get("guard_last_failure_snapshot"))
        guard_code = _STATE.get("last_guard_error_code")
        out = {
            "ok": True,
            "enabled": bool(_STATE["enabled"]),
            "running": bool(_STATE["running"]),
            "stop_reason": _STATE.get("stop_reason"),
            "last_run_at": _STATE.get("last_run_at"),
            "next_run_at": _STATE.get("next_run_at"),
            "last_error": _STATE.get("last_error"),
            "last_action": _STATE.get("last_action"),
            "last_cycle_started_at": _STATE.get("last_cycle_started_at"),
            "last_cycle_finished_at": _STATE.get("last_cycle_finished_at"),
            "last_cycle_duration_ms": _STATE.get("last_cycle_duration_ms"),
            "interval_seconds": int(_STATE.get("interval_seconds") or 300),
            "params": copy.deepcopy(_STATE.get("params") or {}),
            "utc_day": _STATE.get("utc_day"),
            "auto_entries_today": int(_STATE.get("auto_entries_today") or 0),
            "auto_daily_pnl_usdt": float(_STATE.get("auto_daily_pnl_usdt") or 0.0),
            "last_sandbox_status": copy.deepcopy(_STATE.get("last_sandbox_status")),
            "last_cycle_record": copy.deepcopy(_STATE.get("last_cycle_record")),
            "guard_first_failure_cycle_at": _STATE.get("guard_first_failure_cycle_at"),
            "guard_last_failure_snapshot": guard_snap,
            "last_guard_error_code": guard_code,
            "last_params_request": copy.deepcopy(_STATE.get("last_params_request")),
            "params_clamp_audit": copy.deepcopy(_STATE.get("params_clamp_audit") or []),
            "guard_advice": _guard_advice_text(
                str(guard_code) if guard_code is not None else None,
                guard_snap if isinstance(guard_snap, dict) else None,
            ),
            "params_last_update_at": _STATE.get("params_last_update_at"),
            "params_last_update_changed_fields": copy.deepcopy(_STATE.get("params_last_update_changed_fields") or []),
        }

    try:
        app = get_testnet_app_positions()
        if app.get("ok"):
            summ = app.get("summary") if isinstance(app.get("summary"), dict) else {}
            out["app_total_pnl_usdt"] = summ.get("total_pnl_usdt")
            out["app_realized_pnl_usdt"] = app.get("realized_pnl_usdt")
            out["app_unrealized_pnl_usdt"] = summ.get("total_unrealized_pnl_usdt")
        else:
            out["app_positions_error"] = str(app.get("error") or "unknown")
    except Exception as e:
        out["app_positions_error"] = f"{type(e).__name__}: {e}"

    merged_risk = dict(_DEFAULT_PARAMS)
    if isinstance(out.get("params"), dict):
        merged_risk.update(out["params"])
    out["open_position_risk"] = _open_position_risk_from_params(_clamp_params(merged_risk))
    out["auto_position_risk"] = out["open_position_risk"]

    return out


def get_testnet_auto_cycles(*, limit: int = 50) -> dict[str, Any]:
    lim = max(1, min(int(limit), 500))
    if not _AUTO_CYCLES_JSONL.is_file():
        return {"ok": True, "cycles": [], "total": 0}
    try:
        lines = _AUTO_CYCLES_JSONL.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        return {"ok": False, "error": str(e), "cycles": [], "total": 0}
    total = 0
    parsed: list[dict[str, Any]] = []
    for line in lines[-_AUTO_CYCLES_READ_CAP:]:
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
