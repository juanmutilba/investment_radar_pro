from __future__ import annotations

from core.config import DEBT_TO_EQUITY_MAX, PE_MAX, UPSIDE_MIN


def calculate_tech_score(rsi: float, pullback: bool, trend_positive: bool, macd_bullish: bool) -> int:
    score = 0
    if rsi < 30:
        score += 3
    elif rsi < 40:
        score += 1
    if pullback:
        score += 1
    if trend_positive:
        score += 1
    if macd_bullish:
        score += 1
    return score


def calculate_fund_score(
    net_income: float | None,
    ebitda: float | None,
    debt_to_equity: float | None,
    pe: float | None,
    upside: float | None,
) -> int:
    score = 0
    if net_income is not None and net_income > 0:
        score += 1
    if ebitda is not None and ebitda > 0:
        score += 1
    if debt_to_equity is not None and debt_to_equity < DEBT_TO_EQUITY_MAX:
        score += 1
    if pe is not None and pe < PE_MAX:
        score += 1
    if upside is not None and upside > UPSIDE_MIN:
        score += 1
    return score
