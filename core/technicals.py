from __future__ import annotations

import pandas as pd
import ta

from config import MA_LONG, MA_SHORT, RSI_WINDOW


def compute_technical_metrics(close: pd.Series) -> dict:
    price = float(close.iloc[-1])
    rsi = float(ta.momentum.RSIIndicator(close, RSI_WINDOW).rsi().iloc[-1])
    ma50 = float(close.rolling(MA_SHORT).mean().iloc[-1])
    ma200 = float(close.rolling(MA_LONG).mean().iloc[-1])

    macd = ta.trend.MACD(close)
    macd_line = float(macd.macd().iloc[-1])
    signal_line = float(macd.macd_signal().iloc[-1])

    return {
        'Precio': round(price, 2),
        'RSI': round(rsi, 2),
        'MA50': round(ma50, 2),
        'MA200': round(ma200, 2),
        'MACD_Bull': macd_line > signal_line,
        'Pullback': price < ma50,
        'Trend': ma50 > ma200,
    }
