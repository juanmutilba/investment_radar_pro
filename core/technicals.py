from __future__ import annotations

import pandas as pd

from core.config import MA_LONG, MA_SHORT, RSI_WINDOW


def compute_technical_metrics(close: pd.Series) -> dict:
    """
    Técnicos mínimos sin dependencias pesadas (evita requerir scipy vía librerías externas).

    - Precio: último close
    - RSI: Wilder (EWMA alpha=1/n)
    - MA50 / MA200: rolling mean
    - MACD: EMA12-EMA26 vs señal EMA9
    """
    s = pd.to_numeric(close, errors="coerce").dropna()
    price = float(s.iloc[-1])

    # RSI Wilder
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    alpha = 1.0 / float(RSI_WINDOW)
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    rsi = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0

    ma50 = float(s.rolling(MA_SHORT).mean().iloc[-1])
    ma200 = float(s.rolling(MA_LONG).mean().iloc[-1])

    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()

    return {
        'Precio': round(price, 2),
        'RSI': round(rsi, 2),
        'MA50': round(ma50, 2),
        'MA200': round(ma200, 2),
        'MACD_Bull': float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]),
        'Pullback': price < ma50,
        'Trend': ma50 > ma200,
    }
