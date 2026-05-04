from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from services.options.expiry_utils import resolve_expiry_date


def _as_str(x: Any) -> str:
    if x is None:
        return ""
    try:
        return str(x)
    except Exception:
        return ""


def _pick_symbol(item: dict[str, Any]) -> str:
    for k in ("especie", "simbolo"):
        v = item.get(k)
        s = _as_str(v).strip()
        if s:
            return s
    return ""


_TRAILING_EXP_RE = re.compile(r"^(?P<strike>.*?)(?P<exp>\.*[A-Z]+)$", re.IGNORECASE)


def _parse_option_symbol(raw_symbol: str) -> dict[str, str] | None:
    """
    Misma heurística que scripts/debug_rava_options_parse.py (copiada para uso interno).
    """
    s = (raw_symbol or "").strip().upper()
    if not s:
        return None

    idx = -1
    opt_type = ""
    for i, ch in enumerate(s[:-1]):
        if ch in ("C", "V") and s[i + 1].isdigit():
            idx = i
            opt_type = ch
            break
    if idx <= 0:
        return None

    underlying = s[:idx]
    rest = s[idx + 1 :]
    if not underlying or not rest:
        return None

    expiry_raw = ""
    m = _TRAILING_EXP_RE.match(rest)
    if m:
        expiry_raw = (m.group("exp") or "").replace(".", "").strip().upper()
        strike_part = (m.group("strike") or "").strip()
    else:
        strike_part = rest.strip()

    strike_part = strike_part.rstrip(".")
    m2 = re.match(r"^(?P<num>[0-9]+(?:\.[0-9]+)?)", strike_part)
    strike_raw = m2.group("num") if m2 else ""

    return {
        "underlying_guess": underlying,
        "option_type": opt_type,
        "strike_raw": strike_raw,
        "expiry_code_raw": expiry_raw,
    }


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _safe_volumen_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _safe_operaciones_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _resolve_option_price(ultimo: float | None) -> float | None:
    if ultimo is not None and ultimo > 0:
        return ultimo
    return None


def _spread_abs(bid: float | None, ask: float | None) -> float | None:
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return ask - bid
    return None


def _normalize_underlying_prices(prices: dict[Any, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in prices.items():
        ku = _as_str(k).strip().upper()
        if ku:
            out[ku] = v
    return out


def _moneyness_fields(
    option_type: str,
    underlying_price: float | None,
    strike: float,
) -> tuple[float | None, float | None, str | None]:
    if underlying_price is None or underlying_price <= 0 or strike <= 0:
        return None, None, None
    moneyness = underlying_price / strike
    rel = abs(underlying_price - strike) / strike
    if rel <= 0.02:
        return underlying_price, moneyness, "ATM"
    if option_type == "C":
        return underlying_price, moneyness, ("ITM" if underlying_price > strike else "OTM")
    if option_type == "V":
        return underlying_price, moneyness, ("ITM" if underlying_price < strike else "OTM")
    return underlying_price, moneyness, None


def _option_row(
    item: dict[str, Any],
    *,
    expiry_code_raw: str,
    expiry_date: date | None,
    underlying_price: float | None,
    strike: float,
    option_type: str,
) -> dict[str, Any]:
    sym = _pick_symbol(item)
    expiry_iso = expiry_date.isoformat() if expiry_date is not None else None
    days_to_expiry = (expiry_date - date.today()).days if expiry_date is not None else None
    bid_f = _safe_float(item.get("preciocompra"))
    ask_f = _safe_float(item.get("precioventa"))
    ult_f = _safe_float(item.get("ultimo"))
    spread_abs = _spread_abs(bid_f, ask_f)
    uprice, mny, mstat = _moneyness_fields(option_type, underlying_price, strike)
    vol_f = _safe_volumen_float(item.get("volnominal"))
    op_i = _safe_operaciones_int(item.get("operaciones"))
    has_volume = vol_f is not None and vol_f > 0
    has_trades = op_i is not None and op_i > 0
    return {
        "simbolo": sym,
        "ultimo": item.get("ultimo"),
        "bid": item.get("preciocompra"),
        "ask": item.get("precioventa"),
        "volumen": item.get("volnominal"),
        "operaciones": item.get("operaciones"),
        "fecha": item.get("fecha"),
        "hora": item.get("hora"),
        "datetime": item.get("datetime"),
        "expiry_code_raw": expiry_code_raw,
        "expiry_date": expiry_iso,
        "days_to_expiry": days_to_expiry,
        "option_price": _resolve_option_price(ult_f),
        "spread_abs": spread_abs,
        "volumen_float": vol_f,
        "operaciones_int": op_i,
        "has_volume": has_volume,
        "has_trades": has_trades,
        "underlying_price": uprice,
        "moneyness": mny,
        "money_status": mstat,
    }


def _sort_strikes(side: dict[float, dict[str, Any]]) -> dict[float, dict[str, Any]]:
    return {k: side[k] for k in sorted(side.keys())}


def build_rava_option_chain(options: list[Any], underlying_prices: dict | None = None) -> dict[str, Any]:
    """
    Construye cadena anidada desde items Rava (p. ej. salida de /options/rava/raw).

    chain[underlying][expiry]["calls"|"puts"][strike] = option_obj
    """
    chain: dict[str, dict[str, dict[str, dict[float, dict[str, Any]]]]] = {}
    expiry_resolved_cache: dict[str, date | None] = {}
    price_by_underlying: dict[str, Any] = {}
    if underlying_prices is not None:
        price_by_underlying = _normalize_underlying_prices(underlying_prices)

    def _expiry_for_code(code: str) -> date | None:
        if code not in expiry_resolved_cache:
            expiry_resolved_cache[code] = resolve_expiry_date(code)
        return expiry_resolved_cache[code]

    for raw in options:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("securitytype") or "").strip().upper() != "OPT":
            continue

        sym = _pick_symbol(raw)
        parsed = _parse_option_symbol(sym)
        if parsed is None:
            continue

        strike_raw = (parsed.get("strike_raw") or "").strip()
        if not strike_raw:
            continue
        try:
            strike = float(strike_raw)
        except ValueError:
            continue

        und = parsed["underlying_guess"]
        exp_code_raw = parsed["expiry_code_raw"]
        exp = exp_code_raw or "_"
        opt_type = parsed["option_type"]

        if und not in chain:
            chain[und] = {}
        if exp not in chain[und]:
            chain[und][exp] = {"calls": {}, "puts": {}}

        exp_date = _expiry_for_code(exp_code_raw)
        spot: float | None = None
        if price_by_underlying:
            spot = _safe_float(price_by_underlying.get(und.upper()))
        row = _option_row(
            raw,
            expiry_code_raw=exp_code_raw,
            expiry_date=exp_date,
            underlying_price=spot,
            strike=strike,
            option_type=opt_type,
        )
        if opt_type == "C":
            chain[und][exp]["calls"][strike] = row
        elif opt_type == "V":
            chain[und][exp]["puts"][strike] = row

    # Ordenar strikes por subyacente / vencimiento
    for und, expiries in chain.items():
        for exp, sides in expiries.items():
            sides["calls"] = _sort_strikes(sides["calls"])
            sides["puts"] = _sort_strikes(sides["puts"])

    underlyings_count = len(chain)
    expiries_count_total = sum(len(expiries) for expiries in chain.values())

    first_u = sorted(chain.keys())[0] if chain else None
    sample_chain: dict[str, Any] = {}
    if first_u is not None:
        sample_chain = {first_u: chain[first_u]}

    print(f"[RAVA_CHAIN] underlyings_count={underlyings_count}", flush=True)
    print(f"[RAVA_CHAIN] expiries_count_total={expiries_count_total}", flush=True)
    print(
        "[RAVA_CHAIN] sample_chain=" + json.dumps(sample_chain, ensure_ascii=False, default=str)[:8000],
        flush=True,
    )

    return chain
