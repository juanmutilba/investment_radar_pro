"""
Watchlist y scanner multi-activo (solo lectura; sin órdenes).
"""
from __future__ import annotations

from typing import Any

from services.crypto.providers import binance_provider as bp
from services.crypto.signals import MIN_OHLCV_ROWS, analyze_ohlcv

_LOG_PREFIX = "[CRYPTO_SCAN]"

CRYPTO_WATCHLIST: list[str] = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "MATIC/USDT",
]


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def get_crypto_watchlist() -> list[str]:
    """Lista de pares spot a escanear (copia para no mutar la constante)."""
    return list(CRYPTO_WATCHLIST)


def _error_row(symbol: str, timeframe: str, error: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "price": None,
        "score": None,
        "signal": None,
        "trend": None,
        "momentum": None,
        "risk": None,
        "rsi_14": None,
        "macd_hist": None,
        "error": error,
    }


def _scan_one(symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
    sym = symbol.strip()
    tf = (timeframe or "1h").strip() or "1h"
    try:
        candles = bp.fetch_ohlcv(sym, timeframe=tf, limit=limit)
    except Exception as e:
        _log(f"{sym}: fetch_ohlcv fallo {type(e).__name__}: {e}")
        return _error_row(sym, tf, f"{type(e).__name__}: {e}")

    if len(candles) < MIN_OHLCV_ROWS:
        msg = (
            f"Velas insuficientes ({len(candles)}); se requieren al menos {MIN_OHLCV_ROWS}."
        )
        _log(f"{sym}: {msg}")
        return _error_row(sym, tf, msg)

    try:
        analysis = analyze_ohlcv(candles)
    except ValueError as e:
        _log(f"{sym}: analyze_ohlcv {e}")
        return _error_row(sym, tf, str(e))
    except Exception as e:
        _log(f"{sym}: analyze_ohlcv fallo {type(e).__name__}: {e}")
        return _error_row(sym, tf, f"{type(e).__name__}: {e}")

    _log(f"{sym}: OK score={analysis.get('score')} signal={analysis.get('signal')}")
    return {
        "symbol": sym,
        "timeframe": tf,
        "price": analysis["price"],
        "score": analysis["score"],
        "signal": analysis["signal"],
        "trend": analysis["trend"],
        "momentum": analysis["momentum"],
        "risk": analysis["risk"],
        "rsi_14": analysis["rsi_14"],
        "macd_hist": analysis["macd_hist"],
        "error": None,
    }


def _sort_scan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ok = [r for r in rows if not r.get("error")]
    bad = [r for r in rows if r.get("error")]
    ok.sort(key=lambda r: -(r.get("score") or 0))
    bad.sort(key=lambda r: str(r.get("symbol") or ""))
    return ok + bad


def scan_crypto_watchlist(timeframe: str = "1h", limit: int = 200) -> list[dict[str, Any]]:
    """
    Escanea todos los símbolos de la watchlist.
    Un fallo por símbolo no interrumpe el resto.
    """
    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    symbols = get_crypto_watchlist()
    _log(f"inicio symbols={len(symbols)} timeframe={tf} limit={lim}")
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        rows.append(_scan_one(sym, tf, lim))
    out = _sort_scan_rows(rows)
    ok_n = sum(1 for r in out if not r.get("error"))
    _log(f"fin ok={ok_n} errores={len(out) - ok_n}")
    return out
