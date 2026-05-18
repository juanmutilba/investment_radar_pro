"""Modos de estrategia cripto (paper / escaneo). Sin dependencias pesadas."""

from __future__ import annotations

from typing import Any, Literal

StrategyMode = Literal["trend_swing", "daily_intraday"]

STRATEGY_MODE_TREND_SWING: StrategyMode = "trend_swing"
STRATEGY_MODE_DAILY_INTRADAY: StrategyMode = "daily_intraday"

DAILY_SETUP_TYPES: tuple[str, ...] = (
    "pullback",
    "rebound",
    "momentum_intraday",
    "reversal_controlled",
)


def normalize_strategy_mode(mode: str | None) -> StrategyMode:
    m = (mode or STRATEGY_MODE_TREND_SWING).strip().lower().replace("-", "_")
    if m in ("daily", "daily_intraday", "intraday", "intraday_daily"):
        return STRATEGY_MODE_DAILY_INTRADAY
    return STRATEGY_MODE_TREND_SWING


def is_daily_intraday_mode(strategy_mode: str | None) -> bool:
    return normalize_strategy_mode(strategy_mode) == STRATEGY_MODE_DAILY_INTRADAY


def message_no_candidates(strategy_mode: str | None = None) -> str:
    if is_daily_intraday_mode(strategy_mode):
        return "No hay setups intradía elegibles en la watchlist."
    return "No hay candidatos con señal compra_potencial en la watchlist."


def message_no_candidates_cycle(strategy_mode: str | None = None) -> str:
    if is_daily_intraday_mode(strategy_mode):
        return "No se detectaron setups intradía válidos en este ciclo."
    return "No hay candidatos con señal compra_potencial en la watchlist."


def message_cycle_search_complete(
    *,
    strategy_mode: str | None,
    candidates_count: int,
    scanned_count: int,
) -> str:
    if is_daily_intraday_mode(strategy_mode):
        return (
            f"Búsqueda completada: {candidates_count} candidato(s) intradía "
            f"de {scanned_count} activos escaneados."
        )
    return (
        f"Búsqueda completada: {candidates_count} candidato(s) compra_potencial "
        f"de {scanned_count} activos escaneados."
    )


def scan_scenario_no_candidate_label(strategy_mode: str | None = None) -> str:
    if is_daily_intraday_mode(strategy_mode):
        return "Scanner OK, sin setups intradía elegibles"
    return "Scanner OK, sin compra_potencial"


def scan_scenario_candidates_ok_label(strategy_mode: str | None = None) -> str:
    if is_daily_intraday_mode(strategy_mode):
        return "Candidatos intradía elegibles"
    return "Candidatos compra_potencial"


def is_entry_candidate_row(row: dict[str, Any], strategy_mode: str | None = None) -> bool:
    """Criterio de candidato según modo (sin abrir posiciones)."""
    if not isinstance(row, dict) or row.get("error"):
        return False
    mode = normalize_strategy_mode(strategy_mode or row.get("strategy_mode"))
    if mode == STRATEGY_MODE_TREND_SWING:
        return str(row.get("signal") or "") == "compra_potencial"
    if str(row.get("signal") or "") == "compra_potencial":
        return True
    setup = row.get("setup_type")
    if setup in DAILY_SETUP_TYPES and bool(row.get("entry_eligible")):
        return True
    return False
