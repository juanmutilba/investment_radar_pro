"""
Indicadores técnicos sobre cierres (solo stdlib / matemática pura).
Velas ccxt: [timestamp, open, high, low, close, volume].
"""
from __future__ import annotations

import math
from typing import Any, Literal

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


def analyze_ohlcv(candles: list[list[Any]]) -> dict[str, Any]:
    """
    Devuelve dict serializable con indicadores y clasificación simple.
    Raises ValueError si faltan filas o datos inválidos.
    """
    if not isinstance(candles, list) or len(candles) < MIN_OHLCV_ROWS:
        raise ValueError(
            f"Se requieren al menos {MIN_OHLCV_ROWS} velas para SMA50/MACD/RSI; recibidas {len(candles) if isinstance(candles, list) else 0}."
        )

    closes: list[float] = []
    for i, row in enumerate(candles):
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            raise ValueError(f"Vela inválida en índice {i}: se espera [ts, o, h, l, c, v].")
        c = row[4]
        if not isinstance(c, (int, float)) or isinstance(c, bool) or not math.isfinite(float(c)):
            raise ValueError(f"Cierre inválido en índice {i}.")
        closes.append(float(c))

    price = closes[-1]
    sma_20 = sma(closes, 20)
    sma_50 = sma(closes, 50)
    ema_20 = ema(closes, 20)
    rsi_14 = rsi(closes, 14)
    m, ms, mh = macd(closes, 12, 26, 9)

    if any(x is None or (isinstance(x, float) and not math.isfinite(x)) for x in (sma_20, sma_50, ema_20, rsi_14, m, ms, mh)):
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

    out = {
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
    }
    _log(f"analyze_ohlcv: trend={trend} momentum={momentum} risk={risk} score={score_i} signal={sig}")
    return out
