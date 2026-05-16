"""
Ciclo bot paper cripto: escaneo, gestión de riesgo y ejecución simulada.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

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
    dbg = _build_scan_debug(
        scan_results,
        watchlist_count=watchlist_count,
        candidates_count=candidates_count,
        scan_duration_ms=scan_duration_ms,
        scan_error=scan_error,
    )
    dbg["timeframe"] = timeframe
    dbg["limit"] = limit
    dbg["watchlist_sample"] = sample
    dbg["scan_type"] = scan_type
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
) -> dict[str, Any]:
    price = row.get("price")
    return {
        "symbol": row.get("symbol"),
        "signal": row.get("signal"),
        "score": row.get("score"),
        "status": status,
        "reason": reason,
        "price": price if price is None or isinstance(price, (int, float)) else None,
    }


def evaluate_entry_candidates(scan_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Candidatos con signal compra_potencial; no abre posiciones."""
    out = [
        r
        for r in scan_results
        if isinstance(r, dict)
        and not r.get("error")
        and r.get(ENTRY_CANDIDATE_SIGNAL_FIELD) == ENTRY_CANDIDATE_SIGNAL_VALUE
    ]
    _log(
        f"evaluate_entry_candidates: {len(out)} candidatos "
        f"(filtro: row[{ENTRY_CANDIDATE_SIGNAL_FIELD!r}]=={ENTRY_CANDIDATE_SIGNAL_VALUE!r}, sin error)"
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


def _cycle_message_search(scanned_count: int, candidates_count: int) -> str:
    if candidates_count == 0:
        return "Sin oportunidades válidas en la watchlist actual."
    return (
        f"Búsqueda completada: {candidates_count} candidato(s) compra_potencial "
        f"de {scanned_count} activos escaneados."
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
) -> dict[str, str]:
    """A=scanner OK sin compra_potencial; B=scanner no corre; C=posible desajuste filtro/campo."""
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
                "scan_scenario_label": "Candidatos compra_potencial",
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
        "scan_scenario_label": "Scanner OK, sin compra_potencial",
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
    scenario = _derive_scan_scenario(
        watchlist_count=watchlist_count,
        scan_count=scanned_count,
        scan_ok_count=scan_ok_count,
        candidates_count=candidates_count,
        scan_error=scan_error,
        breakdown=breakdown,
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


def run_crypto_paper_cycle(timeframe: str = "1h", limit: int = 200) -> dict[str, Any]:
    """Escanea watchlist completa vía scan_crypto_watchlist; sin aperturas."""
    from services.crypto.paper_portfolio import get_paper_portfolio
    from services.crypto.watchlist import scan_crypto_watchlist

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    _log(f"run_crypto_paper_cycle: inicio timeframe={tf} limit={lim} (watchlist completa)")

    scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim)
    scanned_count = len(scan_results)
    candidates = evaluate_entry_candidates(scan_results)
    candidates_count = len(candidates)
    portfolio = get_paper_portfolio()
    positions_review = evaluate_open_positions(portfolio)

    message = _cycle_message_search(scanned_count, candidates_count)
    _log(
        f"run_crypto_paper_cycle: fin scanned_count={scanned_count} "
        f"candidates_count={candidates_count}"
    )
    return {
        "timeframe": tf,
        "limit": lim,
        "scanned_count": scanned_count,
        "candidates_count": candidates_count,
        "opened_count": 0,
        "message": message,
        "candidates": candidates,
        "evaluated": [],
        "primary_reason": None,
        "positions_review": positions_review,
        "actions": [],
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
) -> dict[str, Any]:
    """
    Revisa salidas, escanea watchlist y abre como máximo 1 posición nueva por ejecución.
    """
    import math

    from services.crypto.paper_portfolio import (
        _count_open_positions,
        get_paper_portfolio,
        load_portfolio,
        open_paper_position_market_by_amount,
        review_paper_positions_for_exit,
    )
    from services.crypto.watchlist import get_crypto_watchlist, scan_crypto_watchlist

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
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
        f"execute_paper_strategy: inicio timeframe={tf} limit={lim} max_open={max_pos} "
        f"cooldown={cooldown_m} btc_filter={require_btc_trend_up} min_score={min_score} "
        f"watchlist_count={watchlist_count}"
    )

    actions: list[dict[str, Any]] = list(review_paper_positions_for_exit())

    scan_error: str | None = None
    scan_results: list[dict[str, Any]] = []
    t_scan = time.monotonic()
    try:
        scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim)
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
    candidates = evaluate_entry_candidates(scan_results)
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
    )
    scan_debug["timeframe"] = tf
    scan_debug["limit"] = lim

    pf = load_portfolio()
    trades = pf.get("trades") or []
    open_count = _count_open_positions(pf)
    opened_count = 0
    evaluated: list[dict[str, Any]] = []
    primary_reason: str | None = None

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
        return _strategy_result_base(
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
            evaluated=[],
            positions_review=evaluate_open_positions(portfolio),
            actions=actions,
        )

    btc_ok = _btc_trend_favorable(scan_by_sym) if require_btc_trend_up else True

    for c in candidates:
        sym = str(c.get("symbol") or "").strip()
        if not sym:
            continue
        score = c.get("score")

        def _append(status: str, reason: str) -> None:
            nonlocal primary_reason
            evaluated.append(_evaluated_row(c, status=status, reason=reason))
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

        if require_btc_trend_up and not _is_btc_symbol(sym) and not btc_ok:
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

        reason = f"estrategia_paper score={score}" if score is not None else "estrategia_paper"
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
            evaluated.append(_evaluated_row(c, status="accepted", reason=reason))
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

    _log(
        f"execute strategy scanned_count={scanned_count} watchlist={watchlist_count} "
        f"candidates_count={candidates_count} opened_count={opened_count} "
        f"evaluated_count={len(evaluated)} primary_reason={primary_reason}"
    )
    return _strategy_result_base(
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
        evaluated=evaluated,
        positions_review=positions_review,
        actions=actions,
    )


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
    watchlist_symbols = get_crypto_watchlist()
    watchlist_count = len(watchlist_symbols)
    _log(
        f"propose_testnet_entry: timeframe={tf} limit={lim} quote={q_use} max_open={max_pos} "
        f"cooldown={cooldown_m} btc_filter={require_btc_trend_up} min_score={min_score} "
        f"watchlist_count={watchlist_count}"
    )

    scan_error: str | None = None
    scan_results: list[dict[str, Any]] = []
    t_scan = time.monotonic()
    try:
        scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim)
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
    candidates = evaluate_entry_candidates(scan_results)
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
    }

    if not candidates:
        return {
            "ok": True,
            "proposal": None,
            "primary_reason": "no_opportunity",
            "evaluated": [],
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
            **base_evaluated_meta,
        }

    btc_ok = _btc_trend_favorable(scan_by_sym) if require_btc_trend_up else True

    def free_base_asset(sym_pair: str) -> float:
        parts = sym_pair.split("/", 1)
        base = parts[0].strip().upper() if parts else ""
        if not base:
            return 0.0
        for row in bal.get("balances") or []:
            if str(row.get("asset") or "").upper() == base:
                try:
                    return float(row.get("free") or 0)
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    def count_whitelist_base_positions() -> int:
        bases_in_whitelist = {"BTC", "ETH", "SOL", "BNB"}
        n = 0
        for row in bal.get("balances") or []:
            au = str(row.get("asset") or "").upper()
            if au not in bases_in_whitelist:
                continue
            try:
                free_b = float(row.get("free") or 0)
            except (TypeError, ValueError):
                continue
            if free_b > 1e-6:
                n += 1
        return n

    open_style_count = count_whitelist_base_positions()

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

        def _append(status: str, reason: str) -> None:
            evaluated.append(_evaluated_row(c, status=status, reason=reason))

        sym_u = _norm_symbol(sym)
        if sym_u not in MARKET_ORDER_SYMBOL_WHITELIST:
            _append("rejected", "not_whitelisted_testnet")
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

        if free_base_asset(sym_u) > 1e-6:
            _append("rejected", "already_hold_base_testnet")
            continue

        if cooldown_m > 0 and testnet_symbol_in_local_order_cooldown(sym_u, cooldown_m):
            _append("rejected", "cooldown_symbol")
            continue

        if require_btc_trend_up and not _is_btc_symbol(sym_u) and not btc_ok:
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

    _log(f"propose_testnet_entry: fin has_proposal={proposal is not None} primary_reason={primary_reason}")

    out: dict[str, Any] = {
        "ok": True,
        "proposal": proposal,
        "primary_reason": primary_reason if proposal is None else None,
        "evaluated": evaluated,
        **base_evaluated_meta,
    }
    return out
