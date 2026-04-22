from __future__ import annotations

import sqlite3
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
    buy_price_cedear_usd: float | None = None,
    buy_price_usa: float | None = None,
    buy_gap: float | None = None,
    score_at_buy: float | None = None,
    signalstate_at_buy: str | None = None,
    techscore_at_buy: float | None = None,
    fundscore_at_buy: float | None = None,
    riskscore_at_buy: float | None = None,
) -> int:
    ts = _now_iso()
    with connection_scope() as conn:
        cur = conn.execute(
            """
            INSERT INTO positions (
              ticker, asset_type, quantity, buy_date,
              buy_price_ars, buy_price_usd, notes,
              buy_price_cedear_usd, buy_price_usa, buy_gap,
              score_at_buy, signalstate_at_buy, techscore_at_buy, fundscore_at_buy, riskscore_at_buy,
              status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                ticker.strip().upper(),
                asset_type,
                quantity,
                buy_date,
                buy_price_ars,
                buy_price_usd,
                notes,
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


def list_positions_by_status(status: str) -> list[sqlite3.Row]:
    with connection_scope() as conn:
        if status == "open":
            q = "SELECT * FROM positions WHERE status = 'open' ORDER BY buy_date DESC, id DESC"
        else:
            q = "SELECT * FROM positions WHERE status = 'closed' ORDER BY sell_date DESC, id DESC"
        return list(conn.execute(q).fetchall())


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
    sell_price_cedear_usd: float | None,
    sell_price_usa: float | None,
    sell_gap: float | None,
    score_at_sell: float | None,
    signalstate_at_sell: str | None,
    techscore_at_sell: float | None,
    fundscore_at_sell: float | None,
    riskscore_at_sell: float | None,
    realized_return_pct: float | None,
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
              holding_days = ?,
              updated_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (
                sell_date,
                sell_price_ars,
                sell_price_usd,
                sell_notes,
                sell_price_cedear_usd,
                sell_price_usa,
                sell_gap,
                score_at_sell,
                signalstate_at_sell,
                techscore_at_sell,
                fundscore_at_sell,
                riskscore_at_sell,
                realized_return_pct,
                holding_days,
                ts,
                position_id,
            ),
        )
        return cur.rowcount > 0


def row_as_mapping(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}
