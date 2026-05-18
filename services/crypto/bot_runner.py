"""
Ciclo bot paper cripto: escaneo, gestión de riesgo y ejecución simulada.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from services.crypto.strategy_modes import (
    DAILY_SETUP_TYPES,
    STRATEGY_MODE_DAILY_INTRADAY,
    STRATEGY_MODE_TREND_SWING,
    normalize_strategy_mode,
    is_entry_candidate_row,
)

_LOG_PREFIX = "[CRYPTO_BOT]"
_SCAN_DEBUG_PREFIX = "[CRYPTO_BOT_SCAN_DEBUG]"

BTC_SYMBOL = "BTC/USDT"

# Campo exacto que usa evaluate_entry_candidates (sin cambiar reglas de trading).
ENTRY_CANDIDATE_SIGNAL_FIELD = "signal"
ENTRY_CANDIDATE_SIGNAL_VALUE = "compra_potencial"


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _log_scan_debug(msg: str) -> None:
    print(f"{_SCAN_DEBUG_PREFIX} {msg}", flush=True)


def log_scan_debug_snapshot(
    *,
    timeframe: str,
    limit: int,
    watchlist_count: int,
    watchlist_sample: list[str],
    scan_type: str,
    scan_results: list[dict[str, Any]],
    candidates_count: int,
    scan_error: str | None,
    scan_duration_ms: int,
    context: str = "execute_paper_strategy",
    strategy_mode: str | None = None,
) -> dict[str, Any]:
    """Log + dict reutilizable para last_scan_debug (sin alterar trading)."""
    scan_ok_count, scan_error_count = _scan_ok_error_counts(scan_results)
    scanned_count = len(scan_results)
    diagnosis = _scan_diagnosis_before_filters(
        watchlist_count=watchlist_count,
        scanned_count=scanned_count,
        scan_ok_count=scan_ok_count,
        candidates_count=candidates_count,
        scan_error=scan_error,
    )
    sample = watchlist_sample[:5] if watchlist_sample else _first_symbols_sample(scan_results, 5)
    breakdown_preview = _build_scan_signal_breakdown(scan_results)
    scenario_preview = _derive_scan_scenario(
        watchlist_count=watchlist_count,
        scan_count=scanned_count,
        scan_ok_count=scan_ok_count,
        candidates_count=candidates_count,
        scan_error=scan_error,
        breakdown=breakdown_preview,
        strategy_mode=strategy_mode,
    )
    _log_scan_debug(
        f"context={context} timeframe={timeframe!r} limit={limit} "
        f"watchlist_count={watchlist_count} watchlist_sample={sample} "
        f"scan_type={scan_type} scan_count={scanned_count} "
        f"scan_ok_count={scan_ok_count} scan_error_count={scan_error_count} "
        f"candidates_count={candidates_count} scan_duration_ms={scan_duration_ms} "
        f"scan_error={scan_error!r} scan_diagnosis={diagnosis} "
        f"scenario={scenario_preview.get('scan_scenario')} "
        f"unique_signals={breakdown_preview.get('unique_signals_detected')} "
        f"rows_compra={breakdown_preview.get('rows_signal_compra_potencial')} "
        f"rows_other_signal={breakdown_preview.get('rows_signal_other')} "
        f"entry_filter=row[{ENTRY_CANDIDATE_SIGNAL_FIELD!r}]=={ENTRY_CANDIDATE_SIGNAL_VALUE!r}"
    )
    mode = normalize_strategy_mode(strategy_mode)
    dbg = _build_scan_debug(
        scan_results,
        watchlist_count=watchlist_count,
        candidates_count=candidates_count,
        scan_duration_ms=scan_duration_ms,
        scan_error=scan_error,
        strategy_mode=mode,
    )
    dbg["timeframe"] = timeframe
    dbg["limit"] = limit
    dbg["watchlist_sample"] = sample
    dbg["scan_type"] = scan_type
    dbg["strategy_mode"] = mode
    return dbg


def _norm_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper()


def _is_btc_symbol(symbol: str) -> bool:
    s = _norm_symbol(symbol)
    return s == BTC_SYMBOL or s.replace("/", "") == "BTCUSDT"


def _scan_by_symbol(scan_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in scan_results:
        if isinstance(r, dict):
            sym = _norm_symbol(str(r.get("symbol") or ""))
            if sym:
                out[sym] = r
    return out


def _parse_iso_utc(ts: str) -> datetime | None:
    raw = (ts or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _symbol_in_cooldown(symbol: str, trades: list[Any], cooldown_minutes: int) -> bool:
    if cooldown_minutes <= 0:
        return False
    sym = _norm_symbol(symbol)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=int(cooldown_minutes))
    for t in trades:
        if not isinstance(t, dict):
            continue
        if _norm_symbol(str(t.get("symbol") or "")) != sym:
            continue
        dt = _parse_iso_utc(str(t.get("exit_time") or ""))
        if dt is not None and dt >= cutoff:
            return True
    return False


def _has_open_position(symbol: str, pf: dict[str, Any]) -> bool:
    sym = _norm_symbol(symbol)
    for p in pf.get("positions") or []:
        if not isinstance(p, dict):
            continue
        if str(p.get("status", "open")) != "open":
            continue
        if _norm_symbol(str(p.get("symbol") or "")) == sym:
            return True
    return False


def _btc_trend_favorable(scan_by_sym: dict[str, dict[str, Any]]) -> bool:
    row = scan_by_sym.get(BTC_SYMBOL)
    if not row or row.get("error"):
        return False
    return str(row.get("trend") or "").strip().lower() == "alcista"


def _evaluated_row(
    row: dict[str, Any],
    *,
    status: str,
    reason: str,
    rejection_reason: str | None = None,
    btc_context: str | None = None,
) -> dict[str, Any]:
    from services.crypto.candidate_diagnostics import build_candidate_opportunity_diagnostic

    price = row.get("price")
    rej = rejection_reason or reason
    btc_ctx = btc_context if btc_context is not None else row.get("btc_context")
    diag = build_candidate_opportunity_diagnostic(
        row,
        btc_context=btc_ctx if isinstance(btc_ctx, str) else None,
        evaluation_status=status,
        evaluation_reason=rej,
    )
    return {
        "symbol": row.get("symbol"),
        "signal": row.get("signal"),
        "score": row.get("score"),
        "status": status,
        "reason": reason,
        "rejection_reason": rej,
        "price": price if price is None or isinstance(price, (int, float)) else None,
        **diag,
    }


def _should_apply_btc_entry_filter(
    *,
    require_btc_trend_up: bool,
    strategy_mode: str,
    row: dict[str, Any],
) -> bool:
    if not require_btc_trend_up:
        return False
    if normalize_strategy_mode(strategy_mode) == STRATEGY_MODE_DAILY_INTRADAY:
        setup = row.get("setup_type")
        if setup in ("pullback", "rebound", "reversal_controlled"):
            return False
    return True


def evaluate_entry_candidates(
    scan_results: list[dict[str, Any]],
    strategy_mode: str | None = None,
) -> list[dict[str, Any]]:
    """Candidatos según strategy_mode (trend_swing: compra_potencial; daily: + setups)."""
    mode = normalize_strategy_mode(strategy_mode)
    out = [r for r in scan_results if isinstance(r, dict) and is_entry_candidate_row(r, mode)]
    _log(
        f"evaluate_entry_candidates mode={mode}: {len(out)} candidatos "
        f"(trend: signal==compra_potencial; daily: + setup_type entry_eligible)"
    )
    return out


def evaluate_open_positions(portfolio: dict[str, Any]) -> list[dict[str, Any]]:
    """Revisión de posiciones abiertas enriquecidas."""
    positions = portfolio.get("positions") or []
    review: list[dict[str, Any]] = []
    for p in positions:
        if not isinstance(p, dict):
            continue
        review.append(
            {
                "id": p.get("id"),
                "symbol": p.get("symbol"),
                "quantity": p.get("quantity"),
                "amount_usdt": p.get("amount_usdt"),
                "entry_price": p.get("entry_price"),
                "stop_loss": p.get("stop_loss"),
                "take_profit": p.get("take_profit"),
                "trailing_stop_pct": p.get("trailing_stop_pct"),
                "highest_price": p.get("highest_price"),
                "break_even_active": p.get("break_even_active"),
                "exit_policy": p.get("exit_policy"),
                "current_price": p.get("current_price"),
                "unrealized_pnl_usdt": p.get("unrealized_pnl_usdt"),
                "unrealized_pnl_pct": p.get("unrealized_pnl_pct"),
                "price_error": p.get("price_error"),
            }
        )
    _log(f"evaluate_open_positions: {len(review)} posiciones")
    return review


def _cycle_message_search(
    scanned_count: int,
    candidates_count: int,
    *,
    strategy_mode: str | None = None,
) -> str:
    from services.crypto.strategy_modes import message_cycle_search_complete

    if candidates_count == 0:
        return "Sin oportunidades válidas en la watchlist actual."
    return message_cycle_search_complete(
        strategy_mode=strategy_mode,
        candidates_count=candidates_count,
        scanned_count=scanned_count,
    )


def _primary_no_entry_reason(
    evaluated: list[dict[str, Any]],
    *,
    had_candidates: bool,
) -> str | None:
    if not had_candidates:
        return "no_opportunity"
    for ev in evaluated:
        reason = str(ev.get("reason") or "")
        status = str(ev.get("status") or "")
        if status in ("rejected", "skipped") and reason:
            return reason
    return "no_entry"


def _first_symbols_sample(scan_results: list[dict[str, Any]], n: int = 5) -> list[str]:
    out: list[str] = []
    for row in scan_results:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip()
        if sym:
            out.append(sym)
        if len(out) >= n:
            break
    return out


def _scan_ok_error_counts(scan_results: list[dict[str, Any]]) -> tuple[int, int]:
    ok = 0
    err = 0
    for row in scan_results:
        if not isinstance(row, dict):
            continue
        if row.get("error"):
            err += 1
        else:
            ok += 1
    return ok, err


def _signal_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _build_scan_signal_breakdown(scan_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Conteos por fila de scan (diagnóstico; no altera evaluate_entry_candidates)."""
    total_scan_rows = 0
    rows_with_error = 0
    rows_with_signal = 0
    rows_signal_compra_potencial = 0
    rows_signal_compra_case_mismatch = 0
    rows_signal_other = 0
    rows_missing_signal = 0
    rows_high_score_not_compra = 0
    rows_action_compra_potencial = 0
    rows_recommendation_compra_potencial = 0
    signal_counts: dict[str, int] = {}
    unique_signals: set[str] = set()
    sample_rows: list[dict[str, Any]] = []

    for row in scan_results:
        if not isinstance(row, dict):
            continue
        total_scan_rows += 1
        sym = row.get("symbol")
        err = row.get("error")
        if err:
            rows_with_error += 1
            if len(sample_rows) < 5:
                sample_rows.append(
                    {
                        "symbol": sym,
                        "signal": None,
                        "action": row.get("action"),
                        "score": row.get("score"),
                        "trend": row.get("trend"),
                        "price": row.get("price"),
                        "error": str(err)[:160],
                    }
                )
            continue

        sig = _signal_str(row.get("signal"))
        action = _signal_str(row.get("action"))
        rec = _signal_str(row.get("recommendation"))
        tipo = _signal_str(row.get("tipo"))
        score = row.get("score")
        try:
            score_f = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_f = None

        if sig:
            rows_with_signal += 1
            unique_signals.add(sig)
            signal_counts[sig] = signal_counts.get(sig, 0) + 1
            if sig == ENTRY_CANDIDATE_SIGNAL_VALUE:
                rows_signal_compra_potencial += 1
            elif sig.lower() == ENTRY_CANDIDATE_SIGNAL_VALUE:
                rows_signal_compra_case_mismatch += 1
                rows_signal_other += 1
            else:
                rows_signal_other += 1
        else:
            rows_missing_signal += 1

        if action == ENTRY_CANDIDATE_SIGNAL_VALUE or (
            action and action.lower() == ENTRY_CANDIDATE_SIGNAL_VALUE
        ):
            rows_action_compra_potencial += 1
        if rec == ENTRY_CANDIDATE_SIGNAL_VALUE or (
            rec and rec.lower() == ENTRY_CANDIDATE_SIGNAL_VALUE
        ):
            rows_recommendation_compra_potencial += 1

        if (
            score_f is not None
            and score_f >= 70
            and sig != ENTRY_CANDIDATE_SIGNAL_VALUE
        ):
            rows_high_score_not_compra += 1

        if len(sample_rows) < 5:
            sample_rows.append(
                {
                    "symbol": sym,
                    "signal": sig,
                    "action": action,
                    "recommendation": rec,
                    "tipo": tipo,
                    "score": score,
                    "trend": row.get("trend"),
                    "price": row.get("price"),
                    "error": None,
                }
            )

    return {
        "total_scan_rows": total_scan_rows,
        "rows_with_error": rows_with_error,
        "rows_ok": total_scan_rows - rows_with_error,
        "rows_with_signal": rows_with_signal,
        "rows_signal_compra_potencial": rows_signal_compra_potencial,
        "rows_signal_compra_case_mismatch": rows_signal_compra_case_mismatch,
        "rows_signal_other": rows_signal_other,
        "rows_missing_signal": rows_missing_signal,
        "rows_high_score_not_compra": rows_high_score_not_compra,
        "rows_action_compra_potencial": rows_action_compra_potencial,
        "rows_recommendation_compra_potencial": rows_recommendation_compra_potencial,
        "unique_signals_detected": sorted(unique_signals),
        "signal_counts": signal_counts,
        "sample_rows": sample_rows,
        "entry_candidate_filter": {
            "field": ENTRY_CANDIDATE_SIGNAL_FIELD,
            "expected_exact": ENTRY_CANDIDATE_SIGNAL_VALUE,
            "requires_no_error": True,
            "fields_not_used_for_entry": [
                "action",
                "recommendation",
                "tipo",
                "SignalState",
            ],
            "note": (
                "evaluate_entry_candidates: row['signal'] == 'compra_potencial' "
                "(comparación exacta; filas con error excluidas)"
            ),
        },
        "evaluated_count_note": (
            "evaluated_count solo se incrementa al evaluar candidatos compra_potencial "
            "con filtros de entrada (score mín., BTC, cooldown, etc.). "
            "Si candidates_count=0, evaluated queda vacío y evaluated_count=0 es esperado."
        ),
    }


def _derive_scan_scenario(
    *,
    watchlist_count: int,
    scan_count: int,
    scan_ok_count: int,
    candidates_count: int,
    scan_error: str | None,
    breakdown: dict[str, Any],
    strategy_mode: str | None = None,
) -> dict[str, str]:
    """A=scanner OK sin candidatos; B=scanner no corre; C=posible desajuste filtro/campo."""
    from services.crypto.strategy_modes import (
        scan_scenario_candidates_ok_label,
        scan_scenario_no_candidate_label,
    )

    mode = normalize_strategy_mode(strategy_mode)
    if scan_error or watchlist_count <= 0 or scan_count == 0:
        return {
            "scan_scenario": "B",
            "scan_scenario_label": "Scanner no corrió o sin filas",
            "scan_scenario_detail": scan_error or "scan_count=0",
        }
    if scan_ok_count == 0:
        return {
            "scan_scenario": "B",
            "scan_scenario_label": "Scanner sin filas OK",
            "scan_scenario_detail": "Todas las filas con error (fetch/análisis)",
        }

    compra = int(breakdown.get("rows_signal_compra_potencial") or 0)
    case_mm = int(breakdown.get("rows_signal_compra_case_mismatch") or 0)
    action_cp = int(breakdown.get("rows_action_compra_potencial") or 0)
    rec_cp = int(breakdown.get("rows_recommendation_compra_potencial") or 0)

    if candidates_count > 0:
        if compra == candidates_count:
            return {
                "scan_scenario": "OK",
                "scan_scenario_label": scan_scenario_candidates_ok_label(mode),
                "scan_scenario_detail": f"{candidates_count} fila(s) pasan el filtro de señal",
            }
        return {
            "scan_scenario": "C",
            "scan_scenario_label": "Desajuste breakdown vs candidatos",
            "scan_scenario_detail": (
                f"rows_signal_compra_potencial={compra} pero candidates_count={candidates_count}"
            ),
        }

    if case_mm > 0 or (action_cp > 0 and compra == 0) or (rec_cp > 0 and compra == 0):
        return {
            "scan_scenario": "C",
            "scan_scenario_label": "Señal en otro campo o distinto casing",
            "scan_scenario_detail": (
                f"case_mismatch={case_mm} action={action_cp} recommendation={rec_cp}; "
                f"el bot solo lee row[{ENTRY_CANDIDATE_SIGNAL_FIELD!r}] "
                f"== {ENTRY_CANDIDATE_SIGNAL_VALUE!r}"
            ),
        }

    if compra > 0:
        return {
            "scan_scenario": "C",
            "scan_scenario_label": "compra_potencial en filas pero candidates=0",
            "scan_scenario_detail": "Revisar evaluate_entry_candidates vs breakdown",
        }

    unique = breakdown.get("unique_signals_detected") or []
    high = int(breakdown.get("rows_high_score_not_compra") or 0)
    return {
        "scan_scenario": "A",
        "scan_scenario_label": scan_scenario_no_candidate_label(mode),
        "scan_scenario_detail": (
            f"señales detectadas: {unique}; filas score>=70 sin compra_potencial: {high}"
        ),
    }


def _scan_diagnosis_before_filters(
    *,
    watchlist_count: int,
    scanned_count: int,
    scan_ok_count: int,
    candidates_count: int,
    scan_error: str | None,
) -> str:
    if scan_error:
        return "scanner_error"
    if watchlist_count <= 0:
        return "watchlist_empty"
    if scanned_count == 0:
        return "scanner_empty"
    if scan_ok_count == 0:
        return "scanner_error"
    if candidates_count == 0:
        return "no_opportunity"
    return "candidates_present"


def _build_scan_debug(
    scan_results: list[dict[str, Any]],
    *,
    watchlist_count: int,
    candidates_count: int,
    scan_duration_ms: int,
    scan_error: str | None,
    strategy_mode: str | None = None,
) -> dict[str, Any]:
    scanned_count = len(scan_results)
    scan_ok_count, scan_error_count = _scan_ok_error_counts(scan_results)
    diagnosis = _scan_diagnosis_before_filters(
        watchlist_count=watchlist_count,
        scanned_count=scanned_count,
        scan_ok_count=scan_ok_count,
        candidates_count=candidates_count,
        scan_error=scan_error,
    )
    breakdown = _build_scan_signal_breakdown(scan_results)
    daily_setups: dict[str, int] = {}
    for row in scan_results:
        if not isinstance(row, dict) or row.get("error"):
            continue
        st = row.get("setup_type")
        if st:
            daily_setups[str(st)] = daily_setups.get(str(st), 0) + 1
    scenario = _derive_scan_scenario(
        watchlist_count=watchlist_count,
        scan_count=scanned_count,
        scan_ok_count=scan_ok_count,
        candidates_count=candidates_count,
        scan_error=scan_error,
        breakdown=breakdown,
        strategy_mode=strategy_mode,
    )
    out: dict[str, Any] = {
        "watchlist_count": int(watchlist_count),
        "scan_count": int(scanned_count),
        "scan_ok_count": int(scan_ok_count),
        "scan_error_count": int(scan_error_count),
        "candidates_count": int(candidates_count),
        "scan_error": scan_error,
        "scan_duration_ms": int(scan_duration_ms),
        "first_symbols_sample": _first_symbols_sample(scan_results),
        "scan_diagnosis": diagnosis,
        "strategy_mode": normalize_strategy_mode(strategy_mode),
        "daily_setup_counts": daily_setups,
        **breakdown,
        **scenario,
    }
    return out


def _strategy_result_base(
    *,
    timeframe: str,
    limit: int,
    amount_usdt: float,
    scan_debug: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    """Campos comunes en todas las respuestas de execute_paper_strategy."""
    out: dict[str, Any] = {
        "timeframe": timeframe,
        "limit": limit,
        "amount_usdt": float(amount_usdt),
        "scanned_count": scan_debug.get("scan_count", 0),
        "scan_debug": scan_debug,
        "watchlist_count": scan_debug.get("watchlist_count"),
        "scan_count": scan_debug.get("scan_count"),
        "evaluated_count": 0,
        "scan_error": scan_debug.get("scan_error"),
        "scan_duration_ms": scan_debug.get("scan_duration_ms"),
        "first_symbols_sample": scan_debug.get("first_symbols_sample") or [],
        "scan_scenario": scan_debug.get("scan_scenario"),
        "scan_signal_breakdown": {
            k: scan_debug.get(k)
            for k in (
                "total_scan_rows",
                "rows_signal_compra_potencial",
                "rows_signal_other",
                "rows_missing_signal",
                "unique_signals_detected",
                "signal_counts",
                "sample_rows",
                "entry_candidate_filter",
            )
            if k in scan_debug
        },
    }
    out.update(extra)
    ev = extra.get("evaluated")
    if isinstance(ev, list):
        out["evaluated_count"] = len([e for e in ev if isinstance(e, dict)])
    return out


def run_crypto_paper_cycle(
    timeframe: str = "1h",
    limit: int = 200,
    strategy_mode: str | None = None,
) -> dict[str, Any]:
    """Escanea watchlist completa vía scan_crypto_watchlist; sin aperturas."""
    from services.crypto.paper_portfolio import (
        get_paper_portfolio,
        load_portfolio,
        paper_position_limits_snapshot,
    )
    from services.crypto.watchlist import scan_crypto_watchlist

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    mode = normalize_strategy_mode(strategy_mode)
    _log(f"run_crypto_paper_cycle: inicio timeframe={tf} limit={lim} mode={mode}")

    pf_snap = load_portfolio()
    position_limits = paper_position_limits_snapshot(3, pf_snap, evaluated=[])

    scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim, strategy_mode=mode)
    scanned_count = len(scan_results)
    raw_candidates = evaluate_entry_candidates(scan_results, strategy_mode=mode)
    from services.crypto.candidate_diagnostics import enrich_entry_candidates

    candidates = enrich_entry_candidates(
        raw_candidates,
        scan_results,
        strategy_mode=mode,
        scan_by_sym=_scan_by_symbol(scan_results),
    )
    candidates_count = len(candidates)
    portfolio = get_paper_portfolio()
    positions_review = evaluate_open_positions(portfolio)

    message = _cycle_message_search(scanned_count, candidates_count, strategy_mode=mode)
    _log(
        f"run_crypto_paper_cycle: fin scanned_count={scanned_count} "
        f"candidates_count={candidates_count}"
    )
    return {
        "timeframe": tf,
        "limit": lim,
        "strategy_mode": mode,
        "scanned_count": scanned_count,
        "candidates_count": candidates_count,
        "opened_count": 0,
        "message": message,
        "candidates": candidates,
        "candidate_opportunities": candidates,
        "evaluated": [],
        "primary_reason": None,
        "positions_review": positions_review,
        "actions": [],
        "position_limits": position_limits,
    }


def execute_paper_strategy(
    timeframe: str = "1h",
    limit: int = 200,
    amount_usdt: float = 100.0,
    stop_loss_pct: float = 2.0,
    take_profit_pct: float = 4.0,
    trailing_stop_pct: float = 1.5,
    max_open_positions: int = 3,
    break_even_trigger_pct: float = 0.0,
    break_even_plus_pct: float = 0.0,
    cooldown_minutes: int = 0,
    require_btc_trend_up: bool = False,
    min_entry_score: float = 0.0,
    strategy_mode: str | None = None,
) -> dict[str, Any]:
    """
    Revisa salidas, escanea watchlist y abre como máximo 1 posición nueva por ejecución.
    """
    import math

    from services.crypto.paper_portfolio import (
        _count_open_positions,
        get_paper_portfolio,
        list_open_paper_position_symbols,
        load_portfolio,
        paper_position_limits_snapshot,
        open_paper_position_market_by_amount,
        review_paper_positions_for_exit,
    )
    from services.crypto.watchlist import get_crypto_watchlist, scan_crypto_watchlist

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    mode = normalize_strategy_mode(strategy_mode)
    watchlist_symbols = get_crypto_watchlist()
    watchlist_count = len(watchlist_symbols)

    if not math.isfinite(amount_usdt) or amount_usdt <= 0:
        bad_dbg = log_scan_debug_snapshot(
            timeframe=tf,
            limit=lim,
            watchlist_count=watchlist_count,
            watchlist_sample=watchlist_symbols,
            scan_type="not_run_invalid_amount",
            scan_results=[],
            candidates_count=0,
            scan_error=f"amount_usdt inválido: {amount_usdt!r}",
            scan_duration_ms=0,
            context="execute_paper_strategy_precheck",
        )
        bad_dbg["scan_diagnosis"] = "strategy_precheck_failed"
        raise ValueError("amount_usdt debe ser > 0") from None

    max_pos = max(1, int(max_open_positions))
    cooldown_m = max(0, int(cooldown_minutes))
    min_score = float(min_entry_score) if math.isfinite(min_entry_score) and min_entry_score > 0 else 0.0

    _log(
        f"execute_paper_strategy: inicio mode={mode} timeframe={tf} limit={lim} max_open={max_pos} "
        f"cooldown={cooldown_m} btc_filter={require_btc_trend_up} min_score={min_score} "
        f"watchlist_count={watchlist_count}"
    )

    actions: list[dict[str, Any]] = list(review_paper_positions_for_exit())

    scan_error: str | None = None
    scan_results: list[dict[str, Any]] = []
    t_scan = time.monotonic()
    try:
        scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim, strategy_mode=mode)
    except Exception as e:
        scan_error = f"{type(e).__name__}: {e}"
        _log(f"execute: scan_crypto_watchlist falló {scan_error}")
    scan_duration_ms = int((time.monotonic() - t_scan) * 1000)

    scanned_count = len(scan_results)
    if watchlist_count > 0 and scanned_count == 0 and not scan_error:
        scan_error = (
            "scan_crypto_watchlist devolvió lista vacía con watchlist no vacía "
            "(revisar import watchlist o logs [CRYPTO_SCAN])"
        )

    scan_by_sym = _scan_by_symbol(scan_results)
    raw_candidates = evaluate_entry_candidates(scan_results, strategy_mode=mode)
    from services.crypto.candidate_diagnostics import enrich_entry_candidates

    candidates = enrich_entry_candidates(
        raw_candidates,
        scan_results,
        strategy_mode=mode,
        scan_by_sym=scan_by_sym,
    )
    candidates_count = len(candidates)
    scan_debug = log_scan_debug_snapshot(
        timeframe=tf,
        limit=lim,
        watchlist_count=watchlist_count,
        watchlist_sample=watchlist_symbols,
        scan_type="scan_crypto_watchlist",
        scan_results=scan_results,
        candidates_count=candidates_count,
        scan_error=scan_error,
        scan_duration_ms=scan_duration_ms,
        strategy_mode=mode,
    )
    scan_debug["timeframe"] = tf
    scan_debug["limit"] = lim

    pf = load_portfolio()
    trades = pf.get("trades") or []
    open_count = _count_open_positions(pf)
    open_symbols = list_open_paper_position_symbols(pf)
    opened_count = 0
    evaluated: list[dict[str, Any]] = []
    primary_reason: str | None = None

    _log(
        f"execute: position_limits open_count={open_count} max_open_positions={max_pos} "
        f"open_symbols={open_symbols} (paper JSON status=open; evaluate_entry_candidates no aplica este tope)"
    )

    if not candidates:
        portfolio = get_paper_portfolio()
        primary_reason = _scan_diagnosis_before_filters(
            watchlist_count=watchlist_count,
            scanned_count=scanned_count,
            scan_ok_count=int(scan_debug.get("scan_ok_count") or 0),
            candidates_count=0,
            scan_error=scan_error,
        )
        if primary_reason == "candidates_present":
            primary_reason = "no_opportunity"
        _log(
            f"execute strategy scanned_count={scanned_count} watchlist={watchlist_count} "
            f"candidates_count=0 primary_reason={primary_reason} scan_error={scan_error}"
        )
        out_empty = _strategy_result_base(
            timeframe=tf,
            limit=lim,
            amount_usdt=float(amount_usdt),
            scan_debug=scan_debug,
            candidates_count=0,
            opened_count=0,
            status="no_opportunity",
            message="Sin oportunidades válidas en la watchlist actual.",
            primary_reason=primary_reason,
            candidates=[],
            candidate_opportunities=[],
            evaluated=[],
            strategy_mode=mode,
            positions_review=evaluate_open_positions(portfolio),
            actions=actions,
        )
        out_empty["position_limits"] = paper_position_limits_snapshot(max_pos, pf, evaluated=[])
        return out_empty

    btc_ok = _btc_trend_favorable(scan_by_sym) if require_btc_trend_up else True
    btc_ctx_label = (
        "favorable" if btc_ok else "unfavorable" if require_btc_trend_up else "not_required"
    )

    for c in candidates:
        sym = str(c.get("symbol") or "").strip()
        if not sym:
            continue
        score = c.get("score")
        row_btc_ctx = btc_ctx_label if not _is_btc_symbol(sym) else "n/a"

        def _append(status: str, reason: str) -> None:
            nonlocal primary_reason
            evaluated.append(
                _evaluated_row(
                    c,
                    status=status,
                    reason=reason,
                    rejection_reason=reason,
                    btc_context=row_btc_ctx,
                )
            )
            if primary_reason is None and status in ("rejected", "skipped"):
                primary_reason = reason

        if opened_count >= 1:
            _append("skipped", "max_one_per_run")
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": "máximo 1 posición nueva por ejecución",
                    "score": score,
                }
            )
            continue

        if open_count >= max_pos:
            _append("skipped", "max_open_positions")
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": f"máximo {max_pos} posiciones abiertas",
                    "score": score,
                }
            )
            continue

        if min_score > 0:
            try:
                sc_val = float(score) if score is not None else None
            except (TypeError, ValueError):
                sc_val = None
            if sc_val is None or sc_val < min_score:
                _append("rejected", "score_below_min")
                actions.append(
                    {
                        "action": "entry",
                        "symbol": sym,
                        "status": "skipped",
                        "reason": "score_below_min",
                        "score": score,
                    }
                )
                continue

        if _has_open_position(sym, pf):
            _append("rejected", "already_open")
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": "already_open",
                    "score": score,
                }
            )
            continue

        if cooldown_m > 0 and _symbol_in_cooldown(sym, trades, cooldown_m):
            _append("rejected", "cooldown_symbol")
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": "cooldown_symbol",
                    "score": score,
                }
            )
            continue

        if _should_apply_btc_entry_filter(
            require_btc_trend_up=require_btc_trend_up,
            strategy_mode=mode,
            row=c,
        ) and not _is_btc_symbol(sym) and not btc_ok:
            _append("rejected", "btc_trend_filter")
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": "btc_trend_filter",
                    "score": score,
                }
            )
            continue

        setup = c.get("setup_type")
        reason = (
            f"estrategia_paper setup={setup} score={score}"
            if setup
            else (f"estrategia_paper score={score}" if score is not None else "estrategia_paper")
        )
        try:
            open_paper_position_market_by_amount(
                symbol=sym,
                side="long",
                amount_usdt=amount_usdt,
                reason=reason,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                trailing_stop_pct=trailing_stop_pct,
                break_even_trigger_pct=break_even_trigger_pct
                if break_even_trigger_pct > 0
                else None,
                break_even_plus_pct=break_even_plus_pct,
            )
            opened_count += 1
            open_count += 1
            primary_reason = "opened"
            evaluated.append(
                _evaluated_row(
                    c,
                    status="accepted",
                    reason=reason,
                    btc_context=row_btc_ctx,
                )
            )
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "executed",
                    "reason": reason,
                    "amount_usdt": float(amount_usdt),
                    "score": score,
                }
            )
            _log(f"execute: {sym} entry executed")
            break
        except ValueError as e:
            err = str(e)
            skip_reason = "already_open" if "Ya existe" in err or "abierta" in err.lower() else err
            _append("skipped", skip_reason)
            actions.append(
                {"action": "entry", "symbol": sym, "status": "skipped", "reason": skip_reason, "score": score}
            )
            _log(f"execute: {sym} skipped {e}")
        except Exception as e:
            skip_reason = f"{type(e).__name__}: {e}"
            _append("skipped", skip_reason)
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": skip_reason,
                    "score": score,
                }
            )
            _log(f"execute: {sym} error {e}")

    portfolio = get_paper_portfolio()
    positions_review = evaluate_open_positions(portfolio)
    exit_n = sum(1 for a in actions if a.get("action") == "exit" and a.get("status") == "executed")

    if opened_count > 0:
        status = "opened"
        message = f"Estrategia ejecutada: se abrió {opened_count} posición paper."
        if exit_n > 0:
            message += f" Se cerraron {exit_n} por reglas de salida."
        primary_reason = primary_reason or "opened"
    elif candidates_count > 0:
        status = "skipped"
        message = "Hubo candidatos, pero ninguno pasó los filtros de entrada o reglas de cartera."
        if primary_reason is None or primary_reason == "opened":
            primary_reason = _primary_no_entry_reason(evaluated, had_candidates=True)
    else:
        status = "no_opportunity"
        message = "Sin oportunidades válidas en la watchlist actual."
        primary_reason = "no_opportunity"

    rejected_max = sum(
        1 for e in evaluated if isinstance(e, dict) and str(e.get("reason") or "") == "max_open_positions"
    )
    limits = paper_position_limits_snapshot(max_pos, pf, evaluated=evaluated)
    _log(
        f"execute strategy scanned_count={scanned_count} watchlist={watchlist_count} "
        f"candidates_count={candidates_count} opened_count={opened_count} "
        f"evaluated_count={len(evaluated)} primary_reason={primary_reason} "
        f"rejected_max_open_positions={rejected_max} open_symbols={limits.get('open_position_symbols')}"
    )
    out = _strategy_result_base(
        timeframe=tf,
        limit=lim,
        amount_usdt=float(amount_usdt),
        scan_debug=scan_debug,
        candidates_count=candidates_count,
        opened_count=opened_count,
        status=status,
        message=message,
        primary_reason=primary_reason,
        candidates=candidates,
        candidate_opportunities=candidates,
        evaluated=evaluated,
        strategy_mode=mode,
        positions_review=positions_review,
        actions=actions,
    )
    out["position_limits"] = limits
    return out


def propose_testnet_entry_from_strategy(
    timeframe: str = "1h",
    limit: int = 200,
    quote_amount_usdt: float = 10.0,
    stop_loss_pct: float = 2.0,
    take_profit_pct: float = 4.0,
    trailing_stop_pct: float = 1.5,
    max_open_positions: int = 3,
    break_even_trigger_pct: float = 0.0,
    break_even_plus_pct: float = 0.0,
    cooldown_minutes: int = 0,
    require_btc_trend_up: bool = False,
    min_entry_score: float = 0.0,
    strategy_mode: str | None = None,
) -> dict[str, Any]:
    """
    Ejecuta el mismo escaneo y filtros de entrada que execute_paper_strategy, pero sin abrir posición paper
    ni orden Binance: devuelve una propuesta BUY testnet para confirmación manual.
    """
    import math

    from services.crypto.binance_testnet import (
        MARKET_ORDER_SYMBOL_WHITELIST,
        MAX_MARKET_ORDER_QUOTE_USDT,
        MIN_MARKET_ORDER_QUOTE_USDT,
        format_testnet_whitelist_rejection,
        get_testnet_balances,
        testnet_symbol_in_local_order_cooldown,
    )
    from services.crypto.watchlist import get_crypto_watchlist, scan_crypto_watchlist

    if not math.isfinite(quote_amount_usdt) or quote_amount_usdt <= 0:
        raise ValueError("quote_amount_usdt debe ser > 0")

    q_use = max(MIN_MARKET_ORDER_QUOTE_USDT, min(float(quote_amount_usdt), MAX_MARKET_ORDER_QUOTE_USDT))
    max_pos = max(1, int(max_open_positions))
    cooldown_m = max(0, int(cooldown_minutes))
    min_score = float(min_entry_score) if math.isfinite(min_entry_score) and min_entry_score > 0 else 0.0

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    mode = normalize_strategy_mode(strategy_mode)
    watchlist_symbols = get_crypto_watchlist()
    watchlist_count = len(watchlist_symbols)
    _log(
        f"propose_testnet_entry: mode={mode} timeframe={tf} limit={lim} quote={q_use} max_open={max_pos} "
        f"cooldown={cooldown_m} btc_filter={require_btc_trend_up} min_score={min_score} "
        f"watchlist_count={watchlist_count}"
    )

    scan_error: str | None = None
    scan_results: list[dict[str, Any]] = []
    t_scan = time.monotonic()
    try:
        scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim, strategy_mode=mode)
    except Exception as e:
        scan_error = f"{type(e).__name__}: {e}"
        _log(f"propose_testnet_entry: scan falló {scan_error}")
    scan_duration_ms = int((time.monotonic() - t_scan) * 1000)
    scanned_count = len(scan_results)
    if watchlist_count > 0 and scanned_count == 0 and not scan_error:
        scan_error = (
            "scan_crypto_watchlist devolvió lista vacía con watchlist no vacía (Testnet asistido)"
        )

    scan_by_sym = _scan_by_symbol(scan_results)
    raw_candidates = evaluate_entry_candidates(scan_results, strategy_mode=mode)
    from services.crypto.candidate_diagnostics import enrich_entry_candidates

    candidate_opportunities = enrich_entry_candidates(
        raw_candidates,
        scan_results,
        strategy_mode=mode,
        scan_by_sym=scan_by_sym,
    )
    candidates = candidate_opportunities
    candidates_count = len(candidates)
    scan_debug = log_scan_debug_snapshot(
        timeframe=tf,
        limit=lim,
        watchlist_count=watchlist_count,
        watchlist_sample=watchlist_symbols,
        scan_type="propose_testnet_entry_from_strategy",
        scan_results=scan_results,
        candidates_count=candidates_count,
        scan_error=scan_error,
        scan_duration_ms=scan_duration_ms,
        context="propose_testnet_entry_from_strategy",
        strategy_mode=mode,
    )
    scan_debug["timeframe"] = tf
    scan_debug["limit"] = lim

    risk_block: dict[str, float] = {
        "stop_loss_pct": float(stop_loss_pct),
        "take_profit_pct": float(take_profit_pct),
        "trailing_stop_pct": float(trailing_stop_pct),
        "break_even_trigger_pct": float(break_even_trigger_pct),
        "break_even_plus_pct": float(break_even_plus_pct),
    }

    base_evaluated_meta = {
        "timeframe": tf,
        "limit": lim,
        "quote_amount_usdt": q_use,
        "watchlist_count": watchlist_count,
        "scanned_count": scanned_count,
        "scan_count": scanned_count,
        "candidates_count": candidates_count,
        "scan_debug": scan_debug,
        "strategy_mode": mode,
    }

    if not candidates:
        return {
            "ok": True,
            "proposal": None,
            "primary_reason": "no_opportunity",
            "evaluated": [],
            "candidate_opportunities": [],
            "position_limits": _testnet_position_limits_meta(max_pos),
            **base_evaluated_meta,
        }

    bal = get_testnet_balances()
    bal_ok = bool(bal.get("ok"))

    if not bal_ok:
        evaluated_offline: list[dict[str, Any]] = []
        for c in candidates:
            if not isinstance(c, dict):
                continue
            sym = str(c.get("symbol") or "").strip()
            if not sym:
                continue
            evaluated_offline.append(_evaluated_row(c, status="rejected", reason="testnet_balances_unavailable"))
        return {
            "ok": True,
            "proposal": None,
            "primary_reason": "testnet_balances_unavailable",
            "evaluated": evaluated_offline,
            "candidate_opportunities": candidate_opportunities,
            "position_limits": _testnet_position_limits_meta(max_pos),
            **base_evaluated_meta,
        }

    btc_ok = _btc_trend_favorable(scan_by_sym) if require_btc_trend_up else True
    btc_ctx_label = (
        "favorable" if btc_ok else "unfavorable" if require_btc_trend_up else "not_required"
    )

    from services.crypto.binance_testnet import (
        format_testnet_app_position_duplicate_rejection,
        get_testnet_app_position_symbols,
    )

    app_open_syms = get_testnet_app_position_symbols()
    app_open_set = frozenset(app_open_syms)
    open_style_count = len(app_open_syms)

    evaluated: list[dict[str, Any]] = []
    proposal: dict[str, Any] | None = None
    primary_reason: str | None = None

    for c in candidates:
        if not isinstance(c, dict):
            continue
        sym = str(c.get("symbol") or "").strip()
        if not sym:
            continue
        score = c.get("score")

        row_btc_ctx = btc_ctx_label if not _is_btc_symbol(sym) else "n/a"

        def _append(status: str, reason: str) -> None:
            evaluated.append(
                _evaluated_row(
                    c,
                    status=status,
                    reason=reason,
                    rejection_reason=reason,
                    btc_context=row_btc_ctx,
                )
            )

        sym_u = _norm_symbol(sym)
        if sym_u not in MARKET_ORDER_SYMBOL_WHITELIST:
            wl_msg = format_testnet_whitelist_rejection(
                sym_u,
                str(c.get("setup_type") or "") or None,
            )
            evaluated.append(
                _evaluated_row(
                    c,
                    status="rejected",
                    reason="not_whitelisted_testnet",
                    rejection_reason=wl_msg,
                    btc_context=row_btc_ctx,
                )
            )
            continue

        if proposal is not None:
            _append("skipped", "max_one_per_run")
            continue

        if open_style_count >= max_pos:
            _append("skipped", "max_open_positions")
            continue

        if min_score > 0:
            try:
                sc_val = float(score) if score is not None else None
            except (TypeError, ValueError):
                sc_val = None
            if sc_val is None or sc_val < min_score:
                _append("rejected", "score_below_min")
                continue

        if sym_u in app_open_set:
            dup_msg = format_testnet_app_position_duplicate_rejection(sym_u)
            evaluated.append(
                _evaluated_row(
                    c,
                    status="rejected",
                    reason="already_hold_base_testnet",
                    rejection_reason=dup_msg,
                    btc_context=row_btc_ctx,
                )
            )
            continue

        if cooldown_m > 0 and testnet_symbol_in_local_order_cooldown(sym_u, cooldown_m):
            _append("rejected", "cooldown_symbol")
            continue

        if _should_apply_btc_entry_filter(
            require_btc_trend_up=require_btc_trend_up,
            strategy_mode=mode,
            row=c,
        ) and not _is_btc_symbol(sym_u) and not btc_ok:
            _append("rejected", "btc_trend_filter")
            continue

        sig = str(c.get("signal") or "")
        reason_txt = f"estrategia_coincidente_con_paper score={score}" if score is not None else "estrategia_coincidente_con_paper"

        score_out: float | None
        if isinstance(score, (int, float)) and math.isfinite(float(score)):
            score_out = float(score)
        else:
            score_out = None

        proposal = {
            "symbol": sym_u,
            "side": "buy",
            "quote_amount_usdt": q_use,
            "score": score_out,
            "signal": sig,
            "reason": reason_txt,
            "timeframe": tf,
            "risk": risk_block,
        }
        _append("selected", reason_txt)
        primary_reason = None
        break

    if proposal is None:
        primary_reason = primary_reason or _primary_no_entry_reason(evaluated, had_candidates=candidates_count > 0)
        if primary_reason is None:
            primary_reason = "no_entry"

    limits = testnet_position_limits_snapshot(max_pos, bal, evaluated=evaluated)
    _log(
        f"propose_testnet_entry: fin has_proposal={proposal is not None} primary_reason={primary_reason} "
        f"position_source={limits.get('position_source')} open={limits.get('open_positions_count')}/"
        f"{limits.get('max_open_positions')} symbols={limits.get('open_position_symbols')} "
        f"rejected_max={limits.get('rejected_by_max_open_positions_count')}"
    )

    out: dict[str, Any] = {
        "ok": True,
        "proposal": proposal,
        "primary_reason": primary_reason if proposal is None else None,
        "evaluated": evaluated,
        "candidate_opportunities": candidate_opportunities,
        "position_limits": limits,
        **base_evaluated_meta,
    }
    return out


def testnet_position_limits_snapshot(
    max_open_positions: int,
    balances_payload: dict[str, Any] | None = None,
    *,
    evaluated: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Diagnóstico de cupo max_open_positions (posiciones desde historial local de la app)."""
    from services.crypto.binance_testnet import (
        TESTNET_POSITION_COUNT_SOURCE,
        TESTNET_POSITION_SOURCE,
        TESTNET_POSITION_SOURCE_LABEL,
        get_testnet_app_position_symbols,
    )

    _ = balances_payload  # saldos sandbox no definen cupo de entradas
    open_syms = get_testnet_app_position_symbols()
    open_count = len(open_syms)
    max_pos = max(1, int(max_open_positions))
    rejected = 0
    if evaluated:
        rejected = sum(
            1
            for e in evaluated
            if isinstance(e, dict) and str(e.get("reason") or "") == "max_open_positions"
        )
    return {
        "open_positions_count": open_count,
        "max_open_positions": max_pos,
        "open_position_symbols": open_syms,
        "open_slots_remaining": max(0, max_pos - open_count),
        "rejected_by_max_open_positions_count": rejected,
        "count_source": TESTNET_POSITION_COUNT_SOURCE,
        "position_source": TESTNET_POSITION_SOURCE,
        "position_source_label": TESTNET_POSITION_SOURCE_LABEL,
    }


def _testnet_position_limits_meta(max_open_positions: int) -> dict[str, Any]:
    """Límites cuando aún no hay lectura de balances (cupo sigue historial local)."""
    from services.crypto.binance_testnet import (
        TESTNET_POSITION_COUNT_SOURCE,
        TESTNET_POSITION_SOURCE,
        TESTNET_POSITION_SOURCE_LABEL,
        get_testnet_app_position_symbols,
    )

    max_pos = max(1, int(max_open_positions))
    open_syms = get_testnet_app_position_symbols()
    open_count = len(open_syms)
    return {
        "open_positions_count": open_count,
        "max_open_positions": max_pos,
        "open_position_symbols": open_syms,
        "open_slots_remaining": max(0, max_pos - open_count),
        "rejected_by_max_open_positions_count": 0,
        "count_source": TESTNET_POSITION_COUNT_SOURCE,
        "position_source": TESTNET_POSITION_SOURCE,
        "position_source_label": TESTNET_POSITION_SOURCE_LABEL,
    }


def _pick_best_scan_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = float("-inf")
    for c in candidates:
        if not isinstance(c, dict):
            continue
        sym = str(c.get("symbol") or "").strip()
        if not sym:
            continue
        score_raw = c.get("score")
        try:
            sc = float(score_raw) if score_raw is not None else float("-inf")
        except (TypeError, ValueError):
            sc = float("-inf")
        if sc > best_score:
            best_score = sc
            best = dict(c) if isinstance(c, dict) else {}
            best.setdefault("symbol", sym)
            best.setdefault("score", score_raw if isinstance(score_raw, (int, float)) else sc)
    return best


def _non_candidate_reasons(
    scan_results: list[dict[str, Any]],
    strategy_mode: str,
) -> dict[str, int]:
    """Resumen de filas OK que no pasan is_entry_candidate_row (solo diagnóstico)."""
    mode = normalize_strategy_mode(strategy_mode)
    reasons: dict[str, int] = {}
    for row in scan_results:
        if not isinstance(row, dict) or row.get("error"):
            continue
        if is_entry_candidate_row(row, mode):
            continue
        key: str
        if mode == STRATEGY_MODE_TREND_SWING:
            key = "signal_not_compra_potencial"
        else:
            setup = row.get("setup_type")
            sig = str(row.get("signal") or "")
            if setup in DAILY_SETUP_TYPES and not row.get("entry_eligible"):
                key = "setup_not_eligible"
            elif sig == "compra_potencial" and not row.get("entry_eligible"):
                key = "compra_not_entry_eligible"
            elif setup in DAILY_SETUP_TYPES:
                key = "setup_other"
            elif sig != "compra_potencial":
                key = "no_daily_setup"
            else:
                key = "other"
        reasons[key] = reasons.get(key, 0) + 1
    return reasons


def compare_crypto_strategies(
    timeframe: str = "1h",
    limit: int = 200,
) -> dict[str, Any]:
    """
    Escanea la watchlist con trend_swing y daily_intraday; sin paper, testnet ni órdenes.
    """
    from services.crypto.watchlist import get_crypto_watchlist, scan_crypto_watchlist

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    watchlist = get_crypto_watchlist()
    watchlist_count = len(watchlist)
    _log(f"compare_crypto_strategies: timeframe={tf} limit={lim} watchlist={watchlist_count}")

    modes_out: list[dict[str, Any]] = []
    for mode in (STRATEGY_MODE_TREND_SWING, STRATEGY_MODE_DAILY_INTRADAY):
        scan_error: str | None = None
        scan_results: list[dict[str, Any]] = []
        t0 = time.monotonic()
        try:
            scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim, strategy_mode=mode)
        except Exception as e:
            scan_error = f"{type(e).__name__}: {e}"
        scan_duration_ms = int((time.monotonic() - t0) * 1000)
        raw_candidates = evaluate_entry_candidates(scan_results, strategy_mode=mode)
        from services.crypto.candidate_diagnostics import enrich_entry_candidates

        scan_by = _scan_by_symbol(scan_results)
        candidates = enrich_entry_candidates(
            raw_candidates,
            scan_results,
            strategy_mode=mode,
            scan_by_sym=scan_by,
        )
        candidates_count = len(candidates)
        scan_debug = _build_scan_debug(
            scan_results,
            watchlist_count=watchlist_count,
            candidates_count=candidates_count,
            scan_duration_ms=scan_duration_ms,
            scan_error=scan_error,
            strategy_mode=mode,
        )
        modes_out.append(
            {
                "strategy_mode": mode,
                "scan_count": scan_debug.get("scan_count", 0),
                "scan_ok_count": scan_debug.get("scan_ok_count", 0),
                "scan_error_count": scan_debug.get("scan_error_count", 0),
                "candidates_count": candidates_count,
                "daily_setup_counts": scan_debug.get("daily_setup_counts") or {},
                "signal_counts": scan_debug.get("signal_counts") or {},
                "best_candidate": _pick_best_scan_candidate(candidates),
                "candidate_opportunities": candidates,
                "non_candidate_reasons": _non_candidate_reasons(scan_results, mode),
                "scan_duration_ms": scan_duration_ms,
                "scan_diagnosis": scan_debug.get("scan_diagnosis"),
                "scan_error": scan_error,
            }
        )

    trend_c = int(modes_out[0].get("candidates_count") or 0)
    daily_c = int(modes_out[1].get("candidates_count") or 0)
    return {
        "ok": True,
        "timeframe": tf,
        "limit": lim,
        "watchlist_count": watchlist_count,
        "note": "Diagnóstico solamente. No ejecuta órdenes.",
        "modes": modes_out,
        "comparison": {
            "candidates_delta": daily_c - trend_c,
            "daily_more_candidates": daily_c > trend_c,
            "same_candidates": daily_c == trend_c,
        },
    }
