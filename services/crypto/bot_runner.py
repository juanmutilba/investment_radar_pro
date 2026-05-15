"""
Ciclo bot paper cripto: escaneo, gestión de riesgo y ejecución simulada.
"""
from __future__ import annotations

from typing import Any

_LOG_PREFIX = "[CRYPTO_BOT]"


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def evaluate_entry_candidates(scan_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Candidatos con signal compra_potencial; no abre posiciones."""
    out = [
        r
        for r in scan_results
        if isinstance(r, dict) and not r.get("error") and r.get("signal") == "compra_potencial"
    ]
    _log(f"evaluate_entry_candidates: {len(out)} candidatos")
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
    from services.crypto.watchlist import scan_crypto_watchlist

    if not math.isfinite(amount_usdt) or amount_usdt <= 0:
        raise ValueError("amount_usdt debe ser > 0")
    max_pos = max(1, int(max_open_positions))

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    _log(f"execute_paper_strategy: inicio timeframe={tf} limit={lim} max_open={max_pos}")

    actions: list[dict[str, Any]] = list(review_paper_positions_for_exit())

    scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim)
    scanned_count = len(scan_results)
    candidates = evaluate_entry_candidates(scan_results)
    candidates_count = len(candidates)

    pf = load_portfolio()
    open_count = _count_open_positions(pf)
    opened_count = 0
    entry_attempted = False

    if not candidates:
        portfolio = get_paper_portfolio()
        _log(
            f"execute strategy scanned_count={scanned_count} "
            f"candidates_count=0 opened_count=0"
        )
        return {
            "timeframe": tf,
            "limit": lim,
            "amount_usdt": float(amount_usdt),
            "scanned_count": scanned_count,
            "candidates_count": 0,
            "opened_count": 0,
            "status": "no_opportunity",
            "message": "Sin oportunidades válidas en la watchlist actual.",
            "candidates": [],
            "positions_review": evaluate_open_positions(portfolio),
            "actions": actions,
        }

    for c in candidates:
        sym = str(c.get("symbol") or "").strip()
        if not sym:
            continue
        score = c.get("score")

        if opened_count >= 1:
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

        entry_attempted = True
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
            )
            opened_count += 1
            open_count += 1
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
            actions.append(
                {"action": "entry", "symbol": sym, "status": "skipped", "reason": str(e), "score": score}
            )
            _log(f"execute: {sym} skipped {e}")
        except Exception as e:
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": f"{type(e).__name__}: {e}",
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
    elif not entry_attempted and candidates_count > 0:
        status = "skipped"
        message = "Hubo candidatos, pero se omitieron por duplicados/cash/reglas."
    elif candidates_count == 0:
        status = "no_opportunity"
        message = "Sin oportunidades válidas en la watchlist actual."
    else:
        status = "skipped"
        message = "Hubo candidatos, pero se omitieron por duplicados/cash/reglas."

    _log(
        f"execute strategy scanned_count={scanned_count} "
        f"candidates_count={candidates_count} opened_count={opened_count}"
    )
    return {
        "timeframe": tf,
        "limit": lim,
        "amount_usdt": float(amount_usdt),
        "scanned_count": scanned_count,
        "candidates_count": candidates_count,
        "opened_count": opened_count,
        "status": status,
        "message": message,
        "candidates": candidates,
        "positions_review": positions_review,
        "actions": actions,
    }
