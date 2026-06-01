"""
Explicación determinista del campo `signal` en modo daily_intraday (solo lectura).

La señal NO se deriva de RSI/MACD/volumen de forma independiente: en código es un
corte sobre el score entero. Ver `_analyze_daily_intraday` en `signals.py`.
"""
from __future__ import annotations

from typing import Any

from services.crypto.strategy_modes import (
    DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE,
    DAILY_SETUP_TYPES,
)

DAILY_INTRADAY_SETUP_ENTRY_MIN_SCORE = 55


def daily_intraday_signal_rules_doc() -> dict[str, Any]:
    """Texto estructurado para informes (fuente de verdad = signals.py)."""
    return {
        "signal_field_generator": "services.crypto.signals.analyze_ohlcv -> _analyze_daily_intraday",
        "compra_potencial_daily_intraday": (
            f'signal == "compra_potencial" si y solo si int(score) >= {DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE}. '
            "No hay rama RSI/MACD/volumen adicional sobre el string `signal`."
        ),
        "neutral_daily_intraday": (
            f'signal == "neutral" si int(score) < {DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE}. '
            "El score se calcula en `_weighted_entry_score_parts` (mismos pesos que trend_swing)."
        ),
        "cuidado_daily_intraday": (
            "En `daily_intraday` el código asigna solo `compra_potencial` o `neutral` al campo `signal` "
            "(no llama a `_signal_label`). El tipo `Signal` incluye `cuidado` por compatibilidad con "
            "`trend_swing`, donde sí aplica riesgo / score bajo."
        ),
        "compra_fuerte": (
            "No existe `compra_fuerte` en `services/crypto/signals.py` ni en el tipo `Signal` del "
            "analizador OHLCV (`Literal['compra_potencial','neutral','cuidado']`). "
            "Las estadísticas de `compra_fuerte` del live scan serán siempre 0 salvo que otro "
            "campo (`action`, etc.) lo inyecte desde fuera (no es el generador estándar del scan)."
        ),
        "entry_eligible": (
            f'entry_eligible = (signal == "compra_potencial") OR '
            f'(setup_type in {DAILY_SETUP_TYPES} AND score >= {DAILY_INTRADAY_SETUP_ENTRY_MIN_SCORE}). '
            "Por eso puede haber `signal=neutral` con `entry_eligible=True` (setup + score>=55)."
        ),
        "order_execution_note": (
            "La apertura automática (paper / testnet) compara el `score` de la fila con `min_entry_score` "
            "desde la UI (`propose_testnet_entry_from_strategy` / `execute_paper_strategy`). "
            "Ese umbral es independiente del corte que define `signal`."
        ),
    }


def _bool_label(ok: bool, yes: str, no: str) -> tuple[str, bool]:
    return (yes if ok else no, ok)


def explain_daily_intraday_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    Construye checklist y bloqueador principal para `signal` en una fila OK del scan.

    `row` debe ser el dict devuelto por analyze_ohlcv en modo daily_intraday (sin `error`).
    """
    if not isinstance(row, dict) or row.get("error"):
        return {"error": "row inválida o con error"}

    score = row.get("score")
    try:
        score_i = int(score) if score is not None else -1
    except (TypeError, ValueError):
        score_i = -1

    sig = str(row.get("signal") or "")
    trend = str(row.get("trend") or "")
    setup = row.get("setup_type")
    setup_s = str(setup) if setup is not None else ""
    eligible = bool(row.get("entry_eligible"))

    rsi = row.get("rsi_14")
    try:
        rsi_f = float(rsi) if rsi is not None and rsi == rsi else None
    except (TypeError, ValueError):
        rsi_f = None

    mh = row.get("macd_hist")
    try:
        mh_f = float(mh) if mh is not None and mh == mh else None
    except (TypeError, ValueError):
        mh_f = None

    vr = row.get("volume_ratio")
    try:
        vr_f = float(vr) if vr is not None and vr == vr else None
    except (TypeError, ValueError):
        vr_f = None

    bd = row.get("score_breakdown") if isinstance(row.get("score_breakdown"), dict) else {}

    checklist: list[dict[str, Any]] = []

    alcista = trend == "alcista"
    t, ok = _bool_label(alcista, "tendencia corta alcista (close > EMA rápida > EMA lenta)", "tendencia no alcista")
    checklist.append({"key": "short_trend_alcista", "label": t, "ok": ok})

    is_pullback = setup_s == "pullback"
    t, ok = _bool_label(is_pullback, "setup_type=pullback", f"setup_type={setup_s or 'None'}")
    checklist.append({"key": "setup_pullback", "label": t, "ok": ok})

    t, ok = _bool_label(eligible, "entry_eligible=True", "entry_eligible=False")
    checklist.append({"key": "entry_eligible", "label": t, "ok": ok})

    macd_pos = mh_f is not None and mh_f > 0
    t, ok = _bool_label(macd_pos, "MACD histograma > 0", "MACD histograma <= 0 o ausente")
    checklist.append({"key": "macd_hist_positive", "label": t, "ok": ok})

    macd_ctx = str(row.get("macd_context") or "")
    macd_hist_rising = macd_ctx in ("improving_positive", "recovering")
    t, ok = _bool_label(
        macd_hist_rising,
        f"MACD histograma subiendo vs vela anterior (macd_context={macd_ctx or '—'}; requisito setup pullback)",
        f"MACD no subió vs vela anterior (macd_context={macd_ctx or '—'}) — pullback no asignado",
    )
    checklist.append({"key": "macd_hist_rising_for_pullback", "label": t, "ok": ok})

    if vr_f is not None:
        vol_strong = vr_f >= 1.1
        t, ok = _bool_label(vol_strong, f"volumen ratio >= 1.1 (actual {vr_f:.3f})", f"volumen ratio < 1.1 (actual {vr_f:.3f})")
    else:
        vol_strong = False
        t, ok = "volume_ratio ausente (no se evalúa ratio)", False
    checklist.append({"key": "volume_ratio_ge_1_1", "label": t, "ok": ok})

    if rsi_f is not None:
        in_pullback_rsi_band = 38.0 <= rsi_f <= 58.0
        t, ok = _bool_label(
            in_pullback_rsi_band,
            f"RSI en banda pullback 38–58 (actual {rsi_f:.2f})",
            f"RSI fuera de 38–58 (actual {rsi_f:.2f}); importa para clasificar setup, no para `signal`",
        )
    else:
        in_pullback_rsi_band = False
        t, ok = "RSI ausente", False
    checklist.append({"key": "rsi_pullback_band_note", "label": t, "ok": ok})

    score_ok_signal = score_i >= DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE
    t, ok = _bool_label(
        score_ok_signal,
        f"score >= {DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE} para signal=compra_potencial (actual {score_i})",
        f"score < {DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE} (actual {score_i}) -> signal forzado a neutral",
    )
    checklist.append({"key": "score_ge_signal_label_min", "label": t, "ok": ok})

    if score_ok_signal:
        primary_blocker = None
        result_explanation = (
            f'signal == "compra_potencial" porque score >= {DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE}'
        )
    else:
        primary_blocker = (
            f"Condición que impide `compra_potencial`: score entero {score_i} < "
            f"{DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE} (única regla en `_analyze_daily_intraday`). "
            "RSI/ADX/volumen/MACD actúan sobre el score vía `_weighted_entry_score_parts`, no sobre el string signal."
        )
        result_explanation = (
            f'signal == "neutral" (score {score_i} < {DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE})'
        )

    worst_components: list[tuple[str, float]] = []
    for k in ("adx_score", "volume_score", "trigger_score", "rsi_score", "macd_score", "ema_score", "risk_penalty"):
        v = bd.get(k)
        if isinstance(v, (int, float)) and v == v:
            worst_components.append((k, float(v)))
    worst_components.sort(key=lambda x: x[1])

    return {
        "symbol": row.get("symbol"),
        "signal": sig,
        "score": score_i,
        "setup_type": setup,
        "entry_eligible": eligible,
        "trend": trend,
        "checklist": checklist,
        "primary_blocker_for_compra_potencial_signal": primary_blocker,
        "result_explanation": result_explanation,
        "score_breakdown": bd,
        "score_components_sorted_asc": worst_components,
        "strategy_mode": row.get("strategy_mode"),
    }


def format_explain_markdown_block(ex: dict[str, Any]) -> str:
    """Formato tipo usuario: símbolo, ✓/✗, resultado."""
    if ex.get("error"):
        return str(ex["error"])
    sym = ex.get("symbol") or "?"
    lines: list[str] = [f"### {sym}", ""]
    for item in ex.get("checklist") or []:
        mark = "✓" if item.get("ok") else "✗"
        lines.append(f"- {mark} {item.get('label')}")
    lines.append("")
    pb = ex.get("primary_blocker_for_compra_potencial_signal")
    if pb:
        lines.append(f"**Bloqueador `compra_potencial` (señal):** {pb}")
    lines.append("")
    lines.append(f"**Resultado:** {ex.get('result_explanation')}")
    bd = ex.get("score_breakdown") or {}
    if bd:
        lines.append("")
        lines.append("**score_breakdown (contribución al total):**")
        for k in (
            "base",
            "adx_score",
            "volume_score",
            "trigger_score",
            "rsi_score",
            "macd_score",
            "ema_score",
            "btc_trend_score",
            "risk_penalty",
            "total_before_clamp",
        ):
            if k in bd:
                lines.append(f"- `{k}`: {bd.get(k)}")
    return "\n".join(lines)
