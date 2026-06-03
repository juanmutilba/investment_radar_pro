"""
Backtest / análisis de tendencias BTC 30m (Binance spot público).
Solo lectura de mercado; no opera testnet ni paper.
"""
from __future__ import annotations

import itertools
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import Any, Callable, Literal

from services.crypto.signals import _ema_series, rsi, sma

_LOG_PREFIX = "[BTC_BACKTEST]"

Direction = Literal["up", "down"]
Regime = Literal["bull", "bear", "neutral"]

TF_MS_30M = 30 * 60 * 1000
DEFAULT_MIN_SAMPLES = 5

_TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": TF_MS_30M,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _ccxt_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper().replace(" ", "")
    if "/" in s:
        return s
    if s.endswith("USDT") and len(s) > 4:
        return f"{s[:-4]}/USDT"
    return s


def _safe_div(a: float, b: float) -> float:
    return a / b if abs(b) > 1e-12 else 0.0


def fetch_btc_ohlcv_paginated(
    *,
    symbol: str,
    timeframe: str,
    days: int,
    limit_per_request: int = 1000,
) -> list[list[float]]:
    """Velas OHLCV desde Binance spot público (sin sandbox)."""
    try:
        import ccxt  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError("ccxt no instalado") from e

    sym = _ccxt_symbol(symbol)
    tf = (timeframe or "30m").strip() or "30m"
    days_i = max(1, int(days))
    lim = max(1, min(int(limit_per_request), 1000))

    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - days_i * 24 * 60 * 60 * 1000

    _log(f"descarga {sym} tf={tf} days={days_i} since={since_ms}")

    all_rows: list[list[float]] = []
    cursor = since_ms
    pages = 0
    while cursor < now_ms:
        pages += 1
        batch = ex.fetch_ohlcv(sym, timeframe=tf, since=cursor, limit=lim)
        if not batch:
            break
        if all_rows and batch[0][0] <= all_rows[-1][0]:
            batch = [r for r in batch if r[0] > all_rows[-1][0]]
            if not batch:
                break
        all_rows.extend(batch)
        cursor = int(batch[-1][0]) + 1
        if len(batch) < lim:
            break
        if pages > 50:
            _log("paginación: tope de páginas alcanzado")
            break

    # recorte a ventana de días
    cutoff = now_ms - days_i * 24 * 60 * 60 * 1000
    trimmed = [r for r in all_rows if r[0] >= cutoff]
    trimmed.sort(key=lambda r: r[0])
    _log(f"descarga OK páginas={pages} velas={len(trimmed)}")
    return trimmed


def timeframe_to_ms(timeframe: str) -> int:
    tf = (timeframe or "30m").strip().lower()
    if tf in _TIMEFRAME_MS:
        return _TIMEFRAME_MS[tf]
    if tf.endswith("m"):
        return int(tf[:-1]) * 60_000
    if tf.endswith("h"):
        return int(tf[:-1]) * 60 * 60_000
    return TF_MS_30M


def fetch_ohlcv_for_window(
    *,
    symbol: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
    limit_per_request: int = 1000,
) -> list[list[float]]:
    """Velas OHLCV públicas entre start_ms y end_ms (inclusive aprox.)."""
    try:
        import ccxt  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError("ccxt no instalado") from e

    sym = _ccxt_symbol(symbol)
    tf = (timeframe or "30m").strip() or "30m"
    lim = max(1, min(int(limit_per_request), 1000))
    pad = timeframe_to_ms(tf) * 3
    since = max(0, int(start_ms) - pad)
    until = int(end_ms) + pad

    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    all_rows: list[list[float]] = []
    cursor = since
    pages = 0
    while cursor < until:
        pages += 1
        batch = ex.fetch_ohlcv(sym, timeframe=tf, since=cursor, limit=lim)
        if not batch:
            break
        if all_rows and batch[0][0] <= all_rows[-1][0]:
            batch = [r for r in batch if r[0] > all_rows[-1][0]]
            if not batch:
                break
        all_rows.extend(batch)
        cursor = int(batch[-1][0]) + 1
        if len(batch) < lim:
            break
        if pages > 80:
            break
    out = [r for r in all_rows if since <= int(r[0]) <= until]
    out.sort(key=lambda r: r[0])
    return out


def compute_long_excursion_from_candles(
    candles: list[list[float]],
    entry_ms: int,
    exit_ms: int,
    entry_price: float,
) -> dict[str, Any]:
    """
    MFE/MAE y flags de niveles entre entry y exit usando high/low de velas en el rango.
    """
    if entry_price <= 0 or not candles:
        return {
            "max_favorable_pct": None,
            "max_adverse_pct": None,
            "bars_to_max": None,
            "bars_to_exit": None,
            "reached_0_8_pct": False,
            "reached_1_0_pct": False,
            "reached_1_5_pct": False,
            "reached_2_5_pct": False,
            "candles_in_path": 0,
        }
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    ts = [int(c[0]) for c in candles]
    i0 = next((i for i, t in enumerate(ts) if t >= entry_ms), 0)
    i1 = max(i0, next((i for i in range(len(ts) - 1, -1, -1) if ts[i] <= exit_ms), len(ts) - 1))
    mfe = 0.0
    mae = 0.0
    bar_max = 0
    for j in range(i0, i1 + 1):
        fav = _safe_div(highs[j] - entry_price, entry_price) * 100.0
        adv = _safe_div(entry_price - lows[j], entry_price) * 100.0
        if fav > mfe:
            mfe = fav
            bar_max = j - i0
    for j in range(i0, i1 + 1):
        adv = _safe_div(entry_price - lows[j], entry_price) * 100.0
        if adv > mae:
            mae = adv
    return {
        "max_favorable_pct": round(mfe, 4),
        "max_adverse_pct": round(mae, 4),
        "bars_to_max": bar_max,
        "bars_to_exit": i1 - i0,
        "reached_0_8_pct": mfe >= 0.8 - 1e-9,
        "reached_1_0_pct": mfe >= 1.0 - 1e-9,
        "reached_1_5_pct": mfe >= 1.5 - 1e-9,
        "reached_2_5_pct": mfe >= 2.5 - 1e-9,
        "candles_in_path": i1 - i0 + 1,
    }


def _macd_hist_series(closes: list[float]) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < 26:
        return out
    ef = _ema_series(closes, 12)
    es = _ema_series(closes, 26)
    line: list[float | None] = [None] * n
    for i in range(n):
        a, b = ef[i], es[i]
        if a is not None and b is not None:
            line[i] = a - b
    # señal EMA9 sobre línea MACD
    sig: list[float | None] = [None] * n
    k = 2.0 / (9 + 1.0)
    seed_idx = next((i for i in range(n) if line[i] is not None), None)
    if seed_idx is None:
        return out
    vals: list[float] = []
    idx_map: list[int] = []
    for i in range(seed_idx, n):
        if line[i] is None:
            continue
        vals.append(float(line[i]))
        idx_map.append(i)
    if len(vals) < 9:
        return out
    sig_v = sum(vals[:9]) / 9.0
    sig[idx_map[8]] = sig_v
    for j in range(9, len(vals)):
        sig_v = vals[j] * k + sig_v * (1.0 - k)
        sig[idx_map[j]] = sig_v
    for i in range(n):
        if line[i] is not None and sig[i] is not None:
            out[i] = line[i] - sig[i]
    return out


def _atr_series(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    trs: list[float] = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return out
    atr_v = sum(trs[:period]) / float(period)
    out[period] = atr_v
    for i in range(period + 1, n):
        tr = trs[i - 1]
        atr_v = (atr_v * (period - 1) + tr) / float(period)
        out[i] = atr_v
    return out


def _adx_series(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period * 2:
        return out
    plus_dm: list[float] = [0.0]
    minus_dm: list[float] = [0.0]
    tr_list: list[float] = [0.0]
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)
    def _wilder_smooth(vals: list[float], p: int) -> list[float | None]:
        res: list[float | None] = [None] * len(vals)
        if len(vals) <= p:
            return res
        s = sum(vals[1 : p + 1])
        res[p] = s
        for i in range(p + 1, len(vals)):
            s = s - (s / p) + vals[i]
            res[i] = s
        return res

    tr_s = _wilder_smooth(tr_list, period)
    p_dm = _wilder_smooth(plus_dm, period)
    m_dm = _wilder_smooth(minus_dm, period)
    dx_vals: list[float | None] = [None] * n
    for i in range(n):
        if tr_s[i] is None or p_dm[i] is None or m_dm[i] is None or tr_s[i] <= 0:
            continue
        pdi = 100.0 * p_dm[i] / tr_s[i]
        mdi = 100.0 * m_dm[i] / tr_s[i]
        denom = pdi + mdi
        if denom <= 0:
            continue
        dx_vals[i] = 100.0 * abs(pdi - mdi) / denom
    adx_seed: list[float] = []
    adx_idx: list[int] = []
    for i in range(n):
        if dx_vals[i] is not None:
            adx_seed.append(dx_vals[i])
            adx_idx.append(i)
    if len(adx_seed) < period:
        return out
    adx_v = sum(adx_seed[:period]) / float(period)
    out[adx_idx[period - 1]] = adx_v
    for j in range(period, len(adx_seed)):
        adx_v = (adx_v * (period - 1) + adx_seed[j]) / float(period)
        out[adx_idx[j]] = adx_v
    return out


def _bollinger_bandwidth_series(closes: list[float], period: int = 20, mult: float = 2.0) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        mid = sum(window) / float(period)
        if mid <= 0:
            continue
        var = sum((x - mid) ** 2 for x in window) / float(period)
        std = math.sqrt(var)
        upper = mid + mult * std
        lower = mid - mult * std
        out[i] = (upper - lower) / mid
    return out


@dataclass
class BarIndicators:
    rsi14: float | None = None
    macd_hist: float | None = None
    macd_hist_prev: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    ema20_slope: float | None = None
    ema20_gt_ema50: bool = False
    adx14: float | None = None
    volume_ratio: float | None = None
    atr14_pct: float | None = None
    bb_bandwidth: float | None = None
    breakout20: bool = False
    pullback_valid: bool = False
    funding_rate: float | None = None  # hook futuro


@dataclass
class TrendRecord:
    direction: Direction
    start_idx: int
    end_idx: int
    start_time_ms: int
    end_time_ms: int
    start_price: float
    max_high: float
    min_low: float
    return_pct: float
    max_favorable_pct: float
    max_adverse_pct: float
    duration_bars: int
    successful: bool = False
    indicators_at_start: BarIndicators = field(default_factory=BarIndicators)


def _build_indicator_matrix(
    candles: list[list[float]],
) -> tuple[list[Regime], list[BarIndicators]]:
    n = len(candles)
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in candles]
    volumes = [float(c[5]) if len(c) > 5 and c[5] is not None else 0.0 for c in candles]

    ema20 = _ema_series(closes, 20)
    ema50 = _ema_series(closes, 50)
    macd_hist = _macd_hist_series(closes)
    atr = _atr_series(highs, lows, closes, 14)
    adx = _adx_series(highs, lows, closes, 14)
    bb_bw = _bollinger_bandwidth_series(closes, 20)

    vol_sma20: list[float | None] = [None] * n
    for i in range(19, n):
        vol_sma20[i] = sum(volumes[i - 19 : i + 1]) / 20.0

    regimes: list[Regime] = ["neutral"] * n
    indicators: list[BarIndicators] = [BarIndicators() for _ in range(n)]

    for i in range(n):
        c, h, l = closes[i], highs[i], lows[i]
        e20, e50 = ema20[i], ema50[i]
        if e20 is not None and e50 is not None:
            if e20 > e50 and c > e20:
                regimes[i] = "bull"
            elif e20 < e50 and c < e20:
                regimes[i] = "bear"
            else:
                regimes[i] = "neutral"

        bi = BarIndicators()
        bi.ema20 = e20
        bi.ema50 = e50
        bi.ema20_gt_ema50 = bool(e20 is not None and e50 is not None and e20 > e50)
        if i > 0 and e20 is not None and ema20[i - 1] is not None:
            bi.ema20_slope = e20 - ema20[i - 1]
        bi.rsi14 = rsi(closes[: i + 1], 14)
        bi.macd_hist = macd_hist[i]
        bi.macd_hist_prev = macd_hist[i - 1] if i > 0 else None
        bi.adx14 = adx[i]
        if vol_sma20[i] is not None and vol_sma20[i] > 0:
            bi.volume_ratio = volumes[i] / vol_sma20[i]
        if atr[i] is not None and c > 0:
            bi.atr14_pct = (atr[i] / c) * 100.0
        bi.bb_bandwidth = bb_bw[i]
        if i >= 20:
            prev_high = max(highs[i - 20 : i])
            bi.breakout20 = c > prev_high
        if i >= 5 and e20 is not None:
            touched = any(
                lows[j] <= (ema20[j] or e20) for j in range(max(0, i - 15), i) if ema20[j] is not None
            )
            bi.pullback_valid = touched and c > e20
        indicators[i] = bi

    return regimes, indicators


def _extract_trends(
    candles: list[list[float]],
    regimes: list[Regime],
    *,
    target_pct: float,
) -> list[TrendRecord]:
    n = len(regimes)
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in candles]
    ts = [int(c[0]) for c in candles]
    trends: list[TrendRecord] = []
    i = 0
    while i < n:
        r = regimes[i]
        if r not in ("bull", "bear"):
            i += 1
            continue
        direction: Direction = "up" if r == "bull" else "down"
        start = i
        last_dir = i
        neutral_run = 0
        j = i + 1
        while j < n:
            if regimes[j] == ("bull" if direction == "up" else "bear"):
                last_dir = j
                neutral_run = 0
                j += 1
            elif regimes[j] == "neutral":
                neutral_run += 1
                if neutral_run > 2:
                    break
                j += 1
            else:
                break
        end = last_dir
        start_price = closes[start]
        seg_high = max(highs[start : end + 1])
        seg_low = min(lows[start : end + 1])
        max_fav = _safe_div(seg_high - start_price, start_price) * 100.0
        max_adv = _safe_div(start_price - seg_low, start_price) * 100.0
        ret_close = _safe_div(closes[end] - start_price, start_price) * 100.0
        tr = TrendRecord(
            direction=direction,
            start_idx=start,
            end_idx=end,
            start_time_ms=ts[start],
            end_time_ms=ts[end],
            start_price=start_price,
            max_high=seg_high,
            min_low=seg_low,
            return_pct=ret_close,
            max_favorable_pct=max_fav,
            max_adverse_pct=max_adv,
            duration_bars=end - start + 1,
        )
        if direction == "up":
            tr.successful = seg_high >= start_price * (1.0 + target_pct / 100.0)
        trends.append(tr)
        i = j
    return trends


def _intervals_overlap(idx: int, trends: list[TrendRecord]) -> TrendRecord | None:
    for t in trends:
        if t.start_idx <= idx <= t.end_idx:
            return t
    return None


def _trend_to_dict(t: TrendRecord) -> dict[str, Any]:
    return {
        "direction": t.direction,
        "start_time": datetime.fromtimestamp(t.start_time_ms / 1000.0, tz=timezone.utc).isoformat(),
        "end_time": datetime.fromtimestamp(t.end_time_ms / 1000.0, tz=timezone.utc).isoformat(),
        "start_price": round(t.start_price, 8),
        "max_high": round(t.max_high, 8),
        "min_low": round(t.min_low, 8),
        "return_pct": round(t.return_pct, 4),
        "max_favorable_pct": round(t.max_favorable_pct, 4),
        "max_adverse_pct": round(t.max_adverse_pct, 4),
        "duration_bars": t.duration_bars,
        "successful": t.successful,
    }


def _metric_row(
    name: str,
    *,
    total_signals: int,
    in_successful: int,
    recall_hits: int,
    recall_denom: int,
    returns_pct: list[float],
    favorable: list[float],
    adverse: list[float],
) -> dict[str, Any]:
    precision = (in_successful / total_signals * 100.0) if total_signals > 0 else None
    recall = (recall_hits / recall_denom * 100.0) if recall_denom > 0 else None
    avg_ret = sum(returns_pct) / len(returns_pct) if returns_pct else None
    med_ret = median(returns_pct) if returns_pct else None
    sum_fav = sum(favorable) if favorable else 0.0
    sum_adv = sum(adverse) if adverse else 0.0
    pf = (sum_fav / sum_adv) if sum_adv > 1e-9 else None
    return {
        "name": name,
        "total_signals": total_signals,
        "signals_in_successful_trends": in_successful,
        "precision_pct": round(precision, 2) if precision is not None else None,
        "recall_on_successful_pct": round(recall, 2) if recall is not None else None,
        "recall_hits": recall_hits,
        "recall_denom": recall_denom,
        "avg_return_pct": round(avg_ret, 4) if avg_ret is not None else None,
        "median_return_pct": round(med_ret, 4) if med_ret is not None else None,
        "profit_factor_approx": round(pf, 4) if pf is not None else None,
    }


def _evaluate_mask(
    name: str,
    mask: list[bool],
    candles_len: int,
    successful_up: list[TrendRecord],
    all_up: list[TrendRecord],
    trends_by_start: dict[int, TrendRecord],
) -> dict[str, Any]:
    total = sum(1 for b in mask if b)
    in_succ = 0
    returns_at_start: list[float] = []
    fav: list[float] = []
    adv: list[float] = []
    for i, hit in enumerate(mask):
        if not hit:
            continue
        tr = _intervals_overlap(i, successful_up)
        if tr is not None:
            in_succ += 1
        tr_start = trends_by_start.get(i)
        if tr_start is not None and tr_start.direction == "up":
            returns_at_start.append(tr_start.max_favorable_pct)
            fav.append(tr_start.max_favorable_pct)
            adv.append(max(tr_start.max_adverse_pct, 1e-6))
    recall_hits = 0
    for t in successful_up:
        if t.start_idx < len(mask) and mask[t.start_idx]:
            recall_hits += 1
    return _metric_row(
        name,
        total_signals=total,
        in_successful=in_succ,
        recall_hits=recall_hits,
        recall_denom=len(successful_up),
        returns_pct=returns_at_start,
        favorable=fav,
        adverse=adv,
    )


def _atomic_masks(indicators: list[BarIndicators], n: int) -> dict[str, list[bool]]:
    m: dict[str, list[bool]] = {}

    def _rsi_gt(th: float) -> list[bool]:
        return [bool(ind.rsi14 is not None and ind.rsi14 > th) for ind in indicators]

    m["rsi_gt_50"] = _rsi_gt(50)
    m["rsi_gt_55"] = _rsi_gt(55)
    m["rsi_lt_70"] = [bool(ind.rsi14 is not None and ind.rsi14 < 70) for ind in indicators]
    m["macd_hist_gt_0"] = [bool(ind.macd_hist is not None and ind.macd_hist > 0) for ind in indicators]
    m["macd_hist_cross_up"] = [
        bool(
            ind.macd_hist is not None
            and ind.macd_hist_prev is not None
            and ind.macd_hist_prev <= 0
            and ind.macd_hist > 0
        )
        for ind in indicators
    ]
    m["adx_gt_18"] = [bool(ind.adx14 is not None and ind.adx14 > 18) for ind in indicators]
    m["adx_gt_20"] = [bool(ind.adx14 is not None and ind.adx14 > 20) for ind in indicators]
    m["adx_gt_25"] = [bool(ind.adx14 is not None and ind.adx14 > 25) for ind in indicators]
    m["vol_ratio_gt_1.1"] = [bool(ind.volume_ratio is not None and ind.volume_ratio > 1.1) for ind in indicators]
    m["vol_ratio_gt_1.3"] = [bool(ind.volume_ratio is not None and ind.volume_ratio > 1.3) for ind in indicators]
    m["vol_ratio_gt_1.5"] = [bool(ind.volume_ratio is not None and ind.volume_ratio > 1.5) for ind in indicators]
    m["breakout20"] = [ind.breakout20 for ind in indicators]
    m["ema20_slope_pos"] = [bool(ind.ema20_slope is not None and ind.ema20_slope > 0) for ind in indicators]
    m["ema20_gt_ema50"] = [ind.ema20_gt_ema50 for ind in indicators]
    m["atr_pct_gt_0.25"] = [bool(ind.atr14_pct is not None and ind.atr14_pct > 0.25) for ind in indicators]
    m["atr_pct_lt_3.0"] = [bool(ind.atr14_pct is not None and ind.atr14_pct < 3.0) for ind in indicators]
    m["pullback_valid"] = [ind.pullback_valid for ind in indicators]
    m["bb_bw_gt_median"] = _bb_bw_above_median(indicators)
    return m


def _bb_bw_above_median(indicators: list[BarIndicators]) -> list[bool]:
    vals = [ind.bb_bandwidth for ind in indicators if ind.bb_bandwidth is not None]
    if not vals:
        return [False] * len(indicators)
    med = median(vals)
    return [bool(ind.bb_bandwidth is not None and ind.bb_bandwidth >= med) for ind in indicators]


def _combine_masks(masks: dict[str, list[bool]], keys: tuple[str, ...]) -> list[bool]:
    if not keys:
        return [False] * len(next(iter(masks.values())))
    acc = list(masks[keys[0]])
    for k in keys[1:]:
        other = masks[k]
        acc = [a and b for a, b in zip(acc, other)]
    return acc


def _score_indicators_at_trend_start(
    bull_trends: list[TrendRecord],
    successful_up: list[TrendRecord],
) -> list[dict[str, Any]]:
    checks: list[tuple[str, Callable[[BarIndicators], bool]]] = [
        ("rsi14_gt_50", lambda b: b.rsi14 is not None and b.rsi14 > 50),
        ("rsi14_gt_55", lambda b: b.rsi14 is not None and b.rsi14 > 55),
        ("rsi14_lt_70", lambda b: b.rsi14 is not None and b.rsi14 < 70),
        ("macd_hist_gt_0", lambda b: b.macd_hist is not None and b.macd_hist > 0),
        ("macd_hist_cross_up", lambda b: b.macd_hist is not None and b.macd_hist_prev is not None and b.macd_hist_prev <= 0 and b.macd_hist > 0),
        ("ema20_slope_pos", lambda b: b.ema20_slope is not None and b.ema20_slope > 0),
        ("ema20_gt_ema50", lambda b: b.ema20_gt_ema50),
        ("adx14_gt_20", lambda b: b.adx14 is not None and b.adx14 > 20),
        ("adx14_gt_25", lambda b: b.adx14 is not None and b.adx14 > 25),
        ("volume_ratio_gt_1.3", lambda b: b.volume_ratio is not None and b.volume_ratio > 1.3),
        ("breakout20", lambda b: b.breakout20),
        ("pullback_valid", lambda b: b.pullback_valid),
        ("atr14_pct_0.25_3", lambda b: b.atr14_pct is not None and 0.25 < b.atr14_pct < 3.0),
    ]
    succ_set = {id(t) for t in successful_up}
    rows: list[dict[str, Any]] = []
    for label, fn in checks:
        total = 0
        hits_succ = 0
        returns: list[float] = []
        for t in bull_trends:
            bi = t.indicators_at_start
            if not fn(bi):
                continue
            total += 1
            if id(t) in succ_set:
                hits_succ += 1
            returns.append(t.max_favorable_pct)
        prec = (hits_succ / total * 100.0) if total > 0 else None
        recall = (hits_succ / len(successful_up) * 100.0) if successful_up else None
        rows.append(
            {
                "indicator": label,
                "true_at_bull_start": total,
                "within_successful": hits_succ,
                "precision_pct": round(prec, 2) if prec is not None else None,
                "recall_on_successful_pct": round(recall, 2) if recall is not None else None,
                "avg_max_favorable_pct": round(sum(returns) / len(returns), 4) if returns else None,
            }
        )
    rows.sort(
        key=lambda r: (
            -(r.get("precision_pct") or 0),
            -(r.get("true_at_bull_start") or 0),
        )
    )
    return rows


def _rank_combo_rows(rows: list[dict[str, Any]], min_samples: int) -> list[dict[str, Any]]:
    eligible = [r for r in rows if (r.get("total_signals") or 0) >= min_samples]
    eligible.sort(
        key=lambda r: (
            -(r.get("precision_pct") or 0),
            -(r.get("total_signals") or 0),
            -(r.get("recall_on_successful_pct") or 0),
        )
    )
    return eligible


def _bot_recommendations(
    individual: list[dict[str, Any]],
    combos: list[dict[str, Any]],
    *,
    target_pct: float,
) -> list[str]:
    recs: list[str] = []
    top_ind = next((r for r in individual if (r.get("true_at_bull_start") or 0) >= 3), None)
    top_combo = combos[0] if combos else None
    if top_ind:
        recs.append(
            f"En inicios de tendencia alcista, «{top_ind['indicator']}» tuvo mejor precisión "
            f"({top_ind.get('precision_pct')}%) con {top_ind.get('true_at_bull_start')} casos."
        )
    if top_combo:
        recs.append(
            f"Combinación destacada: «{top_combo['name']}» — precisión {top_combo.get('precision_pct')}%, "
            f"recall {top_combo.get('recall_on_successful_pct')}%, señales {top_combo.get('total_signals')}."
        )
    recs.append(
        f"Mantener take_profit testnet cerca de +{target_pct}% alineado con movimientos que el histórico 30m suele alcanzar."
    )
    recs.append(
        "Considerar subir min_entry_score si las señales top incluyen RSI>55 y ADX>20 (ver bot_runner / daily_intraday)."
    )
    recs.append(
        "Re-ejecutar este backtest cada 2–4 semanas; no aplicar cambios al bot hasta validar en testnet."
    )
    return recs


def run_btc_30m_trend_backtest(
    *,
    days: int = 30,
    target_pct: float = 2.5,
    symbol: str = "BTCUSDT",
    timeframe: str = "30m",
    min_samples: int = DEFAULT_MIN_SAMPLES,
    max_workers: int = 8,
) -> dict[str, Any]:
    """
    Descarga velas, detecta tendencias EMA20/50 y evalúa indicadores + combinaciones.
  """
    days_i = max(1, int(days))
    target = float(target_pct)
    min_s = max(1, int(min_samples))

    candles = fetch_btc_ohlcv_paginated(symbol=symbol, timeframe=timeframe, days=days_i)
    if len(candles) < 100:
        raise RuntimeError(f"pocas velas ({len(candles)}); ampliar days o revisar red")

    regimes, indicators = _build_indicator_matrix(candles)
    trends = _extract_trends(candles, regimes, target_pct=target)

    bull = [t for t in trends if t.direction == "up"]
    bear = [t for t in trends if t.direction == "down"]
    successful_up = [t for t in bull if t.successful]

    for t in bull:
        t.indicators_at_start = indicators[t.start_idx]

    start_ms = int(candles[0][0])
    end_ms = int(candles[-1][0])
    range_from = datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc).isoformat()
    range_to = datetime.fromtimestamp(end_ms / 1000.0, tz=timezone.utc).isoformat()

    _log(
        f"velas={len(candles)} alcistas={len(bull)} alcistas>={target}%={len(successful_up)} "
        f"bajistas={len(bear)}"
    )

    individual_rows = _score_indicators_at_trend_start(bull, successful_up)

    n = len(candles)
    masks = _atomic_masks(indicators, n)
    successful_up_intervals = successful_up
    trends_by_start = {t.start_idx: t for t in bull}

    atomic_keys = sorted(masks.keys())
    combo_jobs: list[tuple[str, tuple[str, ...]]] = []
    for k in atomic_keys:
        combo_jobs.append((k, (k,)))
    for a, b in itertools.combinations(atomic_keys, 2):
        combo_jobs.append((f"{a}+{b}", (a, b)))
    for a, b, c in itertools.combinations(atomic_keys, 3):
        combo_jobs.append((f"{a}+{b}+{c}", (a, b, c)))

    def _run_job(job: tuple[str, tuple[str, ...]]) -> dict[str, Any]:
        label, keys = job
        mask = _combine_masks(masks, keys)
        return _evaluate_mask(
            label,
            mask,
            n,
            successful_up_intervals,
            bull,
            trends_by_start,
        )

    combo_rows: list[dict[str, Any]] = []
    workers = max(1, min(int(max_workers), 16))
    _log(f"evaluando {len(combo_jobs)} combinaciones (workers={workers})")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_run_job, job): job[0] for job in combo_jobs}
        for fut in as_completed(futs):
            try:
                combo_rows.append(fut.result())
            except Exception as e:
                _log(f"combo falló {futs[fut]}: {type(e).__name__}: {e}")

    ranked_individual = [r for r in combo_rows if "+" not in r["name"]]
    ranked_individual = _rank_combo_rows(ranked_individual, min_s)
    ranked_combos = [r for r in combo_rows if "+" in r["name"]]
    ranked_combos = _rank_combo_rows(ranked_combos, min_s)

    recommendations = _bot_recommendations(individual_rows, ranked_combos, target_pct=target)

    return {
        "ok": True,
        "symbol": _ccxt_symbol(symbol),
        "timeframe": timeframe,
        "days": days_i,
        "target_pct": target,
        "min_samples": min_s,
        "range_from": range_from,
        "range_to": range_to,
        "candles_count": len(candles),
        "bullish_trends_count": len(bull),
        "bullish_success_count": len(successful_up),
        "bullish_success_rate_pct": round(len(successful_up) / len(bull) * 100.0, 2) if bull else None,
        "bearish_trends_count": len(bear),
        "bullish_trends": [_trend_to_dict(t) for t in bull],
        "bearish_trends": [_trend_to_dict(t) for t in bear],
        "successful_bullish_trends": [_trend_to_dict(t) for t in successful_up],
        "indicators_at_bull_start": individual_rows,
        "filter_metrics_individual": ranked_individual[:25],
        "filter_metrics_combinations": ranked_combos[:25],
        "recommendations_for_bot_runner": recommendations,
        "funding_hook_note": "funding_rate reservado (None); integrar fuente externa en futuro.",
    }
