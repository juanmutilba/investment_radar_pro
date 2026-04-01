from __future__ import annotations

from config import (
    RISK_BETA_IDEAL_MAX,
    RISK_BETA_IDEAL_MIN,
    RISK_BETA_NEUTRAL_MAX,
    RISK_BETA_NEUTRAL_MIN,
)


def classify_risk_profile(beta: float | None) -> str:
    if beta is None:
        return 'SIN DATO'
    if beta < 0.8:
        return 'DEFENSIVO'
    if beta <= 1.2:
        return 'BALANCEADO'
    if beta <= 1.8:
        return 'AGRESIVO'
    return 'ESPECULATIVO'


def calculate_risk_score(beta: float | None) -> int:
    if beta is None:
        return 0
    if RISK_BETA_IDEAL_MIN <= beta <= RISK_BETA_IDEAL_MAX:
        return 1
    if RISK_BETA_NEUTRAL_MIN <= beta <= RISK_BETA_NEUTRAL_MAX:
        return 0
    return -1
