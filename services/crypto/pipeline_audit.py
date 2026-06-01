"""
Auditoría del pipeline entrada crypto (testnet auto / informes).
No altera reglas de trading; sólo resume dicts ya producidos por propose_testnet_entry_from_strategy.
"""

from __future__ import annotations

from typing import Any


def build_auto_cycle_entry_pipeline_audit(
    entry: dict[str, Any] | None,
    *,
    max_eval_slim: int = 120,
) -> dict[str, Any] | None:
    """
    Snapshot compacto para persistir en crypto_testnet_auto_cycles.jsonl.
    Incluye digest del scan, resumen de evaluated y casos whitelist.
    """
    if not isinstance(entry, dict):
        return None

    from services.crypto.cycle_diagnostics import build_cycle_summary_from_evaluated

    ev = [e for e in (entry.get("evaluated") or []) if isinstance(e, dict)]
    summary = build_cycle_summary_from_evaluated(ev)

    slim: list[dict[str, Any]] = []
    whitelist_rejects: list[dict[str, Any]] = []
    for e in ev[: max(0, int(max_eval_slim))]:
        sym = e.get("symbol")
        reason = str(e.get("reason") or "")
        row: dict[str, Any] = {
            "symbol": sym,
            "status": e.get("status"),
            "reason": reason,
            "score": e.get("score"),
            "signal": e.get("signal"),
            "setup_type": e.get("setup_type"),
        }
        bd = e.get("score_breakdown")
        if isinstance(bd, dict):
            keys = (
                "adx_score",
                "volume_score",
                "trigger_score",
                "rsi_score",
                "macd_score",
                "ema_score",
                "btc_trend_score",
                "risk_penalty",
            )
            row["score_breakdown"] = {k: bd[k] for k in keys if k in bd}
        slim.append(row)
        if reason == "not_whitelisted_testnet":
            whitelist_rejects.append(
                {
                    "symbol": sym,
                    "score": e.get("score"),
                    "signal": e.get("signal"),
                    "setup_type": e.get("setup_type"),
                    "rejection_reason": e.get("rejection_reason"),
                }
            )

    sd = entry.get("scan_debug") if isinstance(entry.get("scan_debug"), dict) else {}
    scan_subset_keys = (
        "rows_signal_compra_potencial",
        "rows_signal_other",
        "rows_missing_signal",
        "rows_high_score_not_compra",
        "total_scan_rows",
        "unique_signals_detected",
        "signal_counts",
        "daily_setup_counts",
        "scan_diagnosis",
        "scan_scenario",
        "entry_candidate_filter",
    )
    scan_subset = {k: sd[k] for k in scan_subset_keys if k in sd}

    return {
        "primary_reason": entry.get("primary_reason"),
        "proposal_generated": bool(entry.get("proposal")),
        "candidates_count": entry.get("candidates_count"),
        "scanned_count": entry.get("scanned_count"),
        "watchlist_count": entry.get("watchlist_count"),
        "scan_subset": scan_subset,
        "scan_rows_digest": entry.get("scan_rows_digest"),
        "evaluated_summary": summary,
        "evaluated_slim": slim,
        "whitelist_rejects": whitelist_rejects[:30],
    }


def mean_score_breakdown_from_digest(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Promedio de componentes numéricos en score_breakdown del digest (filas con dict)."""
    acc: dict[str, list[float]] = {}
    n = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        bd = r.get("score_breakdown")
        if not isinstance(bd, dict):
            continue
        n += 1
        for k, v in bd.items():
            if k == "macd_cross_up":
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if k not in acc:
                acc[k] = []
            acc[k].append(fv)
    out: dict[str, float] = {}
    for k, vals in acc.items():
        if vals:
            out[k] = sum(vals) / len(vals)
    out["_rows_used"] = float(n)
    return out
