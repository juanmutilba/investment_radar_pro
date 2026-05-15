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


def open_paper_position(
    symbol: str,
    side: str,
    price: float,
    quantity: float,
    reason: str = "",
) -> dict[str, Any]:
    sym = _validate_long_open(symbol, side, price, quantity)
    cost = price * quantity
    pf = load_portfolio()
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
        "stop_loss": None,
        "take_profit": None,
    }
    pf["cash_usdt"] = cash - cost
    pf["positions"].append(pos)
    save_portfolio(pf)
    _log(f"open: {sym} qty={quantity} @ {price}")
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
