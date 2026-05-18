"""
Indicadores técnicos sobre cierres (solo stdlib / matemática pura).
Velas ccxt: [timestamp, open, high, low, close, volume].
"""
from __future__ import annotations

import math
from typing import Any, Literal

from services.crypto.strategy_modes import (
    DAILY_SETUP_TYPES,
    STRATEGY_MODE_DAILY_INTRADAY,
    STRATEGY_MODE_TREND_SWING,
    normalize_strategy_mode,
)

_LOG_PREFIX = "[CRYPTO]"

Trend = Literal["alcista", "bajista", "lateral"]
Momentum = Literal["positivo", "negativo", "neutro"]
Risk = Literal["alto", "medio", "bajo"]
Signal = Literal["compra_potencial", "neutral", "cuidado"]

# SMA50 + cola para MACD (señal sobre línea MACD)
MIN_OHLCV_ROWS = 55


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def sma(values: list[float], period: int) -> float | None:
    """Media móvil simple del último tramo (últimos `period` valores)."""
    if period < 1 or len(values) < period:
        return None
    return sum(values[-period:]) / float(period)


def ema(values: list[float], period: int) -> float | None:
    """EMA del último punto; semilla = SMA de los primeros `period` cierres."""
    if period < 1 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema_v = sum(values[:period]) / float(period)
    for i in range(period, len(values)):
        ema_v = values[i] * k + ema_v * (1.0 - k)
    return ema_v


def rsi(values: list[float], period: int = 14) -> float | None:
    """RSI tipo Wilder (RMA de ganancias/pérdidas)."""
    if period < 1 or len(values) < period + 1:
        return None
    changes: list[float] = []
    for i in range(1, len(values)):
        changes.append(values[i] - values[i - 1])
    if len(changes) < period:
        return None
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]
    avg_g = sum(gains[:period]) / float(period)
    avg_l = sum(losses[:period]) / float(period)
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / float(period)
        avg_l = (avg_l * (period - 1) + losses[i]) / float(period)
    if avg_l <= 0:
        return 100.0 if avg_g > 0 else 50.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def _ema_series(closes: list[float], period: int) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if period < 1 or n < period:
        return out
    k = 2.0 / (period + 1.0)
    ema_v = sum(closes[:period]) / float(period)
    out[period - 1] = ema_v
    for i in range(period, n):
        ema_v = closes[i] * k + ema_v * (1.0 - k)
        out[i] = ema_v
    return out


def macd(
    values: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float | None, float | None, float | None]:
    """
    MACD clásico: línea = EMA(fast) − EMA(slow); señal = EMA(signal) de la línea; histograma = línea − señal.
    Devuelve (macd, signal, hist) del último punto disponible.
    """
    if fast < 1 or slow < 1 or signal < 1 or len(values) < slow:
        return None, None, None
    ef = _ema_series(values, fast)
    es = _ema_series(values, slow)
    line: list[float] = []
    for i in range(len(values)):
        a, b = ef[i], es[i]
        if a is not None and b is not None:
            line.append(a - b)
        else:
            line.append(float("nan"))
    # quitar NaN iniciales para EMA de señal
    clean = [x for x in line if not math.isnan(x)]
    if len(clean) < signal:
        return None, None, None
    sig = ema(clean, signal)
    if sig is None or not clean:
        return None, None, None
    m_last = clean[-1]
    h_last = m_last - sig
    return m_last, sig, h_last


def _risk_label(rsi_v: float) -> Risk:
    if rsi_v > 75 or rsi_v < 30:
        return "alto"
    if 40 <= rsi_v <= 70:
        return "bajo"
    return "medio"


def _trend_label(close: float, s20: float | None, s50: float | None) -> Trend:
    if s20 is None or s50 is None:
        return "lateral"
    if close > s20 > s50:
        return "alcista"
    if close < s20 < s50:
        return "bajista"
    return "lateral"


def _momentum_label(macd_hist: float | None, rsi_v: float | None) -> Momentum:
    if macd_hist is None or rsi_v is None:
        return "neutro"
    pos = macd_hist > 0 and 45.0 <= rsi_v <= 70.0
    neg = macd_hist < 0 or rsi_v < 40.0
    if pos:
        return "positivo"
    if neg:
        return "negativo"
    return "neutro"


def _signal_label(score: int, risk: Risk) -> Signal:
    if risk == "alto":
        return "cuidado"
    if score <= 35:
        return "cuidado"
    if score >= 70:
        return "compra_potencial"
    return "neutral"


def _parse_candles(candles: list[list[Any]]) -> tuple[list[float], list[float]]:
    if not isinstance(candles, list) or len(candles) < MIN_OHLCV_ROWS:
        raise ValueError(
            f"Se requieren al menos {MIN_OHLCV_ROWS} velas para SMA50/MACD/RSI; recibidas {len(candles) if isinstance(candles, list) else 0}."
        )
    closes: list[float] = []
    volumes: list[float] = []
    for i, row in enumerate(candles):
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            raise ValueError(f"Vela inválida en índice {i}: se espera [ts, o, h, l, c, v].")
        c = row[4]
        if not isinstance(c, (int, float)) or isinstance(c, bool) or not math.isfinite(float(c)):
            raise ValueError(f"Cierre inválido en índice {i}.")
        closes.append(float(c))
        if len(row) >= 6 and isinstance(row[5], (int, float)) and not isinstance(row[5], bool):
            v = float(row[5])
            volumes.append(v if math.isfinite(v) and v >= 0 else 0.0)
        else:
            volumes.append(0.0)
    return closes, volumes


def _ema_periods_for_timeframe(timeframe: str, *, daily_mode: bool) -> tuple[int, int]:
    tf = (timeframe or "1h").strip().lower()
    if not daily_mode:
        return 20, 50
    if tf in ("5m", "10m", "15m"):
        return 9, 21
    if tf == "30m":
        return 10, 24
    return 12, 26


def _short_trend_label(close: float, ema_fast: float | None, ema_slow: float | None) -> Trend:
    if ema_fast is None or ema_slow is None:
        return "lateral"
    if close > ema_fast > ema_slow:
        return "alcista"
    if close < ema_fast < ema_slow:
        return "bajista"
    return "lateral"


def _macd_hist_prev(closes: list[float]) -> float | None:
    if len(closes) < MIN_OHLCV_ROWS + 1:
        return None
    _, _, mh = macd(closes[:-1], 12, 26, 9)
    return mh


def _volume_context_label(volumes: list[float]) -> str:
    if len(volumes) < 11:
        return "unknown"
    tail = volumes[-11:]
    avg = sum(tail[:-1]) / 10.0
    last = tail[-1]
    if avg <= 0:
        return "unknown" if last <= 0 else "rising"
    ratio = last / avg
    if ratio >= 1.2:
        return "rising"
    if ratio <= 0.85:
        return "weak"
    return "stable"


def _rsi_context_label(rsi_v: float, closes: list[float]) -> str:
    if len(closes) >= 4:
        drift = closes[-1] - closes[-4]
    else:
        drift = 0.0
    if rsi_v < 32:
        return "oversold_recovering" if drift > 0 else "oversold"
    if rsi_v < 45:
        return "low_recovering" if drift > 0 else "low_support"
    if rsi_v > 68:
        return "overbought"
    return "neutral"


def _macd_context_label(mh: float, mh_prev: float | None) -> str:
    if mh_prev is None:
        return "positive" if mh > 0 else "negative"
    if mh > 0 and mh > mh_prev:
        return "improving_positive"
    if mh > mh_prev:
        return "recovering"
    if mh < mh_prev:
        return "weakening"
    return "flat"


def _pick_daily_setup_type(
    *,
    short_trend: Trend,
    rsi_v: float,
    mh: float,
    mh_prev: float | None,
    vol_ctx: str,
    close: float,
    ema_fast: float | None,
) -> str | None:
    macd_up = mh_prev is not None and mh > mh_prev
    vol_ok = vol_ctx in ("rising", "stable")

    if short_trend == "alcista" and 38 <= rsi_v <= 58 and macd_up and ema_fast is not None and close >= ema_fast * 0.985:
        return "pullback"
    if short_trend in ("bajista", "lateral") and rsi_v < 42 and macd_up:
        return "rebound"
    if short_trend == "alcista" and mh > 0 and vol_ctx == "rising":
        return "momentum_intraday"
    if rsi_v < 38 and macd_up and vol_ok:
        return "reversal_controlled"
    return None


def _analyze_trend_swing(closes: list[float], volumes: list[float], timeframe: str) -> dict[str, Any]:
    price = closes[-1]
    sma_20 = sma(closes, 20)
    sma_50 = sma(closes, 50)
    ema_20 = ema(closes, 20)
    rsi_14 = rsi(closes, 14)
    m, ms, mh = macd(closes, 12, 26, 9)

    if any(
        x is None or (isinstance(x, float) and not math.isfinite(x))
        for x in (sma_20, sma_50, ema_20, rsi_14, m, ms, mh)
    ):
        raise ValueError("No se pudieron calcular todos los indicadores (serie demasiado corta o datos inconsistentes).")

    assert sma_20 is not None and sma_50 is not None and ema_20 is not None and rsi_14 is not None
    assert m is not None and ms is not None and mh is not None

    trend = _trend_label(price, sma_20, sma_50)
    momentum = _momentum_label(mh, rsi_14)
    risk = _risk_label(rsi_14)

    score = 50
    if trend == "alcista":
        score += 20
    elif trend == "bajista":
        score -= 20
    if momentum == "positivo":
        score += 15
    elif momentum == "negativo":
        score -= 15
    if risk == "alto":
        score -= 10
    score_i = int(max(0, min(100, round(score))))
    sig = _signal_label(score_i, risk)

    return {
        "price": round(price, 8),
        "sma_20": round(sma_20, 8),
        "sma_50": round(sma_50, 8),
        "ema_20": round(ema_20, 8),
        "rsi_14": round(rsi_14, 4),
        "macd": round(m, 8),
        "macd_signal": round(ms, 8),
        "macd_hist": round(mh, 8),
        "trend": trend,
        "momentum": momentum,
        "risk": risk,
        "score": score_i,
        "signal": sig,
        "strategy_mode": STRATEGY_MODE_TREND_SWING,
        "setup_type": None,
        "entry_eligible": sig == "compra_potencial",
        "trend_context": f"swing_{trend}",
        "rsi_context": _rsi_context_label(rsi_14, closes),
        "macd_context": _macd_context_label(mh, _macd_hist_prev(closes)),
        "volume_context": _volume_context_label(volumes),
        "btc_context": None,
        "timeframe": timeframe,
    }


def _analyze_daily_intraday(closes: list[float], volumes: list[float], timeframe: str) -> dict[str, Any]:
    price = closes[-1]
    ema_fast_p, ema_slow_p = _ema_periods_for_timeframe(timeframe, daily_mode=True)
    ema_fast = ema(closes, ema_fast_p)
    ema_slow = ema(closes, ema_slow_p)
    rsi_14 = rsi(closes, 14)
    m, ms, mh = macd(closes, 12, 26, 9)
    mh_prev = _macd_hist_prev(closes)

    if any(
        x is None or (isinstance(x, float) and not math.isfinite(x))
        for x in (ema_fast, ema_slow, rsi_14, m, ms, mh)
    ):
        raise ValueError("No se pudieron calcular indicadores intradía.")

    assert ema_fast is not None and ema_slow is not None and rsi_14 is not None
    assert m is not None and ms is not None and mh is not None

    short_trend = _short_trend_label(price, ema_fast, ema_slow)
    vol_ctx = _volume_context_label(volumes)
    rsi_ctx = _rsi_context_label(rsi_14, closes)
    macd_ctx = _macd_context_label(mh, mh_prev)
    setup_type = _pick_daily_setup_type(
        short_trend=short_trend,
        rsi_v=rsi_14,
        mh=mh,
        mh_prev=mh_prev,
        vol_ctx=vol_ctx,
        close=price,
        ema_fast=ema_fast,
    )

    score = 48
    if short_trend == "alcista":
        score += 14
    elif short_trend == "bajista":
        score -= 6
    if rsi_ctx in ("oversold_recovering", "low_recovering", "low_support"):
        score += 12
    elif rsi_ctx == "overbought":
        score -= 8
    if macd_ctx in ("improving_positive", "recovering"):
        score += 12
    elif macd_ctx == "weakening":
        score -= 6
    if vol_ctx == "rising":
        score += 8
    elif vol_ctx == "weak":
        score -= 4
    if setup_type:
        score += 6

    score_i = int(max(0, min(100, round(score))))
    sig: Signal = "compra_potencial" if score_i >= 70 and rsi_14 <= 72 else "neutral"
    entry_eligible = sig == "compra_potencial" or (
        setup_type in DAILY_SETUP_TYPES and score_i >= 55
    )

    return {
        "price": round(price, 8),
        "sma_20": round(ema_fast, 8),
        "sma_50": round(ema_slow, 8),
        "ema_20": round(ema_fast, 8),
        "rsi_14": round(rsi_14, 4),
        "macd": round(m, 8),
        "macd_signal": round(ms, 8),
        "macd_hist": round(mh, 8),
        "trend": short_trend,
        "momentum": "positivo" if mh > 0 else "negativo" if mh < 0 else "neutro",
        "risk": "medio",
        "score": score_i,
        "signal": sig,
        "strategy_mode": STRATEGY_MODE_DAILY_INTRADAY,
        "setup_type": setup_type,
        "entry_eligible": entry_eligible,
        "trend_context": f"short_{short_trend}",
        "rsi_context": rsi_ctx,
        "macd_context": macd_ctx,
        "volume_context": vol_ctx,
        "btc_context": None,
        "timeframe": timeframe,
    }


def analyze_ohlcv(
    candles: list[list[Any]],
    *,
    timeframe: str = "1h",
    strategy_mode: str | None = None,
) -> dict[str, Any]:
    """
    Devuelve dict serializable con indicadores y clasificación.
    strategy_mode trend_swing (default) conserva la lógica histórica; daily_intraday añade setups diarios.
    """
    tf = (timeframe or "1h").strip() or "1h"
    mode = normalize_strategy_mode(strategy_mode)
    closes, volumes = _parse_candles(candles)
    if mode == STRATEGY_MODE_DAILY_INTRADAY:
        out = _analyze_daily_intraday(closes, volumes, tf)
    else:
        out = _analyze_trend_swing(closes, volumes, tf)
    _log(
        f"analyze_ohlcv mode={out.get('strategy_mode')} tf={tf} trend={out.get('trend')} "
        f"score={out.get('score')} signal={out.get('signal')} setup={out.get('setup_type')} "
        f"eligible={out.get('entry_eligible')}"
    )
    return out
