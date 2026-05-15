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
