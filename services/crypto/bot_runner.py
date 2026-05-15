"""
Ciclo bot paper cripto: escaneo y evaluación sin órdenes ni aperturas/cierres automáticos.
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
    """Revisión de posiciones abiertas enriquecidas; no cierra automáticamente."""
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
                "current_price": p.get("current_price"),
                "unrealized_pnl_usdt": p.get("unrealized_pnl_usdt"),
                "unrealized_pnl_pct": p.get("unrealized_pnl_pct"),
                "price_error": p.get("price_error"),
            }
        )
    _log(f"evaluate_open_positions: {len(review)} posiciones")
    return review


def run_crypto_paper_cycle(timeframe: str = "1h", limit: int = 200) -> dict[str, Any]:
    """
    Ejecuta scanner watchlist, filtra candidatos y revisa cartera paper.
    actions siempre vacío hasta activar lógica automática.
    """
    from services.crypto.paper_portfolio import get_paper_portfolio
    from services.crypto.watchlist import scan_crypto_watchlist

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    _log(f"run_crypto_paper_cycle: inicio timeframe={tf} limit={lim}")

    scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim)
    candidates = evaluate_entry_candidates(scan_results)
    portfolio = get_paper_portfolio()
    positions_review = evaluate_open_positions(portfolio)

    _log("run_crypto_paper_cycle: fin (sin acciones automáticas)")
    return {
        "timeframe": tf,
        "limit": lim,
        "candidates": candidates,
        "positions_review": positions_review,
        "actions": [],
    }


def execute_paper_strategy(
    timeframe: str = "1h",
    limit: int = 200,
    amount_usdt: float = 100.0,
) -> dict[str, Any]:
    """
    Escanea candidatos compra_potencial e intenta abrir paper por monto USDT.
    Sin órdenes reales; omite símbolos ya abiertos o sin cash.
    """
    import math

    from services.crypto.paper_portfolio import (
        get_paper_portfolio,
        open_paper_position_market_by_amount,
    )

    if not math.isfinite(amount_usdt) or amount_usdt <= 0:
        raise ValueError("amount_usdt debe ser > 0")

    cycle = run_crypto_paper_cycle(timeframe=timeframe, limit=limit)
    candidates: list[dict[str, Any]] = cycle.get("candidates") or []
    actions: list[dict[str, Any]] = []

    if not candidates:
        _log("execute_paper_strategy: sin candidatos")
        return {
            **cycle,
            "amount_usdt": float(amount_usdt),
            "actions": actions,
            "message": "Sin oportunidades",
        }

    _log(f"execute_paper_strategy: {len(candidates)} candidatos amount_usdt={amount_usdt}")
    for c in candidates:
        sym = str(c.get("symbol") or "").strip()
        if not sym:
            continue
        score = c.get("score")
        reason = f"estrategia_paper score={score}" if score is not None else "estrategia_paper"
        try:
            open_paper_position_market_by_amount(
                symbol=sym,
                side="long",
                amount_usdt=amount_usdt,
                reason=reason,
            )
            actions.append(
                {
                    "symbol": sym,
                    "status": "executed",
                    "amount_usdt": float(amount_usdt),
                    "score": score,
                }
            )
            _log(f"execute: {sym} executed")
        except ValueError as e:
            actions.append({"symbol": sym, "status": "skipped", "reason": str(e), "score": score})
            _log(f"execute: {sym} skipped {e}")
        except Exception as e:
            actions.append(
                {
                    "symbol": sym,
                    "status": "skipped",
                    "reason": f"{type(e).__name__}: {e}",
                    "score": score,
                }
            )
            _log(f"execute: {sym} error {e}")

    portfolio = get_paper_portfolio()
    positions_review = evaluate_open_positions(portfolio)
    executed_n = sum(1 for a in actions if a.get("status") == "executed")
    _log(f"execute_paper_strategy: fin executed={executed_n} skipped={len(actions) - executed_n}")
    return {
        "timeframe": cycle["timeframe"],
        "limit": cycle["limit"],
        "amount_usdt": float(amount_usdt),
        "candidates": candidates,
        "positions_review": positions_review,
        "actions": actions,
        "message": None if executed_n > 0 else "Sin oportunidades ejecutadas",
    }
