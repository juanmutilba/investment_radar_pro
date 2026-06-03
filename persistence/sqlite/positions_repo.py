from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from persistence.sqlite.connection import connection_scope


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_open_position(
    *,
    ticker: str,
    asset_type: str,
    quantity: float,
    buy_date: str,
    buy_price_ars: float | None,
    buy_price_usd: float | None,
    notes: str | None,
    tc_mep_compra: float | None = None,
    buy_price_cedear_usd: float | None = None,
    buy_price_usa: float | None = None,
    buy_gap: float | None = None,
    score_at_buy: float | None = None,
    signalstate_at_buy: str | None = None,
    techscore_at_buy: float | None = None,
    fundscore_at_buy: float | None = None,
    riskscore_at_buy: float | None = None,
    portfolio_type: str = "radar",
) -> int:
    ts = _now_iso()
    pt = (portfolio_type or "radar").strip().lower()
    if pt not in ("radar", "real"):
        pt = "radar"
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO positions (
              ticker, asset_type, portfolio_type, quantity, buy_date,
              buy_price_ars, buy_price_usd, notes,
              tc_mep_compra,
              buy_price_cedear_usd, buy_price_usa, buy_gap,
              score_at_buy, signalstate_at_buy, techscore_at_buy, fundscore_at_buy, riskscore_at_buy,
              status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                ticker.strip().upper(),
                asset_type,
                pt,
                quantity,
                buy_date,
                buy_price_ars,
                buy_price_usd,
                notes,
                tc_mep_compra,
                buy_price_cedear_usd,
                buy_price_usa,
                buy_gap,
                score_at_buy,
                signalstate_at_buy,
                techscore_at_buy,
                fundscore_at_buy,
                riskscore_at_buy,
                ts,
            ),
        )
        return int(cur.lastrowid)


def list_positions_by_status(status: str, portfolio_type: str = "all") -> list[sqlite3.Row]:
    parts = ["status = ?"]
    params: list[Any] = [status]
    pt = (portfolio_type or "all").strip().lower()
    if pt in ("radar", "real"):
        parts.append("lower(coalesce(portfolio_type, 'radar')) = ?")
        params.append(pt)
    order_col = "buy_date" if status == "open" else "sell_date"
    sql = "SELECT * FROM positions WHERE " + " AND ".join(parts) + f" ORDER BY {order_col} DESC, id DESC"
    with connection_scope() as conn:
        return list(conn.execute(sql, params).fetchall())


def get_position_by_id(position_id: int) -> sqlite3.Row | None:
    with connection_scope() as conn:
        return conn.execute(
            "SELECT * FROM positions WHERE id = ?",
            (position_id,),
        ).fetchone()


def close_position_row(
    position_id: int,
    *,
    sell_date: str,
    sell_price_ars: float | None,
    sell_price_usd: float | None,
    sell_notes: str | None,
    tc_mep_venta: float | None,
    sell_price_cedear_usd: float | None,
    sell_price_usa: float | None,
    sell_gap: float | None,
    score_at_sell: float | None,
    signalstate_at_sell: str | None,
    techscore_at_sell: float | None,
    fundscore_at_sell: float | None,
    riskscore_at_sell: float | None,
    realized_return_pct: float | None,
    realized_return_usd_pct: float | None,
    holding_days: int | None,
) -> bool:
    ts = _now_iso()
    with connection_scope() as conn:
        cur = conn.execute(
            """
            UPDATE positions SET
              sell_date = ?,
              sell_price_ars = ?,
              sell_price_usd = ?,
              sell_notes = ?,
              tc_mep_venta = ?,
              sell_price_cedear_usd = ?,
              sell_price_usa = ?,
              sell_gap = ?,
              score_at_sell = ?,
              signalstate_at_sell = ?,
              techscore_at_sell = ?,
              fundscore_at_sell = ?,
              riskscore_at_sell = ?,
              status = 'closed',
              realized_return_pct = ?,
              realized_return_usd_pct = ?,
              holding_days = ?,
              updated_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (
                sell_date,
                sell_price_ars,
                sell_price_usd,
                sell_notes,
                tc_mep_venta,
                sell_price_cedear_usd,
                sell_price_usa,
                sell_gap,
                score_at_sell,
                signalstate_at_sell,
                techscore_at_sell,
                fundscore_at_sell,
                riskscore_at_sell,
                realized_return_pct,
                realized_return_usd_pct,
                holding_days,
                ts,
                position_id,
            ),
        )
        return cur.rowcount > 0


def row_as_mapping(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _json_dumps(obj: Any) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False)


def list_trades_filtered(
    *,
    status: str,
    instrument_type: str = "all",
    portfolio_type: str = "all",
) -> list[sqlite3.Row]:
    """status: open | closed. instrument_type: all | stock | option | option_strategy. portfolio_type: all | radar | real."""
    parts = ["status = ?"]
    params: list[Any] = [status]
    it = (instrument_type or "all").strip().lower()
    if it == "stock":
        parts.append("lower(coalesce(instrument_type, 'stock')) = 'stock'")
    elif it in ("option", "option_strategy"):
        parts.append("lower(coalesce(instrument_type, '')) = ?")
        params.append(it)
    pt = (portfolio_type or "all").strip().lower()
    if pt in ("radar", "real"):
        parts.append("lower(coalesce(portfolio_type, 'radar')) = ?")
        params.append(pt)
    sql = "SELECT * FROM positions WHERE " + " AND ".join(parts) + " ORDER BY buy_date DESC, id DESC"
    with connection_scope() as conn:
        return list(conn.execute(sql, params).fetchall())


def insert_trade_position(
    *,
    ticker: str,
    asset_type: str,
    quantity: float,
    buy_date: str,
    buy_price_ars: float | None,
    buy_price_usd: float | None,
    notes: str | None,
    instrument_type: str,
    underlying_symbol: str | None,
    strategy_type: str | None,
    option_expiration: str | None,
    initial_debit_credit: float | None,
    committed_capital: float | None,
    max_risk: float | None,
    max_profit: float | None,
    opening_underlying_price: float | None,
    opening_iv: float | None,
    legs: list[dict[str, Any]] | None,
    management_events: list[dict[str, Any]] | None,
    tc_mep_compra: float | None = None,
    portfolio_type: str = "real",
) -> int:
    """Alta de opción o estrategia (instrument_type option | option_strategy)."""
    ts = _now_iso()
    legs_j = _json_dumps(legs) if legs is not None else None
    me_j = _json_dumps(management_events) if management_events is not None else "[]"
    pt = (portfolio_type or "real").strip().lower()
    if pt not in ("radar", "real"):
        pt = "real"
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO positions (
              ticker, asset_type, portfolio_type, quantity, buy_date,
              buy_price_ars, buy_price_usd, notes,
              tc_mep_compra,
              score_at_buy, signalstate_at_buy, techscore_at_buy, fundscore_at_buy, riskscore_at_buy,
              status, updated_at,
              instrument_type, underlying_symbol, strategy_type, option_expiration,
              initial_debit_credit, committed_capital, max_risk, max_profit,
              opening_underlying_price, opening_iv, legs_json, management_events_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker.strip().upper(),
                asset_type,
                pt,
                quantity,
                buy_date,
                buy_price_ars,
                buy_price_usd,
                notes,
                tc_mep_compra,
                ts,
                instrument_type,
                underlying_symbol.strip().upper() if underlying_symbol else None,
                strategy_type,
                option_expiration,
                initial_debit_credit,
                committed_capital,
                max_risk,
                max_profit,
                opening_underlying_price,
                opening_iv,
                legs_j,
                me_j or "[]",
            ),
        )
        return int(cur.lastrowid)


_ALLOWED_TRADE_PATCH = frozenset(
    {
        "ticker",
        "notes",
        "quantity",
        "underlying_symbol",
        "strategy_type",
        "option_expiration",
        "initial_debit_credit",
        "committed_capital",
        "max_risk",
        "max_profit",
        "opening_underlying_price",
        "opening_iv",
        "instrument_type",
        "portfolio_type",
    }
)


def update_trade_position_fields(position_id: int, fields: dict[str, Any]) -> bool:
    """PATCH parcial; legs_json / management_events_json si vienen como list se serializan."""
    cols: list[str] = []
    vals: list[Any] = []
    for k, v in fields.items():
        if k not in _ALLOWED_TRADE_PATCH and k not in ("legs_json", "management_events_json"):
            continue
        if k in ("legs_json", "management_events_json") and isinstance(v, (list, dict)):
            v = _json_dumps(v)
        cols.append(f"{k} = ?")
        vals.append(v)
    if not cols:
        return False
    vals.append(_now_iso())
    vals.append(position_id)
    sql = "UPDATE positions SET " + ", ".join(cols) + ", updated_at = ? WHERE id = ?"
    with connection_scope() as conn:
        cur = conn.execute(sql, vals)
        return cur.rowcount > 0


def append_management_event(position_id: int, event: dict[str, Any]) -> bool:
    row = get_position_by_id(position_id)
    if row is None:
        return False
    d = row_as_mapping(row)
    raw = d.get("management_events_json")
    try:
        evs = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        evs = []
    if not isinstance(evs, list):
        evs = []
    ev = dict(event)
    if not str(ev.get("id") or "").strip():
        ev["id"] = str(uuid.uuid4())
    evs.append(ev)
    ts = _now_iso()
    with connection_scope() as conn:
        cur = conn.execute(
            "UPDATE positions SET management_events_json = ?, updated_at = ? WHERE id = ?",
            (_json_dumps(evs), ts, position_id),
        )
        return cur.rowcount > 0


def portfolio_instrument_metrics(portfolio_type: str = "all") -> dict[str, Any]:
    """Métricas opciones/estrategias (instrument_type ≠ stock), con PnL por cashflows para option_strategy."""
    from services.portfolio_strategy_accounting import (
        compute_legacy_trade_pnl_usd_ars,
        compute_strategy_cashflow_pnl,
        management_events_from_row,
        management_events_have_debit_credit,
        sum_management_events_cashflow,
    )

    pt = (portfolio_type or "all").strip().lower()
    pcond = ""
    pparams: list[Any] = []
    if pt in ("radar", "real"):
        pcond = " AND lower(coalesce(portfolio_type, 'radar')) = ?"
        pparams.append(pt)
    sql = (
        """
                SELECT status, instrument_type, underlying_symbol, committed_capital, max_risk,
                       buy_price_usd, buy_price_ars, sell_price_usd, sell_price_ars, quantity, strategy_type,
                       management_events_json
                FROM positions
                WHERE lower(coalesce(instrument_type, 'stock')) != 'stock'
                """
        + pcond
    )
    with connection_scope() as conn:
        rows = list(conn.execute(sql, pparams).fetchall())

    committed = 0.0
    risk = 0.0
    open_strategies = 0
    open_options = 0
    pnl_closed_non_stock = 0.0
    total_realized_pnl_cashflow = 0.0
    by_under: dict[str, float] = {}
    by_strat: dict[str, float] = {}
    strat_wins = 0
    strat_losses = 0
    closed_strat_pnls: list[float] = []
    closed_strategies_count = 0

    for r in rows:
        d = row_as_mapping(r)
        st = str(d.get("status") or "").lower()
        it = str(d.get("instrument_type") or "").lower()
        und = str(d.get("underlying_symbol") or "").strip().upper() or "—"
        strat = str(d.get("strategy_type") or "custom").strip() or "custom"
        cc = float(d["committed_capital"] or 0) if d.get("committed_capital") is not None else 0.0
        mx = float(d["max_risk"] or 0) if d.get("max_risk") is not None else 0.0
        if st == "open":
            committed += cc
            risk += mx
            if it == "option_strategy":
                open_strategies += 1
            elif it == "option":
                open_options += 1
            continue

        # cerrado
        if it == "option_strategy":
            closed_strategies_count += 1
            evs = management_events_from_row(d)
            if management_events_have_debit_credit(evs):
                total_realized_pnl_cashflow += sum_management_events_cashflow(evs)
            pnl_r = compute_strategy_cashflow_pnl(d)
            if pnl_r is None:
                pnl_r = compute_legacy_trade_pnl_usd_ars(d)
        else:
            pnl_r = compute_legacy_trade_pnl_usd_ars(d)

        pnl_closed_non_stock += pnl_r
        by_under[und] = by_under.get(und, 0.0) + pnl_r
        by_strat[strat] = by_strat.get(strat, 0.0) + pnl_r

        if it == "option_strategy":
            closed_strat_pnls.append(pnl_r)
            if pnl_r > 0:
                strat_wins += 1
            elif pnl_r < 0:
                strat_losses += 1

    strat_total = strat_wins + strat_losses
    win_rate = round(strat_wins / strat_total, 4) if strat_total else None
    avg_strat = round(sum(closed_strat_pnls) / len(closed_strat_pnls), 4) if closed_strat_pnls else None

    best_st: str | None = None
    best_v: float | None = None
    worst_st: str | None = None
    worst_v: float | None = None
    for k, v in by_strat.items():
        if best_v is None or v > best_v:
            best_v = v
            best_st = k
        if worst_v is None or v < worst_v:
            worst_v = v
            worst_st = k

    ptf = pt if pt in ("radar", "real", "all") else "all"
    return {
        "portfolio_type_filter": ptf,
        # nuevos nombres “pro”
        "total_realized_pnl_cashflow": round(total_realized_pnl_cashflow, 4),
        "realized_pnl_by_strategy": {k: round(v, 4) for k, v in sorted(by_strat.items())},
        "realized_pnl_by_underlying": {k: round(v, 4) for k, v in sorted(by_under.items())},
        "open_committed_capital": round(committed, 4),
        "open_max_risk": round(risk, 4),
        "open_option_strategies_count": open_strategies,
        "open_options_count": open_options,
        "closed_option_strategies_count": closed_strategies_count,
        "win_rate_closed_strategies": win_rate,
        "avg_pnl_closed_strategy": avg_strat,
        "best_strategy_by_pnl": (
            {"strategy_type": best_st, "pnl": round(best_v, 4)} if best_st is not None and best_v is not None else None
        ),
        "worst_strategy_by_pnl": (
            {"strategy_type": worst_st, "pnl": round(worst_v, 4)} if worst_st is not None and worst_v is not None else None
        ),
        # compatibilidad
        "committed_capital_total_non_stock_open": round(committed, 4),
        "max_risk_total_non_stock_open": round(risk, 4),
        "realized_pnl_usd_approx_closed_non_stock": round(pnl_closed_non_stock, 4),
        "realized_pnl_by_underlying_usd_approx": {k: round(v, 4) for k, v in sorted(by_under.items())},
        "realized_pnl_by_strategy_type_usd_approx": {k: round(v, 4) for k, v in sorted(by_strat.items())},
        "closed_option_strategies_wins": strat_wins,
        "closed_option_strategies_losses": strat_losses,
        "closed_option_strategies_total": strat_total,
        "closed_option_strategies_win_rate": win_rate,
    }
