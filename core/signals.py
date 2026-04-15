from __future__ import annotations

import math

from core.config import BUY_PRIORITY_THRESHOLD, BUY_THRESHOLD, FOLLOW_THRESHOLD, UPSIDE_PRIORITY

def classify_signal_state(
    total_score: int,
    upside: float | None,
    price: float,
    target_price: float | None,
    rsi: float,
    macd_bullish: bool,
    trend_positive: bool,
) -> str:
    if total_score >= BUY_PRIORITY_THRESHOLD and upside is not None and upside > UPSIDE_PRIORITY:
        return 'COMPRA PRIORITARIA'
    if total_score >= BUY_THRESHOLD:
        return 'COMPRA POTENCIAL'
    if total_score >= FOLLOW_THRESHOLD:
        return 'SEGUIMIENTO'
    if target_price is not None and price >= target_price:
        return 'TOMA DE GANANCIA'
    if rsi > 70:
        return 'SOBREEXTENDIDA'
    if (not macd_bullish) and (not trend_positive):
        return 'DEBILITÁNDOSE'
    return 'EVITAR'


def classify_conviction(total_score: int) -> str:
    if total_score >= 10:
        return 'ALTA'
    if total_score >= 8:
        return 'MEDIA'
    if total_score >= 5:
        return 'BAJA'
    return 'NULA'


def suggested_capital(total_score: int) -> int:
    if total_score >= 10:
        return 12
    if total_score >= 8:
        return 8
    if total_score >= 5:
        return 4
    return 0


def classify_setup(rsi: float, pullback: bool, trend_positive: bool, macd_bullish: bool) -> str:
    if pullback and trend_positive and macd_bullish:
        return 'PULLBACK EN TENDENCIA'
    if rsi < 30 and macd_bullish:
        return 'REVERSAL'
    if trend_positive and macd_bullish:
        return 'TENDENCIA FIRME'
    if pullback:
        return 'PULLBACK'
    return 'SIN SETUP'


def classify_evolution(
    current_score: int,
    previous_score: float | None,
    current_state: str,
    previous_state: str | None,
) -> str:
    if previous_score is None and previous_state is None:
        return 'NUEVA INCORPORACIÓN'

    score_change = current_score - previous_score

    if current_state != previous_state:
        if score_change > 0:
            return 'MEJORANDO'
        if score_change < 0:
            return 'DETERIORANDO'
        return 'CAMBIO DE ESTADO'

    if score_change > 0:
        return 'MEJORANDO'
    if score_change < 0:
        return 'DETERIORANDO'
    return 'SIN CAMBIOS'


def classify_priority(
    total_score: int,
    evolution_or_delta,
    score_anterior=None,
) -> str:
    """
    Prioridad de seguimiento en el radar.

    En el pipeline actual, ``Evolucion`` suele ser el *delta numérico* de score
    (``TotalScore - score_anterior``) tras ``merge_history``, no la categoría
    ``'MEJORANDO'`` de ``classify_evolution``. Por eso se acepta:

    - cadena ``'MEJORANDO'`` (compatibilidad), o
    - delta numérico > 0, salvo el caso “primer merge” donde ``score_anterior`` es 0
      y ``Evolucion == TotalScore`` (no es un delta real).
    """
    improving = False
    if isinstance(evolution_or_delta, str):
        improving = evolution_or_delta == 'MEJORANDO'
    else:
        try:
            delta = float(evolution_or_delta)
            if math.isnan(delta):
                delta = 0.0
        except (TypeError, ValueError):
            delta = 0.0
        try:
            prev = float(score_anterior) if score_anterior is not None else 0.0
            if math.isnan(prev):
                prev = 0.0
        except (TypeError, ValueError):
            prev = 0.0
        try:
            cur = float(total_score)
            if math.isnan(cur):
                cur = 0.0
        except (TypeError, ValueError):
            cur = 0.0
        if delta > 0:
            if prev == 0.0 and abs(delta - cur) < 1e-6:
                improving = False
            else:
                improving = True

    if total_score >= 9 and improving:
        return 'ALTA'
    if total_score >= 8:
        return 'MEDIA'
    if total_score >= 5:
        return 'BAJA'
    return 'IGNORAR'
