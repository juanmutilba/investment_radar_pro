"""
Binance (spot) vía ccxt: solo lectura en esta fase (ticker, OHLCV, balance de prueba).
Credenciales: BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_TESTNET, CRYPTO_TRADING_ENABLED.
"""
from __future__ import annotations

import os
from typing import Any

_LOG_PREFIX = "[CRYPTO]"


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _api_key() -> str:
    return (os.getenv("BINANCE_API_KEY") or "").strip()


def _api_secret() -> str:
    return (os.getenv("BINANCE_API_SECRET") or "").strip()


def is_binance_configured() -> bool:
    return bool(_api_key() and _api_secret())


def is_crypto_trading_enabled() -> bool:
    """Flag de entorno; no implica que este módulo envíe órdenes (aún no implementado)."""
    return _env_bool("CRYPTO_TRADING_ENABLED", default=False)


def is_binance_testnet() -> bool:
    return _env_bool("BINANCE_TESTNET", default=False)


def get_binance_exchange() -> Any | None:
    """
    Instancia ccxt.binance (spot) o None si faltan API key/secret.
    Respeta BINANCE_TESTNET (sandbox de Binance vía ccxt).
    """
    try:
        import ccxt  # type: ignore[import-untyped]
    except ImportError:
        _log("ccxt no está instalado; pip install -r requirements.txt")
        return None

    key, secret = _api_key(), _api_secret()
    if not key or not secret:
        _log("get_binance_exchange: BINANCE_API_KEY o BINANCE_API_SECRET vacíos")
        return None

    exchange = ccxt.binance(
        {
            "apiKey": key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )
    if is_binance_testnet():
        exchange.set_sandbox_mode(True)
        _log("get_binance_exchange: modo sandbox/testnet activado (ccxt.set_sandbox_mode)")
    else:
        _log("get_binance_exchange: instancia creada (spot, red principal si keys son live)")

    return exchange


def fetch_ticker(symbol: str) -> dict[str, Any]:
    """Ticker spot (no requiere API keys para la mayoría de exchanges; Binance suele permitir público)."""
    try:
        import ccxt  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError("ccxt no instalado") from e

    sym = (symbol or "").strip()
    if not sym:
        raise ValueError("symbol vacío")

    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    if is_binance_testnet():
        ex.set_sandbox_mode(True)
    _log(f"fetch_ticker: {sym}")
    return ex.fetch_ticker(sym)


def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 200) -> list[list[Any]]:
    """Velas OHLCV (datos públicos)."""
    try:
        import ccxt  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError("ccxt no instalado") from e

    sym = (symbol or "").strip()
    if not sym:
        raise ValueError("symbol vacío")
    tf = (timeframe or "1h").strip() or "1h"
    lim = max(1, min(int(limit), 1000))

    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    if is_binance_testnet():
        ex.set_sandbox_mode(True)
    _log(f"fetch_ohlcv: {sym} tf={tf} limit={lim}")
    return ex.fetch_ohlcv(sym, timeframe=tf, limit=lim)


def fetch_balance_safe() -> dict[str, Any]:
    """
    Intenta fetch_balance con credenciales configuradas.
    No lanza: devuelve { ok, error, total } donde total es el dict resumen de ccxt (solo claves numéricas útiles).
    """
    ex = get_binance_exchange()
    if ex is None:
        return {"ok": False, "error": "not_configured", "total": None}

    try:
        bal = ex.fetch_balance()
        total = bal.get("total") if isinstance(bal, dict) else None
        _log("fetch_balance_safe: OK")
        return {"ok": True, "error": None, "total": total}
    except Exception as e:
        _log(f"fetch_balance_safe: fallo {type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "total": None}


def crypto_status_payload() -> dict[str, Any]:
    """Cuerpo de GET /crypto/status (sin secretos)."""
    try:
        import ccxt  # noqa: F401
    except ImportError:
        return {
            "configured": False,
            "trading_enabled": is_crypto_trading_enabled(),
            "testnet": is_binance_testnet(),
            "can_read_balance": False,
            "message": "ccxt no instalado; agregá dependencias (requirements.txt) y reinstalá el entorno.",
        }

    configured = is_binance_configured()
    trading_enabled = is_crypto_trading_enabled()
    testnet = is_binance_testnet()

    if not configured:
        msg = "Binance no configurado: definí BINANCE_API_KEY y BINANCE_API_SECRET en .env"
        _log("crypto_status: no configurado")
        return {
            "configured": False,
            "trading_enabled": trading_enabled,
            "testnet": testnet,
            "can_read_balance": False,
            "message": msg,
        }

    bal = fetch_balance_safe()
    can_read = bool(bal.get("ok"))
    if can_read:
        msg = "Credenciales cargadas; lectura de balance OK (sin operaciones de trading en esta fase)."
    else:
        err = bal.get("error") or "unknown"
        msg = f"Credenciales presentes pero no se pudo leer balance: {err}"

    _log(f"crypto_status: configured={configured} testnet={testnet} can_read_balance={can_read}")
    return {
        "configured": True,
        "trading_enabled": trading_enabled,
        "testnet": testnet,
        "can_read_balance": can_read,
        "message": msg,
    }
