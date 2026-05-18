"""Helpers para resumir evaluados de un ciclo (scheduler/monitor); sin lógica de trading."""

from __future__ import annotations

from typing import Any


def build_cycle_summary_from_evaluated(evaluated: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    accepted_count = 0
    rejected_count = 0
    skipped_count = 0
    evaluated_count = 0

    for ev in evaluated:
        if not isinstance(ev, dict):
            continue
        evaluated_count += 1
        status = str(ev.get("status") or "")
        reason = str(ev.get("reason") or "unknown")
        if status == "accepted":
            accepted_count += 1
        elif status == "rejected":
            rejected_count += 1
            reasons[reason] = reasons.get(reason, 0) + 1
        elif status == "skipped":
            skipped_count += 1
            reasons[reason] = reasons.get(reason, 0) + 1
        else:
            reasons[reason] = reasons.get(reason, 0) + 1

    out: dict[str, Any] = {
        "evaluated_count": evaluated_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "skipped_count": skipped_count,
        "reasons": reasons,
    }
    return out


def merge_scan_meta_into_summary(
    summary: dict[str, Any],
    scan_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Añade campos de diagnóstico de escaneo al resumen del ciclo (sin mutar trading)."""
    if not isinstance(scan_meta, dict):
        return summary
    for key in (
        "timeframe",
        "limit",
        "watchlist_sample",
        "scan_type",
        "watchlist_count",
        "scan_count",
        "scan_ok_count",
        "scan_error_count",
        "candidates_count",
        "scan_error",
        "scan_duration_ms",
        "first_symbols_sample",
        "scan_diagnosis",
        "scan_scenario",
        "scan_scenario_label",
        "scan_scenario_detail",
        "total_scan_rows",
        "rows_with_signal",
        "rows_signal_compra_potencial",
        "rows_signal_compra_case_mismatch",
        "rows_signal_other",
        "rows_missing_signal",
        "rows_high_score_not_compra",
        "rows_action_compra_potencial",
        "unique_signals_detected",
        "signal_counts",
        "sample_rows",
        "entry_candidate_filter",
        "evaluated_count_note",
        "strategy_mode",
        "daily_setup_counts",
    ):
        if key in scan_meta:
            summary[key] = scan_meta[key]
    return summary


def merge_position_limits_into_summary(
    summary: dict[str, Any],
    position_limits: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(position_limits, dict):
        return summary
    for key in (
        "open_positions_count",
        "max_open_positions",
        "open_position_symbols",
        "open_slots_remaining",
        "positions_in_file_total",
        "rejected_by_max_open_positions_count",
        "count_source",
        "position_source",
        "position_source_label",
    ):
        if key in position_limits:
            summary[key] = position_limits[key]
    return summary


def pick_best_rejected_candidate(evaluated: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = float("-inf")

    for ev in evaluated:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("status") or "") not in ("rejected", "skipped"):
            continue
        sym = ev.get("symbol")
        if not sym:
            continue
        score_raw = ev.get("score")
        try:
            sc = float(score_raw) if score_raw is not None else float("-inf")
        except (TypeError, ValueError):
            sc = float("-inf")
        if sc > best_score:
            best_score = sc
            sig = ev.get("signal")
            best = {
                "symbol": str(sym),
                "score": score_raw if isinstance(score_raw, (int, float)) else sc,
                "reason": str(ev.get("reason") or ev.get("rejection_reason") or ""),
                "signal": str(sig) if sig is not None else "",
                "setup_type": ev.get("setup_type"),
                "rejection_reason": ev.get("rejection_reason"),
                "strategy_mode": ev.get("strategy_mode"),
            }

    return best


def pick_entry_candidate_from_evaluated(
    evaluated: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Candidato aceptado (entrada ejecutada o seleccionada) del último ciclo."""
    for ev in evaluated:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("status") or "") != "accepted":
            continue
        sym = ev.get("symbol")
        if not sym:
            continue
        sig = ev.get("signal")
        return {
            "symbol": str(sym),
            "score": ev.get("score"),
            "reason": str(ev.get("reason") or ""),
            "signal": str(sig) if sig is not None else "",
        }
    return None


def pick_entry_candidate_from_action(action: dict[str, Any]) -> dict[str, Any] | None:
    if action.get("action") != "entry" or action.get("status") != "executed":
        return None
    sym = action.get("symbol")
    if not sym:
        return None
    return {
        "symbol": str(sym),
        "score": action.get("score"),
        "reason": str(action.get("reason") or ""),
        "signal": "",
    }
