"""
Binance Spot Testnet (capa separada): solo lectura en fase 1.
Credenciales dedicadas: BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_API_SECRET, BINANCE_TESTNET_ENABLED.
No usa BINANCE_API_KEY / BINANCE_API_SECRET (cuenta real).
"""
from __future__ import annotations

import os
from typing import Any

_LOG_PREFIX = "[CRYPTO_TESTNET]"
_HIGHLIGHT_ASSETS = ("USDT", "BTC", "ETH", "BNB")


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _api_key() -> str:
    return (os.getenv("BINANCE_TESTNET_API_KEY") or "").strip()


def _api_secret() -> str:
    return (os.getenv("BINANCE_TESTNET_API_SECRET") or "").strip()


def is_testnet_configured() -> bool:
    return bool(_api_key() and _api_secret())


def is_testnet_enabled() -> bool:
    return _env_bool("BINANCE_TESTNET_ENABLED", default=False)


def _ccxt_available() -> bool:
    try:
        import ccxt  # noqa: F401

        return True
    except ImportError:
        return False


def get_testnet_exchange() -> Any | None:
    """Instancia ccxt.binance en sandbox. None si falta config, ccxt o enabled=false."""
    if not is_testnet_enabled():
        _log("exchange: BINANCE_TESTNET_ENABLED=false")
        return None
    if not is_testnet_configured():
        _log("exchange: credenciales testnet vacías")
        return None
    if not _ccxt_available():
        _log("exchange: ccxt no instalado")
        return None

    try:
        import ccxt  # type: ignore[import-untyped]
    except ImportError:
        return None

    ex = ccxt.binance(
        {
            "apiKey": _api_key(),
            "secret": _api_secret(),
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )
    ex.set_sandbox_mode(True)
    _log("exchange: sandbox/testnet listo (solo lectura)")
    return ex


def get_testnet_status() -> dict[str, Any]:
    """Estado de la capa testnet (sin secretos)."""
    configured = is_testnet_configured()
    enabled = is_testnet_enabled()
    ccxt_ok = _ccxt_available()

    if not ccxt_ok:
        return {
            "configured": configured,
            "enabled": enabled,
            "ccxt_available": False,
            "can_read_balance": False,
            "can_read_ticker": False,
            "testnet": True,
            "message": "ccxt no instalado; revisá requirements.txt.",
        }

    if not configured:
        return {
            "configured": False,
            "enabled": enabled,
            "ccxt_available": True,
            "can_read_balance": False,
            "can_read_ticker": False,
            "testnet": True,
            "message": (
                "Testnet no configurado: definí BINANCE_TESTNET_API_KEY y "
                "BINANCE_TESTNET_API_SECRET en .env"
            ),
        }

    if not enabled:
        return {
            "configured": True,
            "enabled": False,
            "ccxt_available": True,
            "can_read_balance": False,
            "can_read_ticker": False,
            "testnet": True,
            "message": "Testnet configurado pero deshabilitado (BINANCE_TESTNET_ENABLED=false).",
        }

    bal_probe = get_testnet_balances()
    can_bal = bool(bal_probe.get("ok"))
    ticker_probe_ok = False
    if can_bal:
        try:
            get_testnet_ticker("BTC/USDT")
            ticker_probe_ok = True
        except Exception as e:
            _log(f"status: ticker probe falló {type(e).__name__}: {e}")

    if can_bal and ticker_probe_ok:
        msg = "Testnet conectado: lectura de balance y ticker OK (sin órdenes en esta fase)."
    elif can_bal:
        msg = "Testnet: balance OK; no se pudo verificar ticker BTC/USDT."
    else:
        err = bal_probe.get("error") or "unknown"
        msg = f"Testnet habilitado pero falló lectura de balance: {err}"

    return {
        "configured": True,
        "enabled": True,
        "ccxt_available": True,
        "can_read_balance": can_bal,
        "can_read_ticker": ticker_probe_ok,
        "testnet": True,
        "message": msg,
    }


def _balances_from_ccxt(bal: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    total = bal.get("total") if isinstance(bal.get("total"), dict) else {}
    free = bal.get("free") if isinstance(bal.get("free"), dict) else {}
    used = bal.get("used") if isinstance(bal.get("used"), dict) else {}

    rows: list[dict[str, Any]] = []
    highlights: dict[str, float] = {a: 0.0 for a in _HIGHLIGHT_ASSETS}

    for asset, t_raw in total.items():
        if not isinstance(asset, str):
            continue
        try:
            t = float(t_raw or 0)
            f = float(free.get(asset) or 0)
            u = float(used.get(asset) or 0)
        except (TypeError, ValueError):
            continue
        if t <= 0 and f <= 0 and u <= 0:
            continue
        row = {"asset": asset.upper(), "free": f, "used": u, "total": t}
        rows.append(row)
        if asset.upper() in highlights:
            highlights[asset.upper()] = t

    rows.sort(key=lambda r: (-(r["total"] or 0), str(r["asset"])))
    return rows, highlights


def get_testnet_balances() -> dict[str, Any]:
    """Balances spot testnet (solo lectura)."""
    if not is_testnet_enabled():
        return {"ok": False, "error": "disabled", "balances": [], "highlights": {}}
    ex = get_testnet_exchange()
    if ex is None:
        return {"ok": False, "error": "not_configured", "balances": [], "highlights": {}}

    try:
        bal = ex.fetch_balance()
        if not isinstance(bal, dict):
            return {"ok": False, "error": "invalid_balance_response", "balances": [], "highlights": {}}
        rows, highlights = _balances_from_ccxt(bal)
        _log(f"balances: OK assets={len(rows)}")
        return {"ok": True, "error": None, "balances": rows, "highlights": highlights}
    except Exception as e:
        _log(f"balances: fallo {type(e).__name__}: {e}")
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "balances": [],
            "highlights": {a: 0.0 for a in _HIGHLIGHT_ASSETS},
        }


def get_testnet_account_info() -> dict[str, Any]:
    """Resumen de cuenta testnet derivado del balance (sin secretos ni órdenes)."""
    bal = get_testnet_balances()
    if not bal.get("ok"):
        return {
            "ok": False,
            "error": bal.get("error"),
            "asset_count": 0,
            "highlights": bal.get("highlights") or {},
            "balances": [],
        }
    balances = bal.get("balances") or []
    return {
        "ok": True,
        "error": None,
        "asset_count": len(balances),
        "highlights": bal.get("highlights") or {},
        "balances": balances,
    }


def get_testnet_ticker(symbol: str) -> dict[str, Any]:
    """Ticker spot en testnet (público con sandbox)."""
    if not is_testnet_enabled():
        raise RuntimeError("BINANCE_TESTNET_ENABLED=false")
    sym = (symbol or "").strip()
    if not sym:
        raise ValueError("symbol vacío")

    try:
        import ccxt  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError("ccxt no instalado") from e

    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    ex.set_sandbox_mode(True)
    _log(f"ticker: {sym}")
    raw = ex.fetch_ticker(sym)
    if not isinstance(raw, dict):
        return {"symbol": sym, "last": None, "percentage": None}
    return {
        "symbol": sym,
        "last": raw.get("last"),
        "percentage": raw.get("percentage"),
        "bid": raw.get("bid"),
        "ask": raw.get("ask"),
        "baseVolume": raw.get("baseVolume"),
        "quoteVolume": raw.get("quoteVolume"),
    }
