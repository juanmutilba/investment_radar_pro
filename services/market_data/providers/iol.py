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
        return None

    now = time.monotonic()
    if _token and now < _token_expires_at_monotonic:
        return _token

    c = _creds
    if c is None:
        return None

    try:
        # Form URL-encoded, tal como el endpoint /token espera en producción.
        data = {
            "grant_type": "password",
            "username": c.username,
            "password": c.password,
        }
        r = requests.post(IOL_TOKEN_URL, data=data, timeout=10)
        if not r.ok:
            _token = None
            _token_expires_at_monotonic = 0.0
            return None
        obj: Any = r.json()
        if not isinstance(obj, dict):
            return None
        tok = obj.get("access_token")
        exp = obj.get("expires_in")
        if not isinstance(tok, str) or not tok.strip():
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
    except Exception:
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
        if not r.ok:
            print("[IOL_QUOTE_MISS] ticker=%s http_status=%s" % (t, getattr(r, "status_code", None)))
            _iol_quote_negative_cache.add(t)
            return None
        obj: Any = r.json()
        if not isinstance(obj, dict):
            _iol_quote_negative_cache.add(t)
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
        return q
    except Exception:
        _iol_quote_negative_cache.add(t)
        return None

