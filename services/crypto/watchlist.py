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
    "DOGE/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "MATIC/USDT",
    "LTC/USDT",
    "UNI/USDT",
    "ATOM/USDT",
    "TRX/USDT",
    "NEAR/USDT",
    "BCH/USDT",
    "APT/USDT",
    "INJ/USDT",
    "ARB/USDT",
    "OP/USDT",
    "SUI/USDT",
    "PEPE/USDT",
    "WIF/USDT",
]


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def get_crypto_watchlist() -> list[str]:
    """Lista de pares spot a escanear (copia para no mutar la constante)."""
    return list(CRYPTO_WATCHLIST)


def get_crypto_watchlist_count() -> int:
    """Cantidad de pares en la watchlist del bot (constante CRYPTO_WATCHLIST)."""
    return len(CRYPTO_WATCHLIST)


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


def _scan_one(symbol: str, timeframe: str, limit: int, strategy_mode: str | None = None) -> dict[str, Any]:
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
        analysis = analyze_ohlcv(candles, timeframe=tf, strategy_mode=strategy_mode)
    except ValueError as e:
        _log(f"{sym}: analyze_ohlcv {e}")
        return _error_row(sym, tf, str(e))
    except Exception as e:
        _log(f"{sym}: analyze_ohlcv fallo {type(e).__name__}: {e}")
        return _error_row(sym, tf, f"{type(e).__name__}: {e}")

    _log(
        f"{sym}: OK mode={analysis.get('strategy_mode')} score={analysis.get('score')} "
        f"signal={analysis.get('signal')} setup={analysis.get('setup_type')}"
    )
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
        "strategy_mode": analysis.get("strategy_mode"),
        "setup_type": analysis.get("setup_type"),
        "entry_eligible": analysis.get("entry_eligible"),
        "trend_context": analysis.get("trend_context"),
        "rsi_context": analysis.get("rsi_context"),
        "macd_context": analysis.get("macd_context"),
        "volume_context": analysis.get("volume_context"),
        "btc_context": analysis.get("btc_context"),
        "error": None,
    }


def _sort_scan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ok = [r for r in rows if not r.get("error")]
    bad = [r for r in rows if r.get("error")]
    ok.sort(key=lambda r: -(r.get("score") or 0))
    bad.sort(key=lambda r: str(r.get("symbol") or ""))
    return ok + bad


def scan_crypto_watchlist(
    timeframe: str = "1h",
    limit: int = 200,
    strategy_mode: str | None = None,
) -> list[dict[str, Any]]:
    """
    Escanea todos los símbolos de la watchlist.
    Un fallo por símbolo no interrumpe el resto.
    """
    from services.crypto.strategy_modes import normalize_strategy_mode

    tf = (timeframe or "1h").strip() or "1h"
    lim = max(50, min(int(limit), 1000))
    mode = normalize_strategy_mode(strategy_mode)
    symbols = get_crypto_watchlist()
    wl_count = len(symbols)
    _log(f"inicio symbols={wl_count} timeframe={tf} limit={lim} strategy_mode={mode}")
    if wl_count == 0:
        _log("watchlist vacía: CRYPTO_WATCHLIST sin símbolos")
        return []
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        rows.append(_scan_one(sym, tf, lim, strategy_mode=mode))
    out = _sort_scan_rows(rows)
    ok_n = sum(1 for r in out if not r.get("error"))
    _log(f"fin ok={ok_n} errores={len(out) - ok_n}")
    return out
