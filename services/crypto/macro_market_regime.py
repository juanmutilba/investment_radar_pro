"""
Régimen macro spot (BTC/USDT, 4h, EMA200). Solo lectura; sin órdenes ni WebSockets.

Usado como filtro opcional antes de nuevas compras long en paper/testnet.
"""
from __future__ import annotations

import math
from typing import Any, Literal

from services.crypto.providers import binance_provider as bp
from services.crypto.signals import ema

_LOG_PREFIX = "[CRYPTO_MACRO]"

MACRO_SYMBOL_CCXT = "BTC/USDT"
MACRO_SYMBOL_DISPLAY = "BTCUSDT"
MACRO_TIMEFRAME = "4h"
MACRO_CANDLE_LIMIT = 250
EMA_PERIOD = 200
BULL_BAND = 1.005
BEAR_BAND = 0.995

Regime = Literal["bull", "bear", "neutral", "unknown"]


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _unknown_payload(reason: str) -> dict[str, Any]:
    return {
        "symbol": MACRO_SYMBOL_DISPLAY,
        "timeframe": MACRO_TIMEFRAME,
        "close": None,
        "ema200": None,
        "regime": "unknown",
        "allow_longs": False,
        "score_adjustment": 0.0,
        "reason": reason,
    }


def get_macro_market_regime_payload() -> dict[str, Any]:
    """
    Devuelve régimen macro BTC 4h vs EMA200.

    Si falla fetch o indicadores: regime=unknown, allow_longs=false (conservador).
    No lanza excepciones al caller.
    """
    try:
        candles = bp.fetch_ohlcv(MACRO_SYMBOL_CCXT, timeframe=MACRO_TIMEFRAME, limit=MACRO_CANDLE_LIMIT)
    except Exception as e:
        msg = f"No se pudo obtener OHLCV: {type(e).__name__}: {e}"
        _log(msg)
        return _unknown_payload(msg)

    if not isinstance(candles, list) or len(candles) < EMA_PERIOD + 1:
        msg = f"Velas insuficientes ({len(candles) if isinstance(candles, list) else 0}); se requieren >={EMA_PERIOD}."
        _log(msg)
        return _unknown_payload(msg)

    closes: list[float] = []
    try:
        for i, row in enumerate(candles):
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                return _unknown_payload(f"Vela inválida en índice {i}.")
            c = row[4]
            if not isinstance(c, (int, float)) or isinstance(c, bool) or not math.isfinite(float(c)):
                return _unknown_payload(f"Cierre inválido en índice {i}.")
            closes.append(float(c))
    except Exception as e:
        return _unknown_payload(f"Parseo velas: {type(e).__name__}: {e}")

    ema200 = ema(closes, EMA_PERIOD)
    if ema200 is None or not math.isfinite(ema200):
        return _unknown_payload("EMA200 no calculable (serie corta o datos inconsistentes).")

    close = closes[-1]
    if not math.isfinite(close):
        return _unknown_payload("Último cierre no finito.")

    upper = ema200 * BULL_BAND
    lower = ema200 * BEAR_BAND
    regime: Regime
    if close > upper:
        regime = "bull"
    elif close < lower:
        regime = "bear"
    else:
        regime = "neutral"

    if regime == "bull":
        allow_longs = True
        score_adjustment = 0.0
        reason = "close > EMA200 * 1.005 (sesgo alcista macro)"
    elif regime == "bear":
        allow_longs = False
        score_adjustment = -20.0
        reason = "close < EMA200 * 0.995 (sesgo bajista macro; bloqueo de nuevos longs)"
    else:
        allow_longs = True
        score_adjustment = -5.0
        reason = "close entre bandas 0.995–1.005 × EMA200 (macro neutral; penalización leve en score)"

    out = {
        "symbol": MACRO_SYMBOL_DISPLAY,
        "timeframe": MACRO_TIMEFRAME,
        "close": round(close, 8),
        "ema200": round(float(ema200), 8),
        "regime": regime,
        "allow_longs": allow_longs,
        "score_adjustment": float(score_adjustment),
        "reason": reason,
    }
    _log(f"OK regime={regime} close={out['close']} ema200={out['ema200']} allow_longs={allow_longs}")
    return out
