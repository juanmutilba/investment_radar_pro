"""
Binance Spot Testnet (capa separada): lectura + órdenes market BUY / SELL acotadas (testnet).
Credenciales dedicadas: BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_API_SECRET, BINANCE_TESTNET_ENABLED.
No usa BINANCE_API_KEY / BINANCE_API_SECRET (cuenta real).
"""
from __future__ import annotations

import json
import math
import os
import time as time_mod
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

_LOG_PREFIX = "[CRYPTO_TESTNET]"
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_ORDERS_JSON = Path(__file__).resolve().parents[2] / "data" / "crypto_testnet_orders.json"
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


def _whitelist_usdt_pair_for_asset(asset: str) -> str | None:
    au = (asset or "").strip().upper()
    if not au:
        return None
    cand = f"{au}/USDT"
    return cand if cand in MARKET_ORDER_SYMBOL_WHITELIST else None


def get_testnet_positions() -> dict[str, Any]:
    """
    Posiciones spot leídas en vivo desde Binance Spot Testnet (balances + últimos precios).
    USDT va en cash_usdt (efectivo estable), no en la lista positions.
    """
    _ensure_dotenv()
    updated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    def _fail(error: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": error,
            "cash_usdt": 0.0,
            "positions": [],
            "total_value_usdt": 0.0,
            "updated_at": updated_at,
        }

    if not _ccxt_available():
        return _fail("ccxt no instalado")

    if not is_testnet_enabled():
        return _fail("BINANCE_TESTNET_ENABLED=false")

    if not is_testnet_configured():
        return _fail("Testnet no configurado (API key/secret)")

    ex = get_testnet_exchange()
    if ex is None:
        return _fail("Exchange testnet no disponible")

    try:
        _assert_exchange_is_sandbox(ex, "positions")
    except RuntimeError as e:
        return _fail(str(e))

    bal_payload = get_testnet_balances()
    if not bal_payload.get("ok"):
        return _fail(str(bal_payload.get("error") or "balance_error"))

    prices: dict[str, float | None] = {}
    for sym in sorted(MARKET_ORDER_SYMBOL_WHITELIST):
        try:
            tk = ex.fetch_ticker(sym)
            if not isinstance(tk, dict):
                prices[sym] = None
                continue
            raw = tk.get("last") or tk.get("bid") or tk.get("close")
            px = _safe_ccxt_float(raw)
            prices[sym] = px if px is not None and px > 0 else None
        except Exception as e:
            _log(f"positions: ticker {sym} falló {_safe_error(e)}")
            prices[sym] = None

    cash_usdt = 0.0
    positions: list[dict[str, Any]] = []

    for row in bal_payload.get("balances") or []:
        if not isinstance(row, dict):
            continue
        asset_raw = row.get("asset")
        if not isinstance(asset_raw, str):
            continue
        asset = asset_raw.strip().upper()
        if not asset:
            continue

        free = _safe_ccxt_float(row.get("free"))
        used = _safe_ccxt_float(row.get("used"))
        total = _safe_ccxt_float(row.get("total"))
        if free is None:
            free = 0.0
        if used is None:
            used = 0.0
        if total is None:
            total = free + used

        if free + used <= 0:
            continue

        if asset == "USDT":
            cash_usdt = total
            continue

        sym = _whitelist_usdt_pair_for_asset(asset)
        last_px = prices.get(sym) if sym else None

        value_usdt: float | None = None
        if last_px is not None:
            value_usdt = total * last_px
            if value_usdt is not None and (math.isnan(value_usdt) or math.isinf(value_usdt)):
                value_usdt = None

        positions.append(
            {
                "asset": asset,
                "symbol": sym,
                "free": free,
                "used": used,
                "total": total,
                "last_price_usdt": last_px,
                "value_usdt": value_usdt,
                "source": "binance_testnet",
            }
        )

    positions.sort(key=lambda r: (-float(r.get("total") or 0), str(r.get("asset") or "")))

    total_val = cash_usdt
    for p in positions:
        v = p.get("value_usdt")
        if isinstance(v, (int, float)) and not math.isnan(v) and not math.isinf(v):
            total_val += float(v)

    _log(f"positions: OK cash_usdt≈{cash_usdt} rows={len(positions)}")
    return {
        "ok": True,
        "error": None,
        "cash_usdt": cash_usdt,
        "positions": positions,
        "total_value_usdt": total_val,
        "updated_at": updated_at,
    }


def _open_order_row_from_ccxt(raw: dict[str, Any], fallback_symbol: str) -> dict[str, Any]:
    """Fila normalizada para órdenes abiertas ccxt (spot testnet)."""
    sym_r = raw.get("symbol")
    if isinstance(sym_r, str) and sym_r.strip():
        out_sym = sym_r.strip()
    else:
        out_sym = fallback_symbol

    oid = raw.get("id")
    if oid is None:
        oid_out: str | int | float | None = None
    elif isinstance(oid, (str, int, float)):
        oid_out = oid
    else:
        oid_out = str(oid)

    side = raw.get("side")
    side_s = str(side).lower() if side is not None else None

    typ = raw.get("type")
    type_s = str(typ).lower() if typ is not None else None

    st = raw.get("status")
    status_s = str(st).lower() if st is not None else "open"

    return {
        "symbol": out_sym,
        "order_id": oid_out,
        "side": side_s,
        "type": type_s,
        "status": status_s,
        "price": _safe_ccxt_float(raw.get("price")),
        "amount": _safe_ccxt_float(raw.get("amount")),
        "filled": _safe_ccxt_float(raw.get("filled")),
        "remaining": _safe_ccxt_float(raw.get("remaining")),
        "cost": _safe_ccxt_float(raw.get("cost")),
        "timestamp": _safe_ccxt_float(raw.get("timestamp")),
    }


def get_testnet_open_orders(symbol: str | None = None) -> dict[str, Any]:
    """
    Órdenes abiertas spot desde Binance Testnet (solo lectura; no persiste JSON).
    Si symbol es None, consulta todos los pares en MARKET_ORDER_SYMBOL_WHITELIST.
    """
    _ensure_dotenv()
    updated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    def _fail(msg: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": msg,
            "orders": [],
            "total": 0,
            "updated_at": updated_at,
        }

    if not _ccxt_available():
        return _fail("ccxt no instalado")

    if not is_testnet_enabled():
        return _fail("BINANCE_TESTNET_ENABLED=false")

    if not is_testnet_configured():
        return _fail("Testnet no configurado (API key/secret)")

    ex = get_testnet_exchange()
    if ex is None:
        return _fail("Exchange testnet no disponible")

    try:
        _assert_exchange_is_sandbox(ex, "open_orders")
    except RuntimeError as e:
        return _fail(str(e))

    sym_raw = (symbol or "").strip() or None
    if sym_raw:
        sym_norm = _normalize_whitelisted_symbol(sym_raw)
        if sym_norm is None:
            return _fail(
                f"Símbolo no permitido; whitelist: {sorted(MARKET_ORDER_SYMBOL_WHITELIST)}"
            )
        symbols_to_query = [sym_norm]
    else:
        symbols_to_query = sorted(MARKET_ORDER_SYMBOL_WHITELIST)

    combined: list[dict[str, Any]] = []
    for sym in symbols_to_query:
        try:
            raw_list = ex.fetch_open_orders(sym)
        except Exception as e:
            err = _safe_error(e)
            _log(f"open_orders {sym} falló {err}")
            return _fail(f"No se pudieron leer órdenes abiertas ({sym}): {err}")
        if not isinstance(raw_list, list):
            return _fail(f"Respuesta inválida de órdenes abiertas ({sym})")
        for item in raw_list:
            if isinstance(item, dict):
                combined.append(_open_order_row_from_ccxt(item, sym))

    def _ts_key(row: dict[str, Any]) -> float:
        t = row.get("timestamp")
        if isinstance(t, (int, float)) and not math.isnan(float(t)) and not math.isinf(float(t)):
            return float(t)
        return 0.0

    combined.sort(key=lambda r: -_ts_key(r))

    _log(f"open_orders: OK total={len(combined)}")
    return {
        "ok": True,
        "error": None,
        "orders": combined,
        "total": len(combined),
        "updated_at": updated_at,
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


def _free_asset_from_balances_payload(bal: dict[str, Any], asset: str) -> float | None:
    """Saldo libre de un activo (spot testnet desde get_testnet_balances)."""
    if not bal.get("ok"):
        return None
    au = (asset or "").strip().upper()
    if not au:
        return None
    for row in bal.get("balances") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("asset", "")).upper() == au:
            try:
                return float(row.get("free") or 0)
            except (TypeError, ValueError):
                return None
    return 0.0


def _base_asset_from_pair(sym: str) -> str | None:
    parts = sym.split("/", 1)
    if len(parts) != 2 or not parts[0].strip():
        return None
    return parts[0].strip().upper()


def _safe_ccxt_float(v: Any) -> float | None:
    """Evita NaN/inf en respuestas JSON y valores no numéricos."""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def _summarize_ccxt_order(sym: str, side: str, raw: dict[str, Any]) -> dict[str, Any]:
    oid = raw.get("id")
    status = raw.get("status")
    if isinstance(status, str):
        status_s = status
    else:
        status_s = str(status) if status is not None else None

    ts_out = _safe_ccxt_float(raw.get("timestamp"))

    if oid is None:
        oid_out: str | int | float | None = None
    elif isinstance(oid, (str, int, float)):
        oid_out = oid
    else:
        oid_out = str(oid)

    return {
        "symbol": sym,
        "side": side,
        "order_id": oid_out,
        "status": status_s,
        "filled": _safe_ccxt_float(raw.get("filled")),
        "cost": _safe_ccxt_float(raw.get("cost")),
        "average": _safe_ccxt_float(raw.get("average")),
        "timestamp": ts_out,
    }


def _http_status_for_exchange_failure(exc: BaseException) -> int:
    """Errores típicos de reglas Binance/ccxt → 400; resto → 502."""
    msg = _safe_error(exc).lower()
    markers = (
        "insufficient balance",
        "insufficient funds",
        "-1013",
        "-1111",
        "-2010",
        "-1021",
        "-2019",
        "filter failure",
        "minimum",
        "notional",
        "precision",
        "lot size",
        "invalid quantity",
        "quote_order_qty",
        "market lot",
        "account has insufficient balance",
    )
    if any(m in msg for m in markers):
        return 400
    name = type(exc).__name__.lower()
    if name in ("insufficientfunds", "invalidorder", "badrequest", "argumentsrequired"):
        return 400
    return 502


_ORDER_HISTORY_LIMIT_CAP = 500


def _load_testnet_orders_json() -> list[dict[str, Any]]:
    if not _ORDERS_JSON.is_file():
        return []
    try:
        raw = json.loads(_ORDERS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    return []


def testnet_symbol_in_local_order_cooldown(symbol: str, cooldown_minutes: int) -> bool:
    """
    True si en el historial local de órdenes testnet hay una orden reciente para el mismo par.
    Usado sólo como filtro heurístico (no incluye órdenes no persistidas por esta app).
    """
    from datetime import timedelta, timezone

    if cooldown_minutes <= 0:
        return False
    sym_norm = _normalize_whitelisted_symbol(symbol)
    if sym_norm is None:
        return False
    want = sym_norm.upper().replace(" ", "")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=int(cooldown_minutes))
    for row in reversed(_load_testnet_orders_json()):
        rs = str(row.get("symbol") or "").strip().upper().replace(" ", "")
        if rs != want:
            continue
        raw = str(row.get("created_at") or "").strip()
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        if dt >= cutoff:
            return True
    return False


def _atomic_write_testnet_orders(rows: list[dict[str, Any]]) -> None:
    _ORDERS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ORDERS_JSON.with_suffix(".tmp_write")
    data = json.dumps(rows, ensure_ascii=False, indent=2)
    tmp.write_text(data + ("\n" if not data.endswith("\n") else ""), encoding="utf-8")
    tmp.replace(_ORDERS_JSON)


def _normalize_raw_status_for_store(raw_status: Any) -> str | None:
    if raw_status is None:
        return None
    if isinstance(raw_status, str):
        return raw_status[:160]
    if isinstance(raw_status, (int, float, bool)):
        return str(raw_status)[:160]
    return str(raw_status)[:160]


def _append_manual_testnet_order_record(summary: dict[str, Any], raw_ccxt_order: dict[str, Any]) -> None:
    """Persiste sólo campos permitidos (sin secrets)."""
    row: dict[str, Any] = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "symbol": summary.get("symbol"),
        "side": summary.get("side"),
        "order_id": summary.get("order_id"),
        "status": summary.get("status"),
        "filled": summary.get("filled"),
        "cost": summary.get("cost"),
        "average": summary.get("average"),
        "timestamp_exchange": summary.get("timestamp"),
        "raw_status": _normalize_raw_status_for_store(raw_ccxt_order.get("status")),
        "source": "manual_testnet",
    }

    prev = _load_testnet_orders_json()
    prev.append(row)
    _atomic_write_testnet_orders(prev)


def get_testnet_order_history(limit: int = 50) -> dict[str, Any]:
    """
    Últimas órdenes persistidas (más reciente primero) + total acumulado en JSON.
    """
    if limit < 1:
        limit = 1
    limit = min(limit, _ORDER_HISTORY_LIMIT_CAP)
    all_rows = _load_testnet_orders_json()
    total = len(all_rows)
    tail = all_rows[-limit:] if len(all_rows) > limit else all_rows[:]
    return {"orders": list(reversed(tail)), "total": total}


def place_testnet_market_order(
    symbol: str,
    side: str,
    quote_amount_usdt: float | None = None,
    *,
    amount_base: float | None = None,
    sell_quote_amount_usdt: float | None = None,
    max_quote_usdt: float = MAX_MARKET_ORDER_QUOTE_USDT,
) -> dict[str, Any]:
    """
    Orden market sólo testnet (sandbox).
    BUY: monto quote en USDT (create_market_buy_order_with_cost).
    SELL: amount_base explícito, o sell_quote_amount_usdt (estima base vía ticker last).
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
    if side_l not in ("buy", "sell"):
        return out_err("side debe ser buy o sell", 400)

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

    bal = get_testnet_balances()
    if not bal.get("ok"):
        return out_err(
            f"Lectura de balance requerida antes de operar: {bal.get('error')}",
            503,
        )

    ex = get_testnet_exchange()
    if ex is None:
        return out_err("Exchange testnet no disponible", 503)

    try:
        _assert_exchange_is_sandbox(ex, "market_order")
    except RuntimeError as e:
        return out_err(str(e), 503)

    raw: dict[str, Any]

    if side_l == "buy":
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

        usdt_free = _free_usdt_from_balances_payload(bal)
        if usdt_free is None:
            return out_err("No se pudo determinar USDT libre", 503)
        if usdt_free + 1e-9 < q_amt:
            return out_err(f"USDT libre insuficiente (libre≈{usdt_free:.8f}, pedido={q_amt})", 400)

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
            code = _http_status_for_exchange_failure(e)
            _log(f"market_buy falló {err}")
            return out_err(err, code)

        if not isinstance(raw, dict):
            return out_err("Respuesta de orden inválida", 502)

        summary = _summarize_ccxt_order(sym, "buy", raw)

    else:
        base_asset = _base_asset_from_pair(sym)
        if base_asset is None:
            return out_err("No se pudo determinar activo base del par", 400)

        base_free = _free_asset_from_balances_payload(bal, base_asset)
        if base_free is None:
            return out_err(f"No se pudo determinar saldo libre de {base_asset}", 503)

        has_base = amount_base is not None
        has_sq = sell_quote_amount_usdt is not None
        if has_base and has_sq:
            return out_err("SELL: usá cantidad exacta O monto en USDT, no ambos", 400)
        if not has_base and not has_sq:
            return out_err(
                "SELL: indicá cantidad en el activo o monto aproximado a vender en USDT",
                400,
            )

        amt_in: float

        if has_sq:
            try:
                sq = float(sell_quote_amount_usdt)
            except (TypeError, ValueError):
                return out_err("sell_quote_amount_usdt inválido", 400)

            if not (sq == sq) or sq <= 0:
                return out_err("sell_quote_amount_usdt debe ser > 0", 400)

            if sq < MIN_MARKET_ORDER_QUOTE_USDT:
                return out_err(
                    f"Monto mínimo a vender en USDT: {MIN_MARKET_ORDER_QUOTE_USDT}",
                    400,
                )

            if sq > max_quote_usdt:
                return out_err(f"Monto máximo por orden {max_quote_usdt} USDT (lado venta)", 400)

            try:
                tk = ex.fetch_ticker(sym)
            except Exception as e:
                err = _safe_error(e)
                code = _http_status_for_exchange_failure(e)
                return out_err(f"No se pudo leer precio testnet para vender: {err}", code)

            if not isinstance(tk, dict):
                return out_err("Ticker inválido para estimar venta", 502)

            px_raw = tk.get("last") or tk.get("bid") or tk.get("close")
            try:
                px = float(px_raw)
            except (TypeError, ValueError):
                px = 0.0

            if not (px == px) or px <= 0:
                return out_err("Precio del par no disponible para estimar la venta en USDT", 400)

            amt_raw = sq / px
            if amt_raw > base_free + 1e-12:
                return out_err(
                    f"{base_asset} libre insuficiente para vender ~{sq} USDT "
                    f"(libre≈{base_free:.12f}, necesario≈{amt_raw:.12f})",
                    400,
                )

            amt_in = amt_raw
        else:
            try:
                amt_in = float(amount_base)
            except (TypeError, ValueError):
                return out_err("amount_base inválido", 400)

            if not (amt_in == amt_in) or amt_in <= 0:
                return out_err("amount_base debe ser > 0", 400)

        amt = amt_in
        atp = getattr(ex, "amount_to_precision", None)
        if callable(atp):
            try:
                amt = float(atp(sym, amt_in))
            except Exception:
                amt = amt_in

        if amt <= 0:
            return out_err("Cantidad tras amount_to_precision inválida para SELL", 400)

        if base_free + 1e-12 < amt:
            return out_err(
                f"{base_asset} libre insuficiente (libre≈{base_free:.12f}, pedido≈{amt})",
                400,
            )

        _log(f"market_sell: symbol={sym} amount_base={amt}")
        try:
            raw = ex.create_market_sell_order(sym, amt)
        except Exception as e:
            err = _safe_error(e)
            code = _http_status_for_exchange_failure(e)
            _log(f"market_sell falló {err}")
            return out_err(err, code)

        if not isinstance(raw, dict):
            return out_err("Respuesta de orden inválida", 502)

        summary = _summarize_ccxt_order(sym, "sell", raw)

    try:
        _append_manual_testnet_order_record(summary, raw)
    except Exception as e:
        _log(f"orders_json: fallo persistencia (orden ya ejecutada en exchange): {_safe_error(e)}")

    return {
        "ok": True,
        "error": None,
        "http_status": 200,
        "order": summary,
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
