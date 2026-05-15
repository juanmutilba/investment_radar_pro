"""
Cartera cripto paper (simulación local). Sin órdenes reales en Binance.
Persistencia: data/crypto_paper_portfolio.json
"""
from __future__ import annotations

import json
import math
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG_PREFIX = "[CRYPTO_PAPER]"

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_PORTFOLIO_FILE = _BASE_DIR / "data" / "crypto_paper_portfolio.json"
_DEFAULT_INITIAL_CASH = 10_000.0


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_portfolio(initial_cash: float = _DEFAULT_INITIAL_CASH) -> dict[str, Any]:
    return {
        "cash_usdt": float(initial_cash),
        "positions": [],
        "trades": [],
    }


def load_portfolio() -> dict[str, Any]:
    """Carga JSON o devuelve cartera vacía con cash por defecto."""
    if not _PORTFOLIO_FILE.exists():
        _log("load: archivo inexistente, usando defaults")
        return _default_portfolio()
    try:
        raw = _PORTFOLIO_FILE.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else _default_portfolio()
    except (json.JSONDecodeError, OSError) as e:
        _log(f"load: error {e}, usando defaults")
        return _default_portfolio()
    if not isinstance(data, dict):
        return _default_portfolio()
    if "cash_usdt" not in data:
        data["cash_usdt"] = _DEFAULT_INITIAL_CASH
    if not isinstance(data.get("positions"), list):
        data["positions"] = []
    if not isinstance(data.get("trades"), list):
        data["trades"] = []
    return data


def save_portfolio(portfolio: dict[str, Any]) -> None:
    _PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PORTFOLIO_FILE.write_text(
        json.dumps(portfolio, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _log("save: OK")


def reset_paper_portfolio(initial_cash: float = _DEFAULT_INITIAL_CASH) -> dict[str, Any]:
    if not math.isfinite(initial_cash) or initial_cash < 0:
        raise ValueError("initial_cash debe ser un número >= 0")
    pf = _default_portfolio(initial_cash)
    save_portfolio(pf)
    _log(f"reset: cash_usdt={initial_cash}")
    return deepcopy(pf)


def _reject_duplicate_open(symbol: str, pf: dict[str, Any] | None = None) -> None:
    """Evita dos posiciones long abiertas en el mismo símbolo."""
    sym = (symbol or "").strip().upper()
    data = pf if pf is not None else load_portfolio()
    for p in data.get("positions") or []:
        if not isinstance(p, dict):
            continue
        if str(p.get("status", "open")) != "open":
            continue
        if str(p.get("symbol") or "").strip().upper() == sym:
            raise ValueError(f"Ya existe una posición paper abierta para {sym}")


def _validate_long_open(symbol: str, side: str, price: float, quantity: float) -> str:
    sym = (symbol or "").strip().upper()
    if not sym or "/" not in sym:
        raise ValueError("symbol inválido (ej. BTC/USDT)")
    s = (side or "").strip().lower()
    if s != "long":
        raise ValueError("solo side='long' está soportado por ahora")
    if not math.isfinite(price) or price <= 0:
        raise ValueError("price debe ser > 0")
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("quantity debe ser > 0")
    return sym


def _count_open_positions(pf: dict[str, Any] | None = None) -> int:
    data = pf if pf is not None else load_portfolio()
    n = 0
    for p in data.get("positions") or []:
        if isinstance(p, dict) and str(p.get("status", "open")) == "open":
            n += 1
    return n


def _apply_risk_fields(
    pos: dict[str, Any],
    entry_price: float,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    trailing_stop_pct: float | None = None,
    break_even_trigger_pct: float | None = None,
    break_even_plus_pct: float | None = None,
    exit_policy: str | None = None,
) -> None:
    pos["highest_price"] = round(float(entry_price), 8)
    pos["stop_loss"] = None
    pos["take_profit"] = None
    pos["trailing_stop_pct"] = None
    pos["break_even_trigger_pct"] = None
    pos["break_even_plus_pct"] = None
    pos["break_even_active"] = False
    pos["exit_policy"] = (exit_policy or "").strip() or None

    if stop_loss_pct is not None and math.isfinite(stop_loss_pct) and stop_loss_pct > 0:
        pos["stop_loss"] = round(entry_price * (1.0 - stop_loss_pct / 100.0), 8)
    if take_profit_pct is not None and math.isfinite(take_profit_pct) and take_profit_pct > 0:
        pos["take_profit"] = round(entry_price * (1.0 + take_profit_pct / 100.0), 8)
    if trailing_stop_pct is not None and math.isfinite(trailing_stop_pct) and trailing_stop_pct > 0:
        pos["trailing_stop_pct"] = round(float(trailing_stop_pct), 6)
    if (
        break_even_trigger_pct is not None
        and math.isfinite(break_even_trigger_pct)
        and break_even_trigger_pct > 0
    ):
        pos["break_even_trigger_pct"] = round(float(break_even_trigger_pct), 6)
        plus = break_even_plus_pct if break_even_plus_pct is not None else 0.0
        pos["break_even_plus_pct"] = round(float(plus), 6) if math.isfinite(float(plus)) else 0.0

    if not pos["exit_policy"]:
        parts: list[str] = []
        if pos["stop_loss"] is not None:
            parts.append("stop_loss")
        if pos["take_profit"] is not None:
            parts.append("take_profit")
        if pos["trailing_stop_pct"] is not None:
            parts.append("trailing_stop")
        if pos.get("break_even_trigger_pct") is not None:
            parts.append("break_even")
        if parts:
            pos["exit_policy"] = "+".join(parts)


def _maybe_apply_break_even(p: dict[str, Any], current_price: float) -> bool:
    """Sube stop_loss a break-even si se alcanzó el trigger; nunca baja el stop existente."""
    raw_trig = p.get("break_even_trigger_pct")
    if raw_trig is None:
        return False
    try:
        trigger_pct = float(raw_trig)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(trigger_pct) or trigger_pct <= 0:
        return False

    entry = float(p.get("entry_price") or 0)
    if entry <= 0 or current_price < entry * (1.0 + trigger_pct / 100.0):
        return False

    plus_raw = p.get("break_even_plus_pct")
    plus_pct = float(plus_raw) if plus_raw is not None and math.isfinite(float(plus_raw)) else 0.0
    be_sl = entry * (1.0 + plus_pct / 100.0)

    cur_sl = p.get("stop_loss")
    if cur_sl is None or not math.isfinite(float(cur_sl)):
        new_sl = be_sl
    else:
        new_sl = max(float(cur_sl), be_sl)

    changed = False
    if cur_sl is None or abs(new_sl - float(cur_sl)) > 1e-12:
        p["stop_loss"] = round(new_sl, 8)
        changed = True
    if not p.get("break_even_active"):
        p["break_even_active"] = True
        changed = True
    return changed


def _fetch_symbol_price(symbol: str) -> float:
    from services.crypto.providers import binance_provider as bp

    tick = bp.fetch_ticker(symbol)
    if not isinstance(tick, dict):
        raise ValueError("respuesta de ticker inválida")
    return _ticker_market_price(tick)


def _ticker_market_price(tick: dict[str, Any]) -> float:
    for key in ("last", "close"):
        raw = tick.get(key)
        if raw is not None and isinstance(raw, (int, float)) and math.isfinite(float(raw)):
            p = float(raw)
            if p > 0:
                return p
    raise ValueError("precio de mercado no disponible en ticker (last/close)")


def open_paper_position_market(
    symbol: str,
    side: str,
    quantity: float,
    reason: str = "",
    break_even_trigger_pct: float | None = None,
    break_even_plus_pct: float | None = None,
) -> dict[str, Any]:
    """Abre posición paper al precio actual de Binance (ticker público; sin orden real)."""
    sym = (symbol or "").strip().upper()
    if not sym or "/" not in sym:
        raise ValueError("symbol inválido (ej. BTC/USDT)")
    s = (side or "").strip().lower()
    if s != "long":
        raise ValueError("solo side='long' está soportado por ahora")
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("quantity debe ser > 0")

    from services.crypto.providers import binance_provider as bp

    tick = bp.fetch_ticker(sym)
    if not isinstance(tick, dict):
        raise ValueError("respuesta de ticker inválida")
    price = _ticker_market_price(tick)
    _log(f"open_market: {sym} ticker price={price}")
    return open_paper_position(
        symbol=sym,
        side=side,
        price=price,
        quantity=quantity,
        reason=reason,
        price_source="binance_ticker",
        break_even_trigger_pct=break_even_trigger_pct,
        break_even_plus_pct=break_even_plus_pct,
    )


def open_paper_position_market_by_amount(
    symbol: str,
    side: str,
    amount_usdt: float,
    reason: str = "",
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    trailing_stop_pct: float | None = None,
    break_even_trigger_pct: float | None = None,
    break_even_plus_pct: float | None = None,
    exit_policy: str | None = None,
) -> dict[str, Any]:
    """Abre posición paper por monto USDT al precio ticker (sin orden real)."""
    sym = (symbol or "").strip().upper()
    if not sym or "/" not in sym:
        raise ValueError("symbol inválido (ej. BTC/USDT)")
    s = (side or "").strip().lower()
    if s != "long":
        raise ValueError("solo side='long' está soportado por ahora")
    if not math.isfinite(amount_usdt) or amount_usdt <= 0:
        raise ValueError("amount_usdt debe ser > 0")

    pf = load_portfolio()
    cash = float(pf.get("cash_usdt") or 0)
    if amount_usdt > cash + 1e-9:
        raise ValueError(
            f"cash_usdt insuficiente: necesario {amount_usdt:.2f}, disponible {cash:.2f}"
        )

    from services.crypto.providers import binance_provider as bp

    tick = bp.fetch_ticker(sym)
    if not isinstance(tick, dict):
        raise ValueError("respuesta de ticker inválida")
    price = _ticker_market_price(tick)
    quantity = amount_usdt / price
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("quantity calculada inválida")

    _log(
        f"open_market_amount: {sym} amount_usdt={amount_usdt:.2f} "
        f"price={price} qty={quantity:.8f}"
    )
    return open_paper_position(
        symbol=sym,
        side=side,
        price=price,
        quantity=quantity,
        reason=reason,
        price_source="binance_ticker",
        amount_usdt=amount_usdt,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        break_even_trigger_pct=break_even_trigger_pct,
        break_even_plus_pct=break_even_plus_pct,
        exit_policy=exit_policy,
    )


def open_paper_position(
    symbol: str,
    side: str,
    price: float,
    quantity: float,
    reason: str = "",
    price_source: str | None = None,
    amount_usdt: float | None = None,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    trailing_stop_pct: float | None = None,
    break_even_trigger_pct: float | None = None,
    break_even_plus_pct: float | None = None,
    exit_policy: str | None = None,
) -> dict[str, Any]:
    sym = _validate_long_open(symbol, side, price, quantity)
    cost = price * quantity
    pf = load_portfolio()
    _reject_duplicate_open(sym, pf)
    cash = float(pf.get("cash_usdt") or 0)
    if cost > cash + 1e-9:
        raise ValueError(
            f"cash_usdt insuficiente: necesario {cost:.2f}, disponible {cash:.2f}"
        )
    pos = {
        "id": str(uuid.uuid4()),
        "symbol": sym,
        "side": "long",
        "quantity": quantity,
        "entry_price": price,
        "entry_time": _now_iso(),
        "entry_reason": (reason or "").strip(),
        "status": "open",
    }
    _apply_risk_fields(
        pos,
        price,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        break_even_trigger_pct=break_even_trigger_pct,
        break_even_plus_pct=break_even_plus_pct,
        exit_policy=exit_policy,
    )
    if price_source:
        pos["price_source"] = price_source
    if amount_usdt is not None and math.isfinite(amount_usdt) and amount_usdt > 0:
        pos["amount_usdt"] = round(float(amount_usdt), 8)
    pf["cash_usdt"] = cash - cost
    pf["positions"].append(pos)
    save_portfolio(pf)
    amt_log = f" amount_usdt={amount_usdt:.2f}" if amount_usdt else ""
    _log(f"open: {sym} qty={quantity} @ {price}{amt_log}")
    return deepcopy(pos)


def close_paper_position(position_id: str, price: float, reason: str = "") -> dict[str, Any]:
    if not (position_id or "").strip():
        raise ValueError("position_id requerido")
    if not math.isfinite(price) or price <= 0:
        raise ValueError("price debe ser > 0")
    pf = load_portfolio()
    positions: list[dict[str, Any]] = pf.get("positions") or []
    idx = None
    pos = None
    for i, p in enumerate(positions):
        if isinstance(p, dict) and str(p.get("id")) == position_id.strip():
            if str(p.get("status", "open")) != "open":
                raise ValueError("la posición ya está cerrada")
            idx = i
            pos = p
            break
    if pos is None or idx is None:
        raise ValueError("posición no encontrada o ya cerrada")

    qty = float(pos["quantity"])
    entry = float(pos["entry_price"])
    exit_time = _now_iso()
    pnl_usdt = (price - entry) * qty
    pnl_pct = ((price / entry) - 1.0) * 100.0 if entry > 0 else 0.0

    trade = {
        "id": str(uuid.uuid4()),
        "symbol": pos["symbol"],
        "side": pos.get("side", "long"),
        "quantity": qty,
        "entry_price": entry,
        "exit_price": price,
        "entry_time": pos.get("entry_time"),
        "exit_time": exit_time,
        "entry_reason": pos.get("entry_reason") or "",
        "exit_reason": (reason or "").strip(),
        "pnl_usdt": round(pnl_usdt, 8),
        "pnl_pct": round(pnl_pct, 6),
    }
    proceeds = price * qty
    pf["cash_usdt"] = float(pf.get("cash_usdt") or 0) + proceeds
    positions.pop(idx)
    pf["positions"] = positions
    trades: list[dict[str, Any]] = pf.get("trades") or []
    trades.append(trade)
    pf["trades"] = trades
    save_portfolio(pf)
    _log(f"close: {pos['symbol']} pnl_usdt={pnl_usdt:.2f}")
    return deepcopy(trade)


def review_paper_positions_for_exit() -> list[dict[str, Any]]:
    """Revisa SL/TP/trailing y cierra posiciones paper que cumplan regla de salida."""
    pf = load_portfolio()
    actions: list[dict[str, Any]] = []
    to_close: list[tuple[str, str, float, str]] = []
    dirty = False

    for p in pf.get("positions") or []:
        if not isinstance(p, dict) or str(p.get("status", "open")) != "open":
            continue
        sym = str(p.get("symbol") or "").strip()
        pos_id = str(p.get("id") or "")
        if not sym or not pos_id:
            continue
        try:
            cp = _fetch_symbol_price(sym)
        except Exception as e:
            actions.append(
                {
                    "action": "exit",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": f"{type(e).__name__}: {e}",
                }
            )
            _log(f"review_exit: {sym} skip precio {e}")
            continue

        entry = float(p.get("entry_price") or 0)
        highest = float(p.get("highest_price") or entry or 0)
        if cp > highest:
            p["highest_price"] = round(cp, 8)
            highest = cp
            dirty = True

        if _maybe_apply_break_even(p, cp):
            dirty = True

        exit_reason: str | None = None
        sl = p.get("stop_loss")
        if sl is not None and math.isfinite(float(sl)) and cp <= float(sl):
            exit_reason = "stop_loss"
        else:
            tp = p.get("take_profit")
            if tp is not None and math.isfinite(float(tp)) and cp >= float(tp):
                exit_reason = "take_profit"
            else:
                tsp = p.get("trailing_stop_pct")
                if (
                    tsp is not None
                    and math.isfinite(float(tsp))
                    and float(tsp) > 0
                    and highest > 0
                    and cp <= highest * (1.0 - float(tsp) / 100.0)
                ):
                    exit_reason = "trailing_stop"

        if exit_reason:
            to_close.append((pos_id, sym, cp, exit_reason))

    if dirty:
        save_portfolio(pf)

    for pos_id, sym, cp, exit_reason in to_close:
        try:
            close_paper_position(pos_id, cp, reason=exit_reason)
            actions.append(
                {
                    "action": "exit",
                    "symbol": sym,
                    "status": "executed",
                    "reason": exit_reason,
                }
            )
            _log(f"review_exit: {sym} closed {exit_reason} @ {cp}")
        except Exception as e:
            actions.append(
                {
                    "action": "exit",
                    "symbol": sym,
                    "status": "skipped",
                    "reason": str(e),
                }
            )
            _log(f"review_exit: {sym} error cierre {e}")

    _log(f"review_paper_positions_for_exit: {len(actions)} acciones")
    return actions


def _enrich_position(pos: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(pos)
    sym = str(out.get("symbol") or "")
    qty = float(out.get("quantity") or 0)
    entry = float(out.get("entry_price") or 0)
    out["current_price"] = None
    out["market_value_usdt"] = None
    out["unrealized_pnl_usdt"] = None
    out["unrealized_pnl_pct"] = None
    out["price_error"] = None
    if not sym:
        out["price_error"] = "symbol vacío"
        return out
    try:
        from services.crypto.providers import binance_provider as bp

        tick = bp.fetch_ticker(sym)
        last = tick.get("last") if isinstance(tick, dict) else None
        if last is None or not isinstance(last, (int, float)) or not math.isfinite(float(last)):
            out["price_error"] = "precio actual no disponible"
            return out
        cp = float(last)
        out["current_price"] = cp
        mv = cp * qty
        out["market_value_usdt"] = round(mv, 8)
        if entry > 0:
            out["unrealized_pnl_usdt"] = round((cp - entry) * qty, 8)
            out["unrealized_pnl_pct"] = round(((cp / entry) - 1.0) * 100.0, 6)
    except Exception as e:
        out["price_error"] = f"{type(e).__name__}: {e}"
    return out


def get_paper_portfolio() -> dict[str, Any]:
    pf = load_portfolio()
    cash = float(pf.get("cash_usdt") or 0)
    open_positions = [p for p in (pf.get("positions") or []) if isinstance(p, dict)]
    enriched = [_enrich_position(p) for p in open_positions]
    market_total = sum(float(p.get("market_value_usdt") or 0) for p in enriched)
    unrealized = sum(float(p.get("unrealized_pnl_usdt") or 0) for p in enriched)
    equity = cash + market_total
    trades = [t for t in (pf.get("trades") or []) if isinstance(t, dict)]
    trades_sorted = sorted(
        trades,
        key=lambda t: str(t.get("exit_time") or ""),
        reverse=True,
    )
    recent_trades = trades_sorted[:30]
    return {
        "cash_usdt": round(cash, 8),
        "equity_usdt": round(equity, 8),
        "unrealized_pnl_usdt": round(unrealized, 8),
        "positions": enriched,
        "trades": recent_trades,
        "trades_total": len(trades),
    }
