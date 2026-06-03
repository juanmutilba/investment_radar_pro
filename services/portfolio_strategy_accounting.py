"""
Contabilidad por cashflows para option_strategy (management_events[].debit_credit).

Convención: débito = negativo, crédito = positivo (flujo de caja neto hacia el inversor).
"""
from __future__ import annotations

import json
from typing import Any


def management_events_from_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("management_events_json")
    if raw is None and "management_events" in row:
        evs = row.get("management_events")
        return evs if isinstance(evs, list) else []
    if not raw:
        return []
    try:
        evs = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    return evs if isinstance(evs, list) else []


def management_events_have_debit_credit(events: list[dict[str, Any]]) -> bool:
    """True si al menos un evento trae debit_credit explícito (incl. 0)."""
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if "debit_credit" in ev and ev.get("debit_credit") is not None:
            return True
    return False


def sum_management_events_cashflow(events: list[dict[str, Any]]) -> float:
    total = 0.0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        v = ev.get("debit_credit")
        if v is None:
            continue
        try:
            total += float(v)
        except (TypeError, ValueError):
            continue
    return total


def compute_strategy_cashflow_total(row: dict[str, Any]) -> float:
    """Suma de todos los debit_credit en eventos (eventos sin monto no suman)."""
    return sum_management_events_cashflow(management_events_from_row(row))


def compute_strategy_is_closed(row: dict[str, Any]) -> bool:
    if str(row.get("status") or "").lower() == "closed":
        return True
    for ev in management_events_from_row(row):
        if not isinstance(ev, dict):
            continue
        if str(ev.get("event_type") or "").lower() == "full_close":
            return True
    return False


def compute_legacy_trade_pnl_usd_ars(row: dict[str, Any]) -> float:
    """PnL aproximado por precio compra/venta × cantidad (USD o ARS)."""
    try:
        q = float(row.get("quantity") or 0)
        bp_u = float(row["buy_price_usd"]) if row.get("buy_price_usd") is not None else None
        sp_u = float(row["sell_price_usd"]) if row.get("sell_price_usd") is not None else None
        if bp_u is not None and sp_u is not None:
            return (sp_u - bp_u) * q
        bp_a = float(row["buy_price_ars"]) if row.get("buy_price_ars") is not None else None
        sp_a = float(row["sell_price_ars"]) if row.get("sell_price_ars") is not None else None
        if bp_a is not None and sp_a is not None:
            return (sp_a - bp_a) * q
    except (TypeError, ValueError):
        pass
    return 0.0


def compute_strategy_cashflow_pnl(row: dict[str, Any]) -> float | None:
    """
    PnL realizado para option_strategy cerrada.

    - Si hay eventos con debit_credit: PnL = suma de cashflows.
    - Si no: PnL legacy por buy/sell (compatibilidad).
    - Si no es option_strategy o no está cerrada: None.
    """
    if str(row.get("instrument_type") or "").lower() != "option_strategy":
        return None
    if not compute_strategy_is_closed(row):
        return None
    evs = management_events_from_row(row)
    if management_events_have_debit_credit(evs):
        return sum_management_events_cashflow(evs)
    return compute_legacy_trade_pnl_usd_ars(row)


def option_strategy_use_cashflow_pnl(row: dict[str, Any]) -> bool:
    """True si la fila cerrada option_strategy usa contabilidad por eventos."""
    if str(row.get("instrument_type") or "").lower() != "option_strategy":
        return False
    if not compute_strategy_is_closed(row):
        return False
    return management_events_have_debit_credit(management_events_from_row(row))


def normalize_leg_multiplier(leg: dict[str, Any]) -> dict[str, Any]:
    out = dict(leg)
    m = out.get("multiplier")
    try:
        mf = float(m) if m is not None else 0.0
    except (TypeError, ValueError):
        mf = 0.0
    if mf <= 0:
        out["multiplier"] = 100.0
    return out
