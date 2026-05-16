"""
Binance Spot Testnet (capa separada): lectura + orden market BUY acotada (testnet).
Credenciales dedicadas: BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_API_SECRET, BINANCE_TESTNET_ENABLED.
No usa BINANCE_API_KEY / BINANCE_API_SECRET (cuenta real).
"""
from __future__ import annotations

import os
import time as time_mod
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


_HIGHLIGHT_ASSETS = ("USDT", "BTC", "ETH", "BNB", "SOL")

MARKET_ORDER_SYMBOL_WHITELIST: frozenset[str] = frozenset(
    {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"}
)
MAX_MARKET_ORDER_QUOTE_USDT: float = 25.0
MIN_MARKET_ORDER_QUOTE_USDT: float = 0.01


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


def is_testnet_auth_debug_enabled() -> bool:
    """GET /crypto/testnet/auth-debug solo si CRYPTO_TESTNET_DEBUG=true (default off)."""
    return _env_bool("CRYPTO_TESTNET_DEBUG", default=False)


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


def _urls_private_route_hint(ex: Any) -> dict[str, Any]:
    """Clasifica rutas esperadas sin exponer URLs completas (solo host + patrón de path)."""
    urls = getattr(ex, "urls", None)
    api = urls.get("api") if isinstance(urls, dict) else None
    if not isinstance(api, dict):
        return {
            "private_host_hint": None,
            "private_path_pattern": None,
            "sapi_urls_present_after_sandbox": False,
            "notes": "urls.api inválidas",
        }
    priv_raw = api.get("private")
    pub_raw = api.get("public")

    priv = ""
    if isinstance(priv_raw, str):
        priv = priv_raw.strip().lower()
    pub = pub_raw.strip().lower() if isinstance(pub_raw, str) else ""

    host_hint = None
    path_pattern = None
    if isinstance(priv_raw, str):
        lu = priv_raw.strip().lower()
        try:
            from urllib.parse import urlparse

            parsed = urlparse(lu if "://" in lu else f"https://{lu}")
            host_hint = (parsed.hostname or "").lower().split(":")[0] if parsed.hostname else None
            p = parsed.path or ""
            path_pattern = p.rstrip("/") or None
        except Exception:
            host_hint = "parse_error"
        priv = lu

    sapi_any = False
    for key, val in api.items():
        if not isinstance(val, str):
            continue
        low = val.lower()
        if "/sapi/" in low or low.rstrip("/").endswith("/sapi/v1"):
            sapi_any = True
            break

    if "/api/v3" in priv:
        routing = "spot_private_api_v3"
    elif "/sapi/" in priv or "/sapi" in priv[-20:]:
        routing = "sapi_like"
    else:
        routing = "other_or_unknown"

    return {
        "private_host_hint": host_hint,
        "private_path_pattern": path_pattern,
        "balance_expected_routing_binance": routing,
        "spot_public_host_hint_matches_private": (
            bool(host_hint and pub and host_hint in pub) if host_hint else None
        ),
        "sapi_urls_present_after_sandbox": sapi_any,
        "notes": "fetch_balance usa private (spot/account). No se registran URLs con query/sign.",
    }


def _build_sandbox_exchange(
    *,
    with_credentials: bool,
    adjust_for_time_difference: bool = False,
) -> Any:
    """
    ccxt.binance + set_sandbox_mode(True) inmediatamente después de crear.
    with_credentials=False: solo endpoints públicos (ticker).
    """
    import ccxt  # type: ignore[import-untyped]

    options: dict[str, Any] = {"defaultType": "spot"}
    if adjust_for_time_difference:
        options["adjustForTimeDifference"] = True

    config: dict[str, Any] = {"enableRateLimit": True, "options": options}
    if with_credentials:
        config["apiKey"] = _api_key()
        config["secret"] = _api_secret()
    ex = ccxt.binance(config)
    ex.set_sandbox_mode(True)
    return ex


def _recv_window_option(ex: Any) -> int | None:
    o = getattr(ex, "options", None)
    if isinstance(o, dict):
        rv = o.get("recvWindow")
        if isinstance(rv, (int, float)) and rv == int(rv):
            return int(rv)
    return None


def _exchange_signed_request_trace(ex: Any) -> dict[str, Any]:
    """Rastro no sensible tras requests (ccxt opcional por versión)."""
    out: dict[str, Any] = {"last_request_path_hint": None, "last_http_status": None}
    url = getattr(ex, "last_request_url", None) or getattr(ex, "lastRequestUrl", None)
    if isinstance(url, str) and url:
        try:
            from urllib.parse import urlparse

            p = urlparse(url)
            out["last_request_path_hint"] = (p.path or "").rstrip("/") or None
        except Exception:
            out["last_request_path_hint"] = "unparsable_url"
    # ccxt algunas versiones guardan código HTTP fuera del exception
    for attr in ("last_http_response", "last_http_status", "lastResponseStatus"):
        raw = getattr(ex, attr, None)
        if raw is None:
            continue
        num = getattr(raw, "status", None)
        if isinstance(raw, dict) and "status" in raw:
            num = raw.get("status")
        out["last_http_status"] = num if isinstance(num, int) else out["last_http_status"]
    return out


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


_CLOCK_DRIFT_AUTO_RETRY_MS = 5000
_FETCH_BALANCE_ERR_MSG_CAP = 800


def get_testnet_auth_debug() -> dict[str, Any]:
    """
    Temporal: diagnóstico tiempo/recvWindow/ruta esperada sin exponer secrets.
    Ejecuta fetch_time y fetch_balance (sin órdenes).
    """
    _ensure_dotenv()

    out: dict[str, Any] = {
        "temporary": True,
        "note": "Endpoint temporal sólo diagnóstico.",
        "exchange_id": None,
        "sandbox_mode": False,
        "urls_api_safe": "unknown",
        "has_api_key": False,
        "has_secret": False,
        "api_key_prefix": None,
        "recv_window": None,
        "timestamp_ms": None,
        "server_time_ms": None,
        "fetch_time_error_type": None,
        "fetch_time_error_message": None,
        "time_diff_ms": None,
        "clock_adjust_auto_attempted": False,
        "clock_adjust_auto_reason": None,
        "fetch_balance_final_ok": False,
        "fetch_balance_error_type": None,
        "fetch_balance_error_message": None,
        "fetch_balance_after_adjust_ok": None,
        "fetch_balance_after_adjust_error_type": None,
        "fetch_balance_after_adjust_error_message": None,
        "route_hints": {},
        "signed_request_trace": {},
    }

    out["has_api_key"] = bool(_api_key())
    out["has_secret"] = bool(_api_secret())
    ak = _api_key()
    if ak:
        out["api_key_prefix"] = ak[:6] if len(ak) >= 6 else ak

    if not _ccxt_available():
        out["fetch_balance_error_type"] = "ccxt_missing"
        out["fetch_balance_error_message"] = "ccxt no instalado"
        return out

    if not is_testnet_enabled():
        out["fetch_balance_error_type"] = "disabled"
        out["fetch_balance_error_message"] = "BINANCE_TESTNET_ENABLED=false"
        return out

    if not is_testnet_configured():
        out["fetch_balance_error_type"] = "not_configured"
        out["fetch_balance_error_message"] = (
            "faltan BINANCE_TESTNET_API_KEY/BINANCE_TESTNET_API_SECRET"
        )
        return out

    ex_auth = _build_sandbox_exchange(with_credentials=True)
    out["sandbox_mode"] = _detect_sandbox_mode(ex_auth)
    out["exchange_id"] = getattr(ex_auth, "id", None)
    out["urls_api_safe"] = _classify_urls_api_safe(ex_auth)
    out["recv_window"] = _recv_window_option(ex_auth)
    out["route_hints"] = _urls_private_route_hint(ex_auth)

    millis = getattr(ex_auth, "milliseconds", None)
    out["timestamp_ms"] = int(millis()) if callable(millis) else int(time_mod.time() * 1000)

    try:
        out["server_time_ms"] = int(ex_auth.fetch_time())
    except Exception as e:
        out["fetch_time_error_type"] = type(e).__name__
        ft_err = _safe_error(e)
        out["fetch_time_error_message"] = ft_err[:_FETCH_BALANCE_ERR_MSG_CAP]

    if out["server_time_ms"] is not None:
        out["time_diff_ms"] = out["server_time_ms"] - out["timestamp_ms"]

    td = out["time_diff_ms"]
    clock_large = td is not None and abs(td) >= _CLOCK_DRIFT_AUTO_RETRY_MS

    def _try_balance(exc: Any) -> tuple[bool, str | None, str | None]:
        try:
            exc.fetch_balance()
            return True, None, None
        except Exception as e:
            msg = _safe_error(e)
            if len(msg) > _FETCH_BALANCE_ERR_MSG_CAP:
                msg = msg[:_FETCH_BALANCE_ERR_MSG_CAP]
            return False, type(e).__name__, msg

    ok, et, em = _try_balance(ex_auth)
    out["fetch_balance_final_ok"] = ok
    out["signed_request_trace"] = _exchange_signed_request_trace(ex_auth)
    if not ok:
        out["fetch_balance_error_type"] = et
        out["fetch_balance_error_message"] = em

    err_txt = em or ""
    clock_err_codes = "-1021" in err_txt or "-1022" in err_txt
    should_retry_clock = (not ok) and (clock_large or clock_err_codes)

    if should_retry_clock:
        out["clock_adjust_auto_attempted"] = True
        if clock_large and clock_err_codes:
            out["clock_adjust_auto_reason"] = "large_delta_and_timestamp_error_symbols"
        elif clock_large:
            out["clock_adjust_auto_reason"] = f"large_time_diff_ms(abs>={_CLOCK_DRIFT_AUTO_RETRY_MS})"
        else:
            out["clock_adjust_auto_reason"] = (
                "error_message_suggests_timestamp_or_recv_window"
            )

        ex_adj = _build_sandbox_exchange(
            with_credentials=True, adjust_for_time_difference=True
        )
        ltd = getattr(ex_adj, "load_time_difference", None)
        if callable(ltd):
            try:
                ltd()
            except Exception as le:
                prev = out["clock_adjust_auto_reason"]
                out["clock_adjust_auto_reason"] = (
                    f"{prev};load_time_difference={type(le).__name__}"
                )

        ok2, et2, em2 = _try_balance(ex_adj)
        out["fetch_balance_after_adjust_ok"] = ok2
        if not ok2:
            out["fetch_balance_after_adjust_error_type"] = et2
            out["fetch_balance_after_adjust_error_message"] = em2
        else:
            out["fetch_balance_after_adjust_error_type"] = None
            out["fetch_balance_after_adjust_error_message"] = None
        out["fetch_balance_final_ok"] = ok or ok2
        out["signed_request_trace"] = _exchange_signed_request_trace(ex_adj)

    return out


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


def _normalize_whitelisted_symbol(raw: str) -> str | None:
    s = (raw or "").strip().upper().replace(" ", "")
    if "/" not in s:
        return None
    base, quote = s.split("/", 1)
    if not base or not quote:
        return None
    norm = f"{base}/{quote}"
    return norm if norm in MARKET_ORDER_SYMBOL_WHITELIST else None


def _assert_exchange_is_sandbox(ex: Any, context: str) -> None:
    if _classify_urls_api_safe(ex) == "real":
        _log(f"{context}: rechazado — cliente apunta a producción")
        raise RuntimeError("sandbox_guard: exchange apunta a Binance real")


def _free_usdt_from_balances_payload(bal: dict[str, Any]) -> float | None:
    if not bal.get("ok"):
        return None
    for row in bal.get("balances") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("asset", "")).upper() == "USDT":
            try:
                return float(row.get("free") or 0)
            except (TypeError, ValueError):
                return None
    return 0.0


def _summarize_ccxt_order(sym: str, side: str, raw: dict[str, Any]) -> dict[str, Any]:
    oid = raw.get("id")
    status = raw.get("status")
    if isinstance(status, str):
        status_s = status
    else:
        status_s = str(status) if status is not None else None
    return {
        "symbol": sym,
        "side": side,
        "order_id": oid,
        "status": status_s,
        "filled": raw.get("filled"),
        "cost": raw.get("cost"),
        "average": raw.get("average"),
        "timestamp": raw.get("timestamp"),
    }


def place_testnet_market_order(
    symbol: str,
    side: str,
    quote_amount_usdt: float | None,
    *,
    max_quote_usdt: float = MAX_MARKET_ORDER_QUOTE_USDT,
) -> dict[str, Any]:
    """
    Orden market sólo testnet. Fase actual: BUY por monto en USDT (quoteOrderQty vía ccxt).
    SELL no implementado (rechazado).
    """
    _ensure_dotenv()
    out_err = (
        lambda e, code: {
            "ok": False,
            "error": e,
            "http_status": code,
            "order": None,
        }
    )

    side_l = (side or "").strip().lower()
    if side_l != "buy":
        return out_err("Sólo BUY en testnet en esta fase; SELL no disponible.", 400)

    if not _ccxt_available():
        return out_err("ccxt no instalado", 503)

    if not is_testnet_enabled():
        return out_err("BINANCE_TESTNET_ENABLED=false", 503)

    if not is_testnet_configured():
        return out_err("Testnet no configurado (API key/secret)", 503)

    sym = _normalize_whitelisted_symbol(symbol)
    if sym is None:
        return out_err(
            f"Símbolo no permitido; whitelist: {sorted(MARKET_ORDER_SYMBOL_WHITELIST)}",
            400,
        )

    if quote_amount_usdt is None:
        return out_err("quote_amount_usdt es obligatorio para BUY", 400)

    try:
        q_amt = float(quote_amount_usdt)
    except (TypeError, ValueError):
        return out_err("quote_amount_usdt inválido", 400)

    if not (q_amt == q_amt) or q_amt <= 0:
        return out_err("quote_amount_usdt debe ser > 0", 400)

    if q_amt < MIN_MARKET_ORDER_QUOTE_USDT:
        return out_err(f"Monto mínimo {MIN_MARKET_ORDER_QUOTE_USDT} USDT", 400)

    if q_amt > max_quote_usdt:
        return out_err(f"Monto máximo por orden {max_quote_usdt} USDT", 400)

    bal = get_testnet_balances()
    if not bal.get("ok"):
        return out_err(
            f"Lectura de balance requerida antes de operar: {bal.get('error')}",
            503,
        )

    usdt_free = _free_usdt_from_balances_payload(bal)
    if usdt_free is None:
        return out_err("No se pudo determinar USDT libre", 503)
    if usdt_free + 1e-9 < q_amt:
        return out_err(f"USDT libre insuficiente (libre≈{usdt_free:.8f}, pedido={q_amt})", 400)

    ex = get_testnet_exchange()
    if ex is None:
        return out_err("Exchange testnet no disponible", 503)

    try:
        _assert_exchange_is_sandbox(ex, "market_order")
    except RuntimeError as e:
        return out_err(str(e), 503)

    cost = q_amt
    ctp = getattr(ex, "cost_to_precision", None)
    if callable(ctp):
        try:
            cost = float(ctp(sym, cost))
        except Exception:
            cost = q_amt

    if cost <= 0 or cost > max_quote_usdt + 1e-9:
        return out_err("Monto tras precisión inválido", 400)

    _log(f"market_buy: symbol={sym} quote_usdt={cost}")
    try:
        raw = ex.create_market_buy_order_with_cost(sym, cost)
    except Exception as e:
        err = _safe_error(e)
        _log(f"market_buy falló {err}")
        return out_err(err, 502)

    if not isinstance(raw, dict):
        return out_err("Respuesta de orden inválida", 502)

    return {
        "ok": True,
        "error": None,
        "http_status": 200,
        "order": _summarize_ccxt_order(sym, "buy", raw),
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
