from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any, Literal

import requests

from services.market_data.types import PriceQuote
import logging

logger = logging.getLogger(__name__)


IOL_API_BASE = "https://api.invertironline.com"
IOL_TOKEN_URL = f"{IOL_API_BASE}/token"
IOL_COTIZACION_URL = f"{IOL_API_BASE}/api/bCBA/Titulos/{{ticker}}/Cotizacion"
IOL_OPCIONES_V2_URL = f"{IOL_API_BASE}/api/v2/bCBA/Titulos/{{ticker}}/Opciones"


class IolOptionsRawError(Exception):
    """Fallo al obtener opciones RAW desde IOL (mensaje apto para HTTP detail)."""

    def __init__(self, detail: str, status_code: int = 502, *, iol_resource_401: bool = False) -> None:
        self.detail = detail
        self.status_code = status_code
        self.iol_resource_401 = iol_resource_401
        super().__init__(detail)


@dataclass
class _IolCreds:
    username: str
    password: str


_creds: _IolCreds | None = None
_token: str | None = None
_token_expires_at_monotonic: float = 0.0

_iol_quote_cache: dict[str, PriceQuote] = {}
_iol_quote_negative_cache: set[str] = set()
_iol_quote_usage_stats: dict[str, int] = {"iol_cache_positive_hits": 0, "iol_cache_negative_hits": 0}


def reset_iol_quote_usage_stats() -> None:
    """Reinicia contadores de uso de caché IOL (p. ej. al inicio de un build CEDEAR)."""
    global _iol_quote_usage_stats
    _iol_quote_usage_stats = {"iol_cache_positive_hits": 0, "iol_cache_negative_hits": 0}


def clear_iol_negative_cache() -> None:
    global _iol_quote_negative_cache
    _iol_quote_negative_cache.clear()


def get_iol_quote_usage_stats() -> dict[str, int]:
    return dict(_iol_quote_usage_stats)


def _iol_usage_inc(key: str) -> None:
    _iol_quote_usage_stats[key] = int(_iol_quote_usage_stats.get(key, 0)) + 1


def configure_iol_credentials(username: str, password: str) -> None:
    """
    Configura credenciales IOL en memoria (no persistente).
    Invalida el token previo.
    """
    global _creds, _token, _token_expires_at_monotonic
    u = (username or "").strip()
    p = (password or "").strip()
    if not u or not p:
        _creds = None
        _token = None
        _token_expires_at_monotonic = 0.0
        _iol_quote_cache.clear()
        _iol_quote_negative_cache.clear()
        logger.info(
            "[IOL_CONFIG] enabled=%s username_present=%s password_present=%s client_id_present=%s client_secret_present=%s",
            is_iol_enabled(),
            bool(u),
            bool(p),
            False,
            False,
        )
        return
    _creds = _IolCreds(username=u, password=p)
    _token = None
    _token_expires_at_monotonic = 0.0
    _iol_quote_cache.clear()
    _iol_quote_negative_cache.clear()
    logger.info(
        "[IOL_CONFIG] enabled=%s username_present=%s password_present=%s client_id_present=%s client_secret_present=%s",
        is_iol_enabled(),
        bool(u),
        bool(p),
        False,
        False,
    )


def is_iol_enabled() -> bool:
    return _creds is not None and bool(_creds.username) and bool(_creds.password)


def get_iol_token() -> str | None:
    """
    Obtiene access_token de IOL (grant_type=password). Cachea en memoria hasta expirar.
    """
    global _token, _token_expires_at_monotonic
    if not is_iol_enabled():
        logger.info(
            "[IOL_AUTH] creds_configured=%s endpoint=%s action=no_request",
            False,
            IOL_TOKEN_URL,
        )
        return None

    now = time.monotonic()
    if _token and now < _token_expires_at_monotonic:
        return _token

    c = _creds
    if c is None:
        logger.info(
            "[IOL_AUTH] creds_configured=%s endpoint=%s action=no_request",
            False,
            IOL_TOKEN_URL,
        )
        return None

    try:
        # Form URL-encoded, tal como el endpoint /token espera en producción.
        data = {
            "grant_type": "password",
            "username": c.username,
            "password": c.password,
        }
        r = requests.post(IOL_TOKEN_URL, data=data, timeout=10)
        body_prefix = (r.text or "")[:500]
        json_keys: Any
        obj: Any
        try:
            obj = r.json()
            if isinstance(obj, dict):
                json_keys = list(obj.keys())
            else:
                json_keys = f"non_dict:{type(obj).__name__}"
        except ValueError:
            obj = None
            json_keys = "json_parse_failed"

        logger.info(
            "[IOL_AUTH] creds_configured=%s endpoint=%s http_status=%s json_keys=%s",
            True,
            IOL_TOKEN_URL,
            r.status_code,
            json_keys,
        )

        if not r.ok:
            logger.warning(
                "[IOL_AUTH] access_token_present=%s body_prefix=%r",
                False,
                body_prefix,
            )
            _token = None
            _token_expires_at_monotonic = 0.0
            return None

        if not isinstance(obj, dict):
            logger.warning(
                "[IOL_AUTH] access_token_present=%s body_prefix=%r",
                False,
                body_prefix,
            )
            _token = None
            _token_expires_at_monotonic = 0.0
            return None

        tok = obj.get("access_token")
        exp = obj.get("expires_in")
        has_token = isinstance(tok, str) and bool(tok.strip())
        logger.info("[IOL_AUTH] access_token_present=%s", has_token)

        if not has_token:
            _token = None
            _token_expires_at_monotonic = 0.0
            return None
        try:
            exp_s = float(exp)
        except (TypeError, ValueError):
            exp_s = 0.0
        # Margen de seguridad para evitar tokens al borde de expirar.
        exp_s = max(0.0, exp_s - 30.0)
        _token = tok.strip()
        _token_expires_at_monotonic = time.monotonic() + exp_s
        return _token
    except Exception as e:
        logger.warning(
            "[IOL_AUTH] creds_configured=%s endpoint=%s exception=%s detail=%s",
            True,
            IOL_TOKEN_URL,
            type(e).__name__,
            e,
        )
        _token = None
        _token_expires_at_monotonic = 0.0
        return None


def _map_iol_moneda(moneda: object) -> Literal["ARS", "USD"] | None:
    if moneda is None:
        return None
    s = str(moneda).strip()
    if not s:
        return None
    s0 = s.lower()
    if "peso" in s0:
        return "ARS"
    if "dolar" in s0 or "dólar" in s0:
        return "USD"
    return None


IolRamRead = PriceQuote | Literal["negative"] | None


def read_iol_quote_ram_only(ticker: str) -> IolRamRead:
    """
    Solo cachés en RAM (sin HTTP). PriceQuote si hay hit positivo; \"negative\" si está en caché de fallos;
    None si no hay entrada (hace falta red o ticker desconocido).
    """
    if not is_iol_enabled():
        return None
    t = (ticker or "").strip().upper()
    if not t:
        return None
    if t in _iol_quote_negative_cache:
        _iol_usage_inc("iol_cache_negative_hits")
        return "negative"
    hit = _iol_quote_cache.get(t)
    if hit is not None:
        _iol_usage_inc("iol_cache_positive_hits")
        return hit
    return None


def get_iol_quote(ticker: str) -> PriceQuote | None:
    """
    Retorna PriceQuote válido (precio > 0) si IOL está habilitado y responde; None en caso contrario.
    Caché en memoria por proceso: aciertos reutilizan quote; fallos reutilizan None sin HTTP.
    """
    t0 = time.perf_counter()

    def _iol_slow_quote_log(sym: str, status: str) -> None:
        ms = (time.perf_counter() - t0) * 1000.0
        if ms > 1500.0:
            print("[IOL_SLOW_QUOTE] ticker=%s ms=%s status=%s" % (sym, int(round(ms)), status), flush=True)

    if not is_iol_enabled():
        return None

    t = (ticker or "").strip().upper()
    if not t:
        return None

    ram = read_iol_quote_ram_only(t)
    if ram == "negative":
        return None
    if isinstance(ram, PriceQuote):
        return ram

    tok = get_iol_token()
    if not tok:
        return None

    try:
        url = IOL_COTIZACION_URL.format(ticker=t)
        headers = {"Authorization": f"Bearer {tok}"}
        r = requests.get(url, headers=headers, timeout=3)
        http_st = "http_%s" % getattr(r, "status_code", "?")
        if not r.ok:
            print("[IOL_QUOTE_MISS] ticker=%s http_status=%s" % (t, getattr(r, "status_code", None)))
            _iol_quote_negative_cache.add(t)
            _iol_slow_quote_log(t, http_st)
            return None
        obj: Any = r.json()
        if not isinstance(obj, dict):
            _iol_quote_negative_cache.add(t)
            _iol_slow_quote_log(t, http_st)
            return None
        moneda_raw = obj.get("moneda")
        cur = _map_iol_moneda(moneda_raw) or "ARS"
        raw_price = obj.get("ultimoPrecio")
        value: float | None
        try:
            value = float(raw_price)
        except (TypeError, ValueError):
            value = None
        if value is not None and (value != value or value <= 0):
            value = None
        if value is None:
            _iol_quote_negative_cache.add(t)
            _iol_slow_quote_log(t, http_st)
            return None
        q = PriceQuote(
            value=value,
            currency=cur,
            source="iol",
            as_of=datetime.now(timezone.utc),
            symbol_used=t,
            notes=f"moneda={moneda_raw!s}" if moneda_raw is not None else None,
        )
        _iol_quote_cache[t] = q
        _iol_slow_quote_log(t, "ok")
        return q
    except Exception:
        _iol_quote_negative_cache.add(t)
        _iol_slow_quote_log(t, "exception")
        return None


def get_iol_options_raw(symbol: str) -> Any:
    """
    GET /api/v2/bCBA/Titulos/{ticker}/Opciones — respuesta JSON sin transformar.
    Normalización de símbolo alineada con _normalize_iol_ticker (cedear_service).

    Si IOL responde 401 en este recurso pero el mismo token obtiene cotización 200,
    suele ser restricción de plan/API o path no habilitado. Ver scripts/debug_iol_options_raw.py.
    """
    from services.cedear_service import _normalize_iol_ticker

    received = (symbol or "").strip()
    normalized = _normalize_iol_ticker(symbol)

    if not is_iol_enabled():
        logger.warning("[IOL_OPTIONS_RAW] status=disabled symbol=%s normalized=%s", received, normalized)
        raise IolOptionsRawError("IOL no configurado (credenciales)", status_code=503)

    if not normalized:
        logger.warning("[IOL_OPTIONS_RAW] status=empty_symbol symbol=%s normalized=%s", received, normalized)
        raise IolOptionsRawError("Símbolo vacío o inválido", status_code=400)

    tok = get_iol_token()
    if not tok:
        logger.warning("[IOL_OPTIONS_RAW] status=token_failed symbol=%s normalized=%s", received, normalized)
        raise IolOptionsRawError("No se pudo obtener token IOL", status_code=502)

    headers = {"Authorization": f"Bearer {tok}"}
    options_url = IOL_OPCIONES_V2_URL.format(ticker=normalized)

    try:
        r = requests.get(options_url, headers=headers, timeout=15)
    except requests.RequestException as e:
        logger.warning(
            "[IOL_OPTIONS_RAW] status=request_error symbol=%s normalized=%s error=%s",
            received,
            normalized,
            e,
        )
        raise IolOptionsRawError(f"Error de red: {e}", status_code=502) from e

    if not r.ok:
        body_preview = (r.text or "")[:500]
        st = int(r.status_code)
        if st == 401:
            logger.warning(
                "[IOL_OPTIONS_RAW] options_status=401 symbol=%s normalized=%s",
                received,
                normalized,
            )
            raise IolOptionsRawError("", status_code=401, iol_resource_401=True)
        logger.warning(
            "[IOL_OPTIONS_RAW] status=http_error symbol=%s normalized=%s http_status=%s body_prefix=%r",
            received,
            normalized,
            r.status_code,
            body_preview,
        )
        out_st = st if 400 <= st < 600 else 502
        raise IolOptionsRawError(f"IOL respondió {r.status_code}: {body_preview}", status_code=out_st)

    try:
        data: Any = r.json()
    except ValueError as e:
        logger.warning(
            "[IOL_OPTIONS_RAW] status=invalid_json symbol=%s normalized=%s error=%s",
            received,
            normalized,
            e,
        )
        raise IolOptionsRawError("Respuesta IOL no es JSON válido", status_code=502) from e

    if isinstance(data, list):
        logger.info(
            "[IOL_OPTIONS_RAW] symbol=%s normalized=%s items=%s",
            received,
            normalized,
            len(data),
        )
        if data and isinstance(data[0], dict):
            logger.info("[IOL_OPTIONS_RAW] first_keys=%s", list(data[0].keys()))
    else:
        logger.info(
            "[IOL_OPTIONS_RAW] symbol=%s normalized=%s items=n/a (response not a list)",
            received,
            normalized,
        )

    return data
