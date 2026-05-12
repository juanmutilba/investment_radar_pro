"""
Motor de oportunidades sobre la cadena merge (Allaria + Rava).
Bull call spread: costo siempre ask compra - bid venta (sin last).
Sin endpoint HTTP; consumir desde scripts o futura API.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

from services.options.models import OptionContract
from services.options.normalizer import normalize_option_type
from services.options.options_service import get_options_chain, resolve_option_chain_spot


def safe_float(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
        if not math.isfinite(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def days_to_expiry(expiry: str | None) -> int | None:
    if expiry is None:
        return None
    s = str(expiry).strip()
    if not s:
        return None
    try:
        d = date.fromisoformat(s[:10])
    except ValueError:
        return None
    today = date.today()
    n = (d - today).days
    if n <= 0:
        return None
    return int(n)


def midpoint(bid: float | None, ask: float | None, last: float | None) -> float | None:
    """Mid para spread_pct; si solo hay bid o solo ask, usa ese lado (sin last salvo ausencia total)."""
    b = safe_float(bid)
    a = safe_float(ask)
    if b is not None and a is not None and b > 0 and a > 0:
        return (b + a) / 2.0
    if b is not None and b > 0:
        return b
    if a is not None and a > 0:
        return a
    return safe_float(last)


def spread_pct(bid: float | None, ask: float | None) -> float | None:
    b = safe_float(bid)
    a = safe_float(ask)
    if b is None or a is None or b <= 0 or a <= 0:
        return None
    mid = midpoint(bid, ask, None)
    if mid is None or mid <= 0:
        return None
    return (a - b) / mid


def annualized_return(net_fraction: float, days: int) -> float | None:
    """Anualiza un retorno fraccional ya dividido por capital (ej. bid/spot)."""
    if days <= 0 or not math.isfinite(net_fraction):
        return None
    r = net_fraction * (365.0 / days)
    return r if math.isfinite(r) else None


def _contract_key(c: OptionContract) -> tuple[str, float, str]:
    exp = (c.expiry or "")[:10]
    st = safe_float(c.strike) or -1.0
    ot = normalize_option_type(c.option_type) or ""
    return (exp, st, ot)


def _dedupe_contracts(contracts: list[OptionContract]) -> list[OptionContract]:
    best: dict[tuple[str, float, str], OptionContract] = {}
    for c in contracts:
        k = _contract_key(c)
        if k[2] not in ("CALL", "PUT"):
            continue
        prev = best.get(k)
        if prev is None:
            best[k] = c
            continue
        v0 = safe_float(prev.volume) or 0.0
        v1 = safe_float(c.volume) or 0.0
        if v1 > v0:
            best[k] = c
    return list(best.values())


def _is_call(c: OptionContract) -> bool:
    return normalize_option_type(c.option_type) == "CALL"


def _call_otm_or_atm(strike: float, spot: float) -> bool:
    if spot <= 0:
        return False
    rel = abs(strike - spot) / spot
    if rel <= 0.03:
        return True
    return strike > spot


def _quality_scan(contracts: list[OptionContract]) -> dict[str, int]:
    vz = 0
    ws = 0
    nba = 0
    for c in contracts:
        vol = safe_float(c.volume)
        if vol is None or vol <= 0:
            vz += 1
        b = safe_float(c.bid)
        a = safe_float(c.ask)
        if b is None or b <= 0 or a is None or a <= 0:
            nba += 1
        sp = spread_pct(c.bid, c.ask)
        if sp is not None and sp > 0.25:
            ws += 1
    return {"volume_zero": vz, "wide_spread": ws, "no_bid_or_ask": nba}


def _leg_dict(side: str, c: OptionContract, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "side": side,
        "type": normalize_option_type(c.option_type) or c.option_type,
        "strike": safe_float(c.strike),
        "symbol": c.symbol,
        "bid": safe_float(c.bid),
        "ask": safe_float(c.ask),
        "last": safe_float(c.last),
        "volume": safe_float(c.volume),
        "source": c.source,
    }
    if extra:
        out.update(extra)
    return out


def _bull_spread_notes(debit: float) -> str:
    parts = ["uses_bid_ask_only"]
    if debit < 0:
        parts.append("credit_spread")
    elif debit == 0:
        parts.append("zero_cost")
    else:
        parts.append("debit_spread")
    return "; ".join(parts)


def scan_options_opportunities(underlying: str) -> dict[str, Any]:
    chain = get_options_chain(underlying)
    spot, _spot_src, _spot_sym, _meta = resolve_option_chain_spot(underlying)
    generated_at = datetime.now(timezone.utc).isoformat()

    quality_flags = _quality_scan(chain.contracts)
    deduped = _dedupe_contracts(chain.contracts)

    covered_calls: list[dict[str, Any]] = []
    if spot is not None and spot > 0:
        for c in deduped:
            if not _is_call(c):
                continue
            strike = safe_float(c.strike)
            if strike is None or strike <= 0:
                continue
            if not _call_otm_or_atm(strike, spot):
                continue
            bid = safe_float(c.bid)
            if bid is None or bid <= 0:
                continue
            vol = safe_float(c.volume)
            if vol is None or vol <= 0:
                continue
            days = days_to_expiry(c.expiry)
            if days is None:
                continue
            premium = bid
            premium_yield = premium / spot
            tna_prem = annualized_return(premium_yield, days)
            upside_px = max(strike - spot, 0.0)
            upside_pct = upside_px / spot
            assigned_return = (premium + upside_px) / spot
            assigned_tna = annualized_return(assigned_return, days)
            sp_ct = spread_pct(c.bid, c.ask)

            if tna_prem is None or not math.isfinite(tna_prem):
                continue

            covered_calls.append(
                {
                    "strategy": "covered_call",
                    "expiry": c.expiry,
                    "days": days,
                    "legs": [_leg_dict("sell", c)],
                    "metrics": {
                        "strike": strike,
                        "premium": round(premium, 6),
                        "premium_yield": round(premium_yield, 8),
                        "tna_premium": round(tna_prem, 6),
                        "upside_pct": round(upside_pct, 8),
                        "assigned_return": round(assigned_return, 8),
                        "assigned_tna": round(assigned_tna, 6) if assigned_tna is not None else None,
                        "spread_pct": round(sp_ct, 6) if sp_ct is not None else None,
                        "volume": vol,
                    },
                    "notes": "Ingreso = bid de la call; TNA prima vs asignación separadas.",
                }
            )

    covered_calls.sort(key=lambda x: float(x["metrics"]["tna_premium"]), reverse=True)
    covered_calls = covered_calls[:20]

    bull_spreads_free: list[dict[str, Any]] = []
    bull_spreads_best_rr: list[dict[str, Any]] = []
    all_bull_for_rr: list[dict[str, Any]] = []

    calls_by_expiry: dict[str, list[OptionContract]] = {}
    for c in deduped:
        if not _is_call(c):
            continue
        exp = (c.expiry or "")[:10]
        if not exp:
            continue
        strike = safe_float(c.strike)
        if strike is None or strike <= 0:
            continue
        ask_b = safe_float(c.ask)
        bid_b = safe_float(c.bid)
        vol = safe_float(c.volume)
        if ask_b is None or ask_b <= 0 or bid_b is None or bid_b <= 0:
            continue
        if vol is None or vol <= 0:
            continue
        calls_by_expiry.setdefault(exp, []).append(c)

    for exp, lst in calls_by_expiry.items():
        lst.sort(key=lambda x: safe_float(x.strike) or 0.0)
        n = len(lst)
        for i in range(n):
            for j in range(i + 1, n):
                buy_c = lst[i]
                sell_c = lst[j]
                buy_k = safe_float(buy_c.strike)
                sell_k = safe_float(sell_c.strike)
                if buy_k is None or sell_k is None or buy_k <= 0 or sell_k <= 0:
                    continue
                if buy_k >= sell_k:
                    continue
                ask_buy = safe_float(buy_c.ask)
                bid_sell = safe_float(sell_c.bid)
                if ask_buy is None or ask_buy <= 0 or bid_sell is None or bid_sell <= 0:
                    continue

                buy_vol = safe_float(buy_c.volume)
                sell_vol = safe_float(sell_c.volume)
                if buy_vol is None or buy_vol <= 0 or sell_vol is None or sell_vol <= 0:
                    continue

                debit = ask_buy - bid_sell
                width = sell_k - buy_k
                if width <= 0:
                    continue

                if debit < 0:
                    credit = abs(debit)
                    max_loss = 0.0
                    max_profit = width + credit
                    free_or_credit = True
                elif debit == 0:
                    credit = 0.0
                    max_loss = 0.0
                    max_profit = width
                    free_or_credit = True
                else:
                    credit = 0.0
                    max_loss = debit
                    max_profit = width - debit
                    free_or_credit = False

                if max_profit <= 0 or not math.isfinite(max_profit):
                    continue

                days = days_to_expiry(exp)
                if days is None:
                    continue

                rr: float | None = None
                if max_loss > 0:
                    rr = max_profit / max_loss

                buy_sp = spread_pct(buy_c.bid, buy_c.ask)
                sell_sp = spread_pct(sell_c.bid, sell_c.ask)

                base_opp: dict[str, Any] = {
                    "strategy": "bull_call_spread",
                    "expiry": buy_c.expiry,
                    "days": days,
                    "legs": [
                        _leg_dict("buy", buy_c),
                        _leg_dict("sell", sell_c),
                    ],
                    "metrics": {
                        "debit": round(debit, 6),
                        "credit": round(credit, 6),
                        "width": round(width, 6),
                        "max_profit": round(max_profit, 6),
                        "max_loss": round(max_loss, 6),
                        "risk_reward": round(rr, 8) if rr is not None and math.isfinite(rr) else None,
                        "free_or_credit": free_or_credit,
                        "buy_ask": round(ask_buy, 6),
                        "sell_bid": round(bid_sell, 6),
                        "buy_volume": buy_vol,
                        "sell_volume": sell_vol,
                        "buy_spread_pct": round(buy_sp, 6) if buy_sp is not None else None,
                        "sell_spread_pct": round(sell_sp, 6) if sell_sp is not None else None,
                    },
                    "notes": _bull_spread_notes(debit),
                }
                all_bull_for_rr.append(base_opp)
                if free_or_credit:
                    bull_spreads_free.append(base_opp)

    bull_spreads_free.sort(key=lambda o: float(o["metrics"]["max_profit"]), reverse=True)
    bull_spreads_free = bull_spreads_free[:20]

    rr_candidates = [o for o in all_bull_for_rr if o["metrics"]["risk_reward"] is not None]
    rr_candidates.sort(
        key=lambda o: float(o["metrics"]["risk_reward"] or 0.0),
        reverse=True,
    )
    bull_spreads_best_rr = rr_candidates[:20]

    return {
        "underlying": chain.underlying,
        "spot": spot,
        "generated_at": generated_at,
        "covered_calls": covered_calls,
        "bull_spreads_free": bull_spreads_free,
        "bull_spreads_best_rr": bull_spreads_best_rr,
        "quality_flags": quality_flags,
    }
