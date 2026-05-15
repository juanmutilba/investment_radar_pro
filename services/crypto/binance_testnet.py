"""
Binance Spot Testnet (capa separada): solo lectura en fase 1.
Credenciales dedicadas: BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_API_SECRET, BINANCE_TESTNET_ENABLED.
No usa BINANCE_API_KEY / BINANCE_API_SECRET (cuenta real).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

_LOG_PREFIX = "[CRYPTO_TESTNET]"
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_PROBE_SYMBOL = "BTC/USDT"
UrlsApiSafe = Literal["sandbox", "testnet", "real", "unknown"]


def _ensure_dotenv() -> None:
    """Fallback si el proceso no cargó .env (p. ej. API sin reiniciar tras editar .env)."""
    if _api_key() and _api_secret():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if _ENV_FILE.is_file():
        load_dotenv(_ENV_FILE, override=True)


_HIGHLIGHT_ASSETS = ("USDT", "BTC", "ETH", "BNB")


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _enabled_raw() -> str | None:
    raw = os.getenv("BINANCE_TESTNET_ENABLED")
    if raw is None:
        return None
    s = raw.strip()
    return s if s else None


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


def _classify_urls_api_safe(ex: Any) -> UrlsApiSafe:
    """Clasifica endpoints ccxt sin exponer URLs completas."""
    urls = getattr(ex, "urls", None)
    api = urls.get("api") if isinstance(urls, dict) else None
    if not isinstance(api, dict) or not api:
        return "unknown"

    parts: list[str] = []
    for value in api.values():
        if isinstance(value, str):
            parts.append(value.lower())
    if not parts:
        return "unknown"

    blob = " ".join(parts)
    if "testnet.binance.vision" in blob:
        return "sandbox"
    if "testnet.binancefuture" in blob or "testnet.binance" in blob:
        return "testnet"
    if "api.binance.com" in blob:
        return "real"
    return "unknown"


def _detect_sandbox_mode(ex: Any) -> bool:
    return _classify_urls_api_safe(ex) in ("sandbox", "testnet")


def _exchange_diagnostics(ex: Any | None) -> dict[str, Any]:
    if ex is None:
        return {
            "sandbox_mode": False,
            "exchange_id": None,
            "default_type": None,
            "urls_api_safe": "unknown",
        }
    opts = getattr(ex, "options", None)
    default_type = opts.get("defaultType") if isinstance(opts, dict) else None
    return {
        "sandbox_mode": _detect_sandbox_mode(ex),
        "exchange_id": getattr(ex, "id", None),
        "default_type": default_type,
        "urls_api_safe": _classify_urls_api_safe(ex),
    }


def _build_sandbox_exchange(*, with_credentials: bool) -> Any:
    """
    ccxt.binance + set_sandbox_mode(True) inmediatamente después de crear.
    with_credentials=False: solo endpoints públicos (ticker).
    """
    import ccxt  # type: ignore[import-untyped]

    config: dict[str, Any] = {
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    }
    if with_credentials:
        config["apiKey"] = _api_key()
        config["secret"] = _api_secret()
    ex = ccxt.binance(config)
    ex.set_sandbox_mode(True)
    return ex


def _diagnostics_exchange(*, with_credentials: bool = False) -> Any | None:
    if not _ccxt_available():
        return None
    try:
        return _build_sandbox_exchange(with_credentials=with_credentials)
    except Exception:
        return None


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

    ex = _build_sandbox_exchange(with_credentials=True)
    _log("exchange: sandbox/testnet listo (solo lectura)")
    return ex


def _safe_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _probe_ticker(ex: Any) -> tuple[bool, str | None]:
    try:
        raw = ex.fetch_ticker(_PROBE_SYMBOL)
        if isinstance(raw, dict) and raw.get("last") is not None:
            return True, None
        return False, "invalid_ticker_response"
    except Exception as e:
        return False, _safe_error(e)


def _probe_balance(ex: Any) -> tuple[bool, str | None]:
    try:
        bal = ex.fetch_balance()
        if isinstance(bal, dict):
            return True, None
        return False, "invalid_balance_response"
    except Exception as e:
        return False, _safe_error(e)


def _diagnosis_hint(
    *,
    urls_api_safe: UrlsApiSafe | str,
    sandbox_mode: bool,
    can_read_ticker: bool,
    can_read_balance: bool,
    configured: bool,
    enabled: bool,
) -> str:
    if urls_api_safe == "real":
        return "sandbox_misconfigured"
    if not sandbox_mode and enabled:
        return "sandbox_mode_inactive"
    if can_read_ticker and not can_read_balance and configured:
        return "keys_or_permissions"
    if not can_read_ticker and not can_read_balance and sandbox_mode:
        return "network_or_testnet_down"
    if can_read_ticker and can_read_balance:
        return "ok"
    if not enabled:
        return "disabled"
    if not configured:
        return "not_configured"
    return "unknown"


def _status_core(
    *,
    configured: bool,
    enabled: bool,
    ccxt_available: bool,
    can_read_balance: bool,
    can_read_ticker: bool,
    message: str,
    diag: dict[str, Any],
    diagnosis: str,
    ticker_error: str | None = None,
    balance_error: str | None = None,
) -> dict[str, Any]:
    return {
        "configured": configured,
        "enabled": enabled,
        "api_key_present": bool(_api_key()),
        "api_secret_present": bool(_api_secret()),
        "enabled_raw": _enabled_raw(),
        "ccxt_available": ccxt_available,
        "can_read_balance": can_read_balance,
        "can_read_ticker": can_read_ticker,
        "testnet": True,
        "sandbox_mode": diag.get("sandbox_mode", False),
        "exchange_id": diag.get("exchange_id"),
        "default_type": diag.get("default_type"),
        "urls_api_safe": diag.get("urls_api_safe", "unknown"),
        "diagnosis": diagnosis,
        "ticker_error": ticker_error,
        "balance_error": balance_error,
        "message": message,
    }


def get_testnet_status() -> dict[str, Any]:
    """Estado de la capa testnet (sin secretos ni URLs completas)."""
    _ensure_dotenv()
    configured = is_testnet_configured()
    enabled = is_testnet_enabled()
    ccxt_ok = _ccxt_available()

    diag_ex = _diagnostics_exchange(with_credentials=False) if ccxt_ok else None
    diag = _exchange_diagnostics(diag_ex)

    if not ccxt_ok:
        return _status_core(
            configured=configured,
            enabled=enabled,
            ccxt_available=False,
            can_read_balance=False,
            can_read_ticker=False,
            message="ccxt no instalado; revisá requirements.txt.",
            diag=diag,
            diagnosis="ccxt_missing",
        )

    if not configured:
        return _status_core(
            configured=False,
            enabled=enabled,
            ccxt_available=True,
            can_read_balance=False,
            can_read_ticker=False,
            message=(
                "Testnet no configurado: definí BINANCE_TESTNET_API_KEY y "
                "BINANCE_TESTNET_API_SECRET en .env (reiniciá el servidor API tras guardar). "
                f"Archivo .env esperado: {_ENV_FILE}"
            ),
            diag=diag,
            diagnosis="not_configured",
        )

    if not enabled:
        return _status_core(
            configured=True,
            enabled=False,
            ccxt_available=True,
            can_read_balance=False,
            can_read_ticker=False,
            message="Testnet configurado pero deshabilitado (BINANCE_TESTNET_ENABLED=false).",
            diag=diag,
            diagnosis="disabled",
        )

    can_ticker = False
    can_bal = False
    ticker_err: str | None = None
    balance_err: str | None = None

    pub_ex = _diagnostics_exchange(with_credentials=False)
    if pub_ex is not None:
        diag = _exchange_diagnostics(pub_ex)
        can_ticker, ticker_err = _probe_ticker(pub_ex)
        if not can_ticker:
            _log(f"status: ticker probe falló {ticker_err}")

    auth_ex = get_testnet_exchange()
    if auth_ex is not None:
        auth_diag = _exchange_diagnostics(auth_ex)
        if auth_diag.get("urls_api_safe") != "unknown":
            diag = auth_diag
        can_bal, balance_err = _probe_balance(auth_ex)
        if not can_bal:
            _log(f"status: balance probe falló {balance_err}")

    diagnosis = _diagnosis_hint(
        urls_api_safe=str(diag.get("urls_api_safe") or "unknown"),
        sandbox_mode=bool(diag.get("sandbox_mode")),
        can_read_ticker=can_ticker,
        can_read_balance=can_bal,
        configured=True,
        enabled=True,
    )

    if diagnosis == "sandbox_misconfigured":
        msg = "Cliente ccxt apunta a Binance real (urls_api_safe=real). Revisar set_sandbox_mode(True)."
    elif diagnosis == "sandbox_mode_inactive":
        msg = "Sandbox no detectado en URLs ccxt tras set_sandbox_mode(True)."
    elif diagnosis == "keys_or_permissions":
        msg = (
            f"Sandbox OK ({diag.get('urls_api_safe')}); ticker {_PROBE_SYMBOL} OK. "
            f"Balance falló: revisar keys de testnet.binance.vision, IP y permisos de lectura."
        )
    elif diagnosis == "network_or_testnet_down":
        parts = [f"ticker={ticker_err or 'fail'}"]
        if balance_err:
            parts.append(f"balance={balance_err}")
        msg = f"Sandbox detectado pero fallaron lecturas: {'; '.join(parts)}"
    elif diagnosis == "ok":
        msg = "Testnet conectado: ticker público y balance OK (sin órdenes en esta fase)."
    else:
        msg = "Estado testnet indeterminado; revisar diagnosis y errores de probe."

    return _status_core(
        configured=True,
        enabled=True,
        ccxt_available=True,
        can_read_balance=can_bal,
        can_read_ticker=can_ticker,
        message=msg,
        diag=diag,
        diagnosis=diagnosis,
        ticker_error=ticker_err,
        balance_error=balance_err,
    )


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
    _ensure_dotenv()
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
        err = _safe_error(e)
        _log(f"balances: fallo {err}")
        return {
            "ok": False,
            "error": err,
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
    """Ticker spot en testnet (público; sandbox sin credenciales en la petición)."""
    _ensure_dotenv()
    if not is_testnet_enabled():
        raise RuntimeError("BINANCE_TESTNET_ENABLED=false")
    sym = (symbol or "").strip()
    if not sym:
        raise ValueError("symbol vacío")
    if not _ccxt_available():
        raise RuntimeError("ccxt no instalado")

    ex = _build_sandbox_exchange(with_credentials=False)
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
