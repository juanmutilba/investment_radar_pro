"""
Curva / sonrisa de IV: agrupa puntos ya con iv_pct; cálculo IV alineado al frontend (BS + misma tasa y mark).

La IV para el endpoint /options/iv-smile usa bid/ask/último de la cadena mergeada (sin batch /options/quotes),
misma prioridad de mark que optionMarkPriceForIv en el webapp.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Literal

from services.options.models import OptionChain, OptionContract
from services.options.normalizer import normalize_option_type

IV_RISK_FREE_RATE_ANNUAL = 0.45


def _erf_approx(x: float) -> float:
    sign = -1.0 if x < 0 else 1.0
    ax = abs(x)
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911
    t = 1.0 / (1.0 + p * ax)
    y = 1.0 - (((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * math.exp(-ax * ax))
    return sign * y


def _norm_cdf(x: float) -> float:
    if x < -10:
        return 0.0
    if x > 10:
        return 1.0
    return 0.5 * (1.0 + _erf_approx(x / math.sqrt(2.0)))


def _black_scholes_european(
    spot: float,
    strike: float,
    time_years: float,
    risk_free: float,
    sigma: float,
    call: bool,
) -> float:
    if not (spot > 0 and strike > 0 and sigma > 0):
        return float("nan")
    if time_years <= 0:
        return max(spot - strike, 0.0) if call else max(strike - spot, 0.0)
    sqrt_t = math.sqrt(time_years)
    d1 = (math.log(spot / strike) + (risk_free + 0.5 * sigma * sigma) * time_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    disc = math.exp(-risk_free * time_years)
    if call:
        return spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def mark_price_for_iv(
    bid: float | None,
    ask: float | None,
    last: float | None,
) -> float | None:
    b = bid if bid is not None and math.isfinite(bid) and bid > 0 else None
    a = ask if ask is not None and math.isfinite(ask) and ask > 0 else None
    l = last if last is not None and math.isfinite(last) and last > 0 else None
    if b is not None and a is not None:
        return (b + a) / 2.0
    if b is not None:
        return b
    if a is not None:
        return a
    return l


def implied_volatility_annual_percent(
    *,
    spot: float,
    strike: float,
    mark_price: float,
    time_years: float,
    call: bool,
    risk_free_annual: float = IV_RISK_FREE_RATE_ANNUAL,
) -> float | None:
    """IV anual en puntos porcentuales (p. ej. 38.2); None si no hay bracket válido."""
    r = risk_free_annual
    if not (spot > 0 and strike > 0 and mark_price > 0 and time_years > 0 and r >= 0):
        return None
    intrinsic = max(spot - strike, 0.0) if call else max(strike - spot, 0.0)
    if mark_price + 1e-10 < intrinsic:
        return None
    if call and mark_price > spot * 1.001:
        return None
    if not call and mark_price > strike * 1.001:
        return None

    def price(sig: float) -> float:
        return _black_scholes_european(spot, strike, time_years, r, sig, call)

    def f(sig: float) -> float:
        return price(sig) - mark_price

    lo = 1e-5
    hi = 4.0
    flo = f(lo)
    fhi = f(hi)
    if not (math.isfinite(flo) and math.isfinite(fhi)):
        return None
    guard = 0
    while fhi < 0 and hi < 80 and guard < 25:
        hi *= 1.6
        fhi = f(hi)
        guard += 1
    if flo > 0 or fhi < 0:
        return None
    tol = 1e-5
    max_it = 90
    for _ in range(max_it):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if not math.isfinite(fm):
            return None
        if abs(fm) < tol or hi - lo < 1e-7:
            sigma = mid
            if not (sigma > 0) or sigma > 79:
                return None
            return sigma * 100.0
        if fm > 0:
            hi = mid
        else:
            lo = mid
    return None


def days_between_today_and_expiry(yyyy_mm_dd: str) -> int | None:
    if not yyyy_mm_dd or len(yyyy_mm_dd) < 10:
        return None
    s = yyyy_mm_dd[:10]
    try:
        y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
        end = date(y, mo, d)
    except ValueError:
        return None
    today = date.today()
    diff = (end - today).days
    return diff if diff >= 0 else None


def _contract_type_upper(c: OptionContract) -> str:
    return (c.option_type or "").strip().upper()


def moneyness_label(
    strike: float | None,
    option_type_upper: str,
    spot: float | None,
) -> Literal["ITM", "ATM", "OTM", "SIN_DATO"]:
    """Mismo criterio que el panel (ATM si |K-S|/S ≤ 3 %)."""
    if spot is None or not math.isfinite(spot) or spot <= 0:
        return "SIN_DATO"
    if strike is None or not math.isfinite(strike):
        return "SIN_DATO"
    rel = abs(strike - spot) / spot
    if rel <= 0.03:
        return "ATM"
    t = option_type_upper
    is_call = "CALL" in t or t == "C"
    is_put = "PUT" in t or t in ("P", "V")
    if not is_call and not is_put:
        return "SIN_DATO"
    if is_call:
        return "ITM" if strike < spot else "OTM"
    return "ITM" if strike > spot else "OTM"


def _moneyness_from_raw_or_model(
    raw: dict[str, Any] | None,
    strike: float,
    opt_upper: str,
    spot: float | None,
) -> str:
    if isinstance(raw, dict):
        for k in ("money_status", "moneyness_status", "moneyness"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().upper()
    return moneyness_label(strike, opt_upper, spot)


def iv_pct_for_contract_smile(
    c: OptionContract,
    *,
    spot: float | None,
    days_to_expiry: int | None,
) -> float | None:
    """IV % anual con mark bid/ask/último de la fila de cadena (sin quotes batch)."""
    if spot is None or not math.isfinite(spot) or spot <= 0:
        return None
    if days_to_expiry is None or days_to_expiry <= 0:
        return None
    k = c.strike
    if k is None or not math.isfinite(k) or k <= 0:
        return None
    nt = normalize_option_type(c.option_type)
    if nt not in ("CALL", "PUT"):
        return None
    call = nt == "CALL"
    mark = mark_price_for_iv(c.bid, c.ask, c.last)
    if mark is None or mark <= 0:
        return None
    ty = days_to_expiry / 365.0
    return implied_volatility_annual_percent(
        spot=float(spot),
        strike=float(k),
        mark_price=float(mark),
        time_years=float(ty),
        call=call,
    )


def _finite_non_neg_volume(v: object) -> float:
    if v is None:
        return 0.0
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) and x >= 0 else 0.0


def _chain_bid_positive(c: OptionContract) -> float | None:
    b = c.bid
    if b is None:
        return None
    try:
        x = float(b)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def iv_smile_input_rows_from_chain(chain: OptionChain, spot: float | None) -> list[dict[str, Any]]:
    """Filas planas con iv_pct para ``build_iv_smile`` (incluye volumen y bid de cadena para oportunidades IV)."""
    u = (chain.underlying or "").strip().upper()
    out: list[dict[str, Any]] = []
    for c in chain.contracts:
        exp = (c.expiry or "").strip()
        if not exp:
            continue
        exp10 = exp[:10]
        k = c.strike
        if k is None or not math.isfinite(k):
            continue
        nt = normalize_option_type(c.option_type)
        if nt not in ("CALL", "PUT"):
            continue
        dte = days_between_today_and_expiry(exp10)
        iv = iv_pct_for_contract_smile(c, spot=spot, days_to_expiry=dte)
        if iv is None or not math.isfinite(iv):
            continue
        opt_u = _contract_type_upper(c)
        raw = c.raw if isinstance(c.raw, dict) else None
        mn = _moneyness_from_raw_or_model(raw, float(k), opt_u, spot)
        sym = (c.symbol or "").strip()
        vol = _finite_non_neg_volume(c.volume)
        bid_p = _chain_bid_positive(c)
        out.append(
            {
                "underlying": u or (c.underlying or "").strip().upper(),
                "expiration": exp10,
                "option_type": nt,
                "strike": float(k),
                "iv_pct": float(iv),
                "moneyness": mn,
                "symbol": sym,
                "volume": vol,
                "bid": bid_p,
            }
        )
    return out


def build_iv_smile(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Agrupa por underlying, expiration y option_type; ordena puntos por strike ascendente.

    Por grupo: ``avg_iv_pct``, ``min_iv_pct``, ``max_iv_pct`` y por punto diferencias vs promedio
    y flags ``rich_iv`` / ``cheap_iv`` (±10 % relativo al promedio del grupo).
    """
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        try:
            strike = float(row["strike"])
            iv_pct = float(row["iv_pct"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(strike) or not math.isfinite(iv_pct):
            continue
        und = str(row.get("underlying") or "").strip().upper()
        exp = str(row.get("expiration") or "").strip()[:10]
        ot = str(row.get("option_type") or "").strip().upper()
        if not und or not exp or ot not in ("CALL", "PUT"):
            continue
        key = (und, exp, ot)
        vol = row.get("volume")
        try:
            vol_f = float(vol) if vol is not None else 0.0
        except (TypeError, ValueError):
            vol_f = 0.0
        if not math.isfinite(vol_f) or vol_f < 0:
            vol_f = 0.0
        bid_v = row.get("bid")
        bid_f: float | None
        try:
            if bid_v is None:
                bid_f = None
            else:
                bf = float(bid_v)
                bid_f = bf if math.isfinite(bf) and bf > 0 else None
        except (TypeError, ValueError):
            bid_f = None
        groups.setdefault(key, []).append(
            {
                "strike": strike,
                "iv_pct": iv_pct,
                "moneyness": str(row.get("moneyness") or "SIN_DATO"),
                "symbol": str(row.get("symbol") or ""),
                "volume": vol_f,
                "bid": bid_f,
            }
        )
    items: list[dict[str, Any]] = []
    for (und, exp, ot) in sorted(groups.keys(), key=lambda x: (x[0], x[1], x[2])):
        raw_pts = sorted(groups[(und, exp, ot)], key=lambda p: p["strike"])
        ivs = [float(p["iv_pct"]) for p in raw_pts if math.isfinite(float(p["iv_pct"]))]
        n_iv = len(ivs)
        avg_iv = sum(ivs) / float(n_iv) if n_iv else 0.0
        min_iv = min(ivs) if ivs else None
        max_iv = max(ivs) if ivs else None
        avg_ok = avg_iv > 0 and math.isfinite(avg_iv)
        pts_out: list[dict[str, Any]] = []
        for p in raw_pts:
            iv = float(p["iv_pct"])
            if avg_ok:
                diff_abs = iv - avg_iv
                diff_pct = (iv / avg_iv - 1.0) * 100.0
                rich = bool(diff_pct >= 10.0)
                cheap = bool(diff_pct <= -10.0)
            else:
                diff_abs = None
                diff_pct = None
                rich = False
                cheap = False
            pts_out.append(
                {
                    "strike": p["strike"],
                    "iv_pct": iv,
                    "moneyness": p["moneyness"],
                    "symbol": p["symbol"],
                    "volume": float(p.get("volume") or 0.0),
                    "bid": p.get("bid"),
                    "iv_diff_vs_avg": None if diff_abs is None else round(diff_abs, 6),
                    "iv_diff_vs_avg_pct": None if diff_pct is None else round(diff_pct, 4),
                    "rich_iv": rich,
                    "cheap_iv": cheap,
                }
            )
        items.append(
            {
                "underlying": und,
                "expiration": exp,
                "option_type": ot,
                "avg_iv_pct": round(avg_iv, 6) if n_iv else None,
                "min_iv_pct": round(min_iv, 6) if min_iv is not None else None,
                "max_iv_pct": round(max_iv, 6) if max_iv is not None else None,
                "points": pts_out,
            }
        )
    return items
