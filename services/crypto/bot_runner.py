"""
Ciclo bot paper cripto: escaneo, gestión de riesgo y ejecución simulada.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_LOG_PREFIX = "[CRYPTO_BOT]"

BTC_SYMBOL = "BTC/USDT"


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _norm_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper()


def _is_btc_symbol(symbol: str) -> bool:
    s = _norm_symbol(symbol)
    return s == BTC_SYMBOL or s.replace("/", "") == "BTCUSDT"


def _scan_by_symbol(scan_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in scan_results:
        if isinstance(r, dict):
            sym = _norm_symbol(str(r.get("symbol") or ""))
            if sym:
                out[sym] = r
    return out


def _parse_iso_utc(ts: str) -> datetime | None:
    raw = (ts or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _symbol_in_cooldown(symbol: str, trades: list[Any], cooldown_minutes: int) -> bool:
    if cooldown_minutes <= 0:
        return False
    sym = _norm_symbol(symbol)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=int(cooldown_minutes))
    for t in trades:
        if not isinstance(t, dict):
            continue
        if _norm_symbol(str(t.get("symbol") or "")) != sym:
            continue
        dt = _parse_iso_utc(str(t.get("exit_time") or ""))
        if dt is not None and dt >= cutoff:
            return True
    return False


def _has_open_position(symbol: str, pf: dict[str, Any]) -> bool:
    sym = _norm_symbol(symbol)
    for p in pf.get("positions") or []:
        if not isinstance(p, dict):
            continue
        if str(p.get("status", "open")) != "open":
            continue
        if _norm_symbol(str(p.get("symbol") or "")) == sym:
            return True
    return False


def _btc_trend_favorable(scan_by_sym: dict[str, dict[str, Any]]) -> bool:
    row = scan_by_sym.get(BTC_SYMBOL)
    if not row or row.get("error"):
        return False
    return str(row.get("trend") or "").strip().lower() == "alcista"


def _evaluated_row(
    row: dict[str, Any],
    *,
    status: str,
    reason: str,
) -> dict[str, Any]:
    price = row.get("price")
    return {
        "symbol": row.get("symbol"),
        "signal": row.get("signal"),
        "score": row.get("score"),
        "status": status,
        "reason": reason,
        "price": price if price is None or isinstance(price, (int, float)) else None,
    }


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
                "break_even_active": p.get("break_even_active"),
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


def _primary_no_entry_reason(
    evaluated: list[dict[str, Any]],
    *,
    had_candidates: bool,
) -> str | None:
    if not had_candidates:
        return "no_opportunity"
    for ev in evaluated:
        reason = str(ev.get("reason") or "")
        status = str(ev.get("status") or "")
        if status in ("rejected", "skipped") and reason:
            return reason
    return "no_entry"


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
        "evaluated": [],
        "primary_reason": None,
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
    break_even_trigger_pct: float = 0.0,
    break_even_plus_pct: float = 0.0,
    cooldown_minutes: int = 0,
    require_btc_trend_up: bool = False,
    min_entry_score: float = 0.0,
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
    cooldown_m = max(0, int(cooldown_minutes))
    min_score = float(min_entry_score) if math.isfinite(min_entry_score) and min_entry_score > 0 else 0.0

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    _log(
        f"execute_paper_strategy: inicio timeframe={tf} limit={lim} max_open={max_pos} "
        f"cooldown={cooldown_m} btc_filter={require_btc_trend_up} min_score={min_score}"
    )

    actions: list[dict[str, Any]] = list(review_paper_positions_for_exit())

    scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim)
    scanned_count = len(scan_results)
    scan_by_sym = _scan_by_symbol(scan_results)
    candidates = evaluate_entry_candidates(scan_results)
    candidates_count = len(candidates)

    pf = load_portfolio()
    trades = pf.get("trades") or []
    open_count = _count_open_positions(pf)
    opened_count = 0
    evaluated: list[dict[str, Any]] = []
    primary_reason: str | None = None

    if not candidates:
        portfolio = get_paper_portfolio()
        primary_reason = "no_opportunity"
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
            "primary_reason": primary_reason,
            "candidates": [],
            "evaluated": [],
            "positions_review": evaluate_open_positions(portfolio),
            "actions": actions,
        }

    btc_ok = _btc_trend_favorable(scan_by_sym) if require_btc_trend_up else True

    for c in candidates:
        sym = str(c.get("symbol") or "").strip()
        if not sym:
            continue
        score = c.get("score")

        def _append(status: str, reason: str) -> None:
            nonlocal primary_reason
            evaluated.append(_evaluated_row(c, status=status, reason=reason))
            if primary_reason is None and status in ("rejected", "skipped"):
                primary_reason = reason

        if opened_count >= 1:
            _append("skipped", "max_one_per_run")
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
            _append("skipped", "max_open_positions")
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

        if min_score > 0:
            try:
                sc_val = float(score) if score is not None else None
            except (TypeError, ValueError):
                sc_val = None
            if sc_val is None or sc_val < min_score:
                _append("rejected", "score_below_min")
                actions.append(
                    {
                        "action": "entry",
                        "symbol": sym,
                        "status": "skipped",
                        "reason": "score_below_min",
                        "score": score,
                    }
                )
                continue

        if _has_open_position(sym, pf):
            _append("rejected", "already_open")
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": "already_open",
                    "score": score,
                }
            )
            continue

        if cooldown_m > 0 and _symbol_in_cooldown(sym, trades, cooldown_m):
            _append("rejected", "cooldown_symbol")
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": "cooldown_symbol",
                    "score": score,
                }
            )
            continue

        if require_btc_trend_up and not _is_btc_symbol(sym) and not btc_ok:
            _append("rejected", "btc_trend_filter")
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": "btc_trend_filter",
                    "score": score,
                }
            )
            continue

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
                break_even_trigger_pct=break_even_trigger_pct
                if break_even_trigger_pct > 0
                else None,
                break_even_plus_pct=break_even_plus_pct,
            )
            opened_count += 1
            open_count += 1
            primary_reason = "opened"
            evaluated.append(_evaluated_row(c, status="accepted", reason=reason))
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
            err = str(e)
            skip_reason = "already_open" if "Ya existe" in err or "abierta" in err.lower() else err
            _append("skipped", skip_reason)
            actions.append(
                {"action": "entry", "symbol": sym, "status": "skipped", "reason": skip_reason, "score": score}
            )
            _log(f"execute: {sym} skipped {e}")
        except Exception as e:
            skip_reason = f"{type(e).__name__}: {e}"
            _append("skipped", skip_reason)
            actions.append(
                {
                    "action": "entry",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": skip_reason,
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
        primary_reason = primary_reason or "opened"
    elif candidates_count > 0:
        status = "skipped"
        message = "Hubo candidatos, pero ninguno pasó los filtros de entrada o reglas de cartera."
        if primary_reason is None or primary_reason == "opened":
            primary_reason = _primary_no_entry_reason(evaluated, had_candidates=True)
    else:
        status = "no_opportunity"
        message = "Sin oportunidades válidas en la watchlist actual."
        primary_reason = "no_opportunity"

    _log(
        f"execute strategy scanned_count={scanned_count} "
        f"candidates_count={candidates_count} opened_count={opened_count} "
        f"primary_reason={primary_reason}"
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
        "primary_reason": primary_reason,
        "candidates": candidates,
        "evaluated": evaluated,
        "positions_review": positions_review,
        "actions": actions,
    }


def propose_testnet_entry_from_strategy(
    timeframe: str = "1h",
    limit: int = 200,
    quote_amount_usdt: float = 10.0,
    stop_loss_pct: float = 2.0,
    take_profit_pct: float = 4.0,
    trailing_stop_pct: float = 1.5,
    max_open_positions: int = 3,
    break_even_trigger_pct: float = 0.0,
    break_even_plus_pct: float = 0.0,
    cooldown_minutes: int = 0,
    require_btc_trend_up: bool = False,
    min_entry_score: float = 0.0,
) -> dict[str, Any]:
    """
    Ejecuta el mismo escaneo y filtros de entrada que execute_paper_strategy, pero sin abrir posición paper
    ni orden Binance: devuelve una propuesta BUY testnet para confirmación manual.
    """
    import math

    from services.crypto.binance_testnet import (
        MARKET_ORDER_SYMBOL_WHITELIST,
        MAX_MARKET_ORDER_QUOTE_USDT,
        MIN_MARKET_ORDER_QUOTE_USDT,
        get_testnet_balances,
        testnet_symbol_in_local_order_cooldown,
    )
    from services.crypto.watchlist import scan_crypto_watchlist

    if not math.isfinite(quote_amount_usdt) or quote_amount_usdt <= 0:
        raise ValueError("quote_amount_usdt debe ser > 0")

    q_use = max(MIN_MARKET_ORDER_QUOTE_USDT, min(float(quote_amount_usdt), MAX_MARKET_ORDER_QUOTE_USDT))
    max_pos = max(1, int(max_open_positions))
    cooldown_m = max(0, int(cooldown_minutes))
    min_score = float(min_entry_score) if math.isfinite(min_entry_score) and min_entry_score > 0 else 0.0

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    _log(
        f"propose_testnet_entry: timeframe={tf} limit={lim} quote={q_use} max_open={max_pos} "
        f"cooldown={cooldown_m} btc_filter={require_btc_trend_up} min_score={min_score}"
    )

    scan_results = scan_crypto_watchlist(timeframe=tf, limit=lim)
    scanned_count = len(scan_results)
    scan_by_sym = _scan_by_symbol(scan_results)
    candidates = evaluate_entry_candidates(scan_results)
    candidates_count = len(candidates)

    risk_block: dict[str, float] = {
        "stop_loss_pct": float(stop_loss_pct),
        "take_profit_pct": float(take_profit_pct),
        "trailing_stop_pct": float(trailing_stop_pct),
        "break_even_trigger_pct": float(break_even_trigger_pct),
        "break_even_plus_pct": float(break_even_plus_pct),
    }

    base_evaluated_meta = {
        "timeframe": tf,
        "limit": lim,
        "quote_amount_usdt": q_use,
        "scanned_count": scanned_count,
        "candidates_count": candidates_count,
    }

    if not candidates:
        return {
            "ok": True,
            "proposal": None,
            "primary_reason": "no_opportunity",
            "evaluated": [],
            **base_evaluated_meta,
        }

    bal = get_testnet_balances()
    bal_ok = bool(bal.get("ok"))

    if not bal_ok:
        evaluated_offline: list[dict[str, Any]] = []
        for c in candidates:
            if not isinstance(c, dict):
                continue
            sym = str(c.get("symbol") or "").strip()
            if not sym:
                continue
            evaluated_offline.append(_evaluated_row(c, status="rejected", reason="testnet_balances_unavailable"))
        return {
            "ok": True,
            "proposal": None,
            "primary_reason": "testnet_balances_unavailable",
            "evaluated": evaluated_offline,
            **base_evaluated_meta,
        }

    btc_ok = _btc_trend_favorable(scan_by_sym) if require_btc_trend_up else True

    def free_base_asset(sym_pair: str) -> float:
        parts = sym_pair.split("/", 1)
        base = parts[0].strip().upper() if parts else ""
        if not base:
            return 0.0
        for row in bal.get("balances") or []:
            if str(row.get("asset") or "").upper() == base:
                try:
                    return float(row.get("free") or 0)
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    def count_whitelist_base_positions() -> int:
        bases_in_whitelist = {"BTC", "ETH", "SOL", "BNB"}
        n = 0
        for row in bal.get("balances") or []:
            au = str(row.get("asset") or "").upper()
            if au not in bases_in_whitelist:
                continue
            try:
                free_b = float(row.get("free") or 0)
            except (TypeError, ValueError):
                continue
            if free_b > 1e-6:
                n += 1
        return n

    open_style_count = count_whitelist_base_positions()

    evaluated: list[dict[str, Any]] = []
    proposal: dict[str, Any] | None = None
    primary_reason: str | None = None

    for c in candidates:
        if not isinstance(c, dict):
            continue
        sym = str(c.get("symbol") or "").strip()
        if not sym:
            continue
        score = c.get("score")

        def _append(status: str, reason: str) -> None:
            evaluated.append(_evaluated_row(c, status=status, reason=reason))

        sym_u = _norm_symbol(sym)
        if sym_u not in MARKET_ORDER_SYMBOL_WHITELIST:
            _append("rejected", "not_whitelisted_testnet")
            continue

        if proposal is not None:
            _append("skipped", "max_one_per_run")
            continue

        if open_style_count >= max_pos:
            _append("skipped", "max_open_positions")
            continue

        if min_score > 0:
            try:
                sc_val = float(score) if score is not None else None
            except (TypeError, ValueError):
                sc_val = None
            if sc_val is None or sc_val < min_score:
                _append("rejected", "score_below_min")
                continue

        if free_base_asset(sym_u) > 1e-6:
            _append("rejected", "already_hold_base_testnet")
            continue

        if cooldown_m > 0 and testnet_symbol_in_local_order_cooldown(sym_u, cooldown_m):
            _append("rejected", "cooldown_symbol")
            continue

        if require_btc_trend_up and not _is_btc_symbol(sym_u) and not btc_ok:
            _append("rejected", "btc_trend_filter")
            continue

        sig = str(c.get("signal") or "")
        reason_txt = f"estrategia_coincidente_con_paper score={score}" if score is not None else "estrategia_coincidente_con_paper"

        score_out: float | None
        if isinstance(score, (int, float)) and math.isfinite(float(score)):
            score_out = float(score)
        else:
            score_out = None

        proposal = {
            "symbol": sym_u,
            "side": "buy",
            "quote_amount_usdt": q_use,
            "score": score_out,
            "signal": sig,
            "reason": reason_txt,
            "timeframe": tf,
            "risk": risk_block,
        }
        _append("selected", reason_txt)
        primary_reason = None
        break

    if proposal is None:
        primary_reason = primary_reason or _primary_no_entry_reason(evaluated, had_candidates=candidates_count > 0)
        if primary_reason is None:
            primary_reason = "no_entry"

    _log(f"propose_testnet_entry: fin has_proposal={proposal is not None} primary_reason={primary_reason}")

    out: dict[str, Any] = {
        "ok": True,
        "proposal": proposal,
        "primary_reason": primary_reason if proposal is None else None,
        "evaluated": evaluated,
        **base_evaluated_meta,
    }
    return out
