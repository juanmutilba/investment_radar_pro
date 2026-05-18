"""Diagnóstico de por qué un símbolo es candidato (sin alterar reglas de entrada)."""

from __future__ import annotations

from typing import Any

from services.crypto.strategy_modes import (
    DAILY_SETUP_TYPES,
    STRATEGY_MODE_DAILY_INTRADAY,
    STRATEGY_MODE_TREND_SWING,
    normalize_strategy_mode,
)

_SETUP_HINTS: dict[str, str] = {
    "pullback": "Pullback en tendencia corta (RSI en zona de compra, MACD mejorando)",
    "rebound": "Rebote controlado (tendencia baja/lateral + RSI bajo + MACD al alza)",
    "momentum_intraday": "Momentum intradía (tendencia alcista + MACD positivo + volumen creciente)",
    "reversal_controlled": "Reversal controlado (RSI muy bajo + MACD girando + volumen estable/subiendo)",
}


def _scan_acceptance_reason(row: dict[str, Any], mode: str) -> str:
    signal = str(row.get("signal") or "")
    setup = row.get("setup_type")
    parts: list[str] = []
    if mode == STRATEGY_MODE_DAILY_INTRADAY:
        if setup:
            hint = _SETUP_HINTS.get(str(setup), str(setup))
            parts.append(f"Setup intradía: {hint}")
        elif signal and signal != "neutral":
            parts.append(f"Señal {signal}")
        if row.get("entry_eligible"):
            parts.append("Marcado entry_eligible (setup/score intradía)")
        if not parts:
            parts.append("Candidato intradía por criterio entry_eligible del scanner")
    else:
        if signal == "compra_potencial":
            parts.append("Señal compra_potencial (modo Trend/Swing conservador)")
        else:
            parts.append(f"Señal {signal or '—'} no alcanza compra_potencial en swing")
    return " · ".join(parts)


def _evaluation_outcome_label(status: str, reason: str) -> str:
    st = (status or "").strip().lower()
    r = (reason or "").strip()
    if st in ("accepted", "selected"):
        return f"Aceptado en filtros de entrada: {r}" if r else "Aceptado en filtros de entrada"
    if st == "skipped":
        return f"Omitido en filtros: {r}" if r else "Omitido en filtros"
    if st == "rejected":
        return f"Rechazado en filtros: {r}" if r else "Rechazado en filtros"
    return r or st or "—"


def build_candidate_opportunity_diagnostic(
    row: dict[str, Any],
    *,
    btc_context: str | None = None,
    evaluation_status: str | None = None,
    evaluation_reason: str | None = None,
) -> dict[str, Any]:
    """Campos para UI: por qué apareció / qué pasó en filtros posteriores."""
    mode = normalize_strategy_mode(row.get("strategy_mode"))
    sym = str(row.get("symbol") or "").strip()
    rsi_raw = row.get("rsi_14")
    rsi_out: float | None
    if isinstance(rsi_raw, (int, float)):
        rsi_out = float(rsi_raw)
    else:
        rsi_out = None

    scan_reason = _scan_acceptance_reason(row, mode)
    outcome = (
        _evaluation_outcome_label(evaluation_status or "", evaluation_reason or "")
        if evaluation_status
        else None
    )

    return {
        "symbol": sym,
        "strategy_mode": mode,
        "setup_type": row.get("setup_type"),
        "score": row.get("score"),
        "rsi": rsi_out,
        "rsi_14": rsi_out,
        "signal": row.get("signal"),
        "trend_context": row.get("trend_context"),
        "rsi_context": row.get("rsi_context"),
        "macd_context": row.get("macd_context"),
        "volume_context": row.get("volume_context"),
        "btc_context": btc_context if btc_context is not None else row.get("btc_context"),
        "entry_eligible": bool(row.get("entry_eligible")),
        "scan_acceptance_reason": scan_reason,
        "evaluation_status": evaluation_status,
        "evaluation_reason": evaluation_reason,
        "evaluation_outcome": outcome,
    }


def enrich_entry_candidates(
    candidates: list[dict[str, Any]],
    scan_results: list[dict[str, Any]],
    *,
    strategy_mode: str | None = None,
    scan_by_sym: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Añade diagnóstico a cada candidato del scanner (mismas filas, más campos)."""
    mode = normalize_strategy_mode(strategy_mode)
    by_sym = scan_by_sym or {}
    if not by_sym:
        for r in scan_results:
            if isinstance(r, dict):
                sym = str(r.get("symbol") or "").strip().upper()
                if sym:
                    by_sym[sym] = r

    btc_row = by_sym.get("BTC/USDT")
    btc_default: str | None = None
    if btc_row and not btc_row.get("error"):
        btc_default = f"btc_trend_{btc_row.get('trend', 'unknown')}"

    out: list[dict[str, Any]] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        sym_u = str(c.get("symbol") or "").strip().upper()
        base_row = by_sym.get(sym_u, c)
        merged = {**base_row, **c}
        sym = str(merged.get("symbol") or sym_u)
        btc_ctx = merged.get("btc_context")
        if btc_ctx is None and sym_u not in ("BTC/USDT", "BTCUSDT") and btc_default:
            btc_ctx = btc_default
        diag = build_candidate_opportunity_diagnostic(merged, btc_context=btc_ctx)
        out.append({**merged, **diag})
    _ = mode  # reserved for future per-mode tweaks
    return out
