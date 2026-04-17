"""
Precio último vía API Cocos Capital (búsqueda + snapshot) para símbolos CEDEAR.
Requiere JWT de app (Apikey / Bearer) provisto por el usuario; sin persistencia en disco.

Resolución de instrumento: solo tipo CEDEARS, subtipos BYMA ARS/USD válidos, match exacto de
short_ticker (sin heurísticas startswith si hay ambigüedad). Sin match claro → None (Yahoo).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import requests

COCOS_API_BASE = "https://api.cocos.capital/"
SEARCH_PATH = "api/v1/markets/tickers/search"
SNAPSHOT_TMPL = "api/v1/markets/tickers/{}?segment=C"
REQUEST_TIMEOUT_S = 18

# Tipo / subtipos alineados con pyCocos (InstrumentType / InstrumentSubType).
CEDEARS_TYPE = "CEDEARS"
CEDEAR_SUBTYPES_OK = frozenset({"NACIONALES_ARS", "NACIONALES_USD"})


class CocosAuthError(Exception):
    """401 / respuesta de autenticación inválida contra Cocos."""


def _headers(api_jwt: str) -> dict[str, str]:
    t = api_jwt.strip()
    return {
        "Apikey": t,
        "Authorization": f"Bearer {t}",
        "User-Agent": "Mozilla/5.0 (compatible; InvestmentRadar/1.0)",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _parse_price_from_snapshot_row(row: dict[str, Any]) -> float | None:
    for key in (
        "last",
        "last_price",
        "close",
        "previous_close",
        "regularMarketPrice",
        "ask",
        "bid",
    ):
        v = row.get(key)
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x > 0:
            return round(x, 6)
    return None


def _norm_ticker(s: str) -> str:
    return (s or "").strip().upper()


def _is_cedears_block(item: dict[str, Any]) -> bool:
    return _norm_ticker(str(item.get("instrument_type") or "")) == CEDEARS_TYPE


def _iter_cedear_market_cells(search_payload: list[Any]):
    """Solo celdas CEDEARS con subtype BYMA ARS o USD (cable)."""
    if not isinstance(search_payload, list):
        return
    for item in search_payload:
        if not isinstance(item, dict) or not _is_cedears_block(item):
            continue
        for subtype in item.get("instrument_subtypes") or []:
            if not isinstance(subtype, dict):
                continue
            sub = _norm_ticker(str(subtype.get("instrument_subtype") or ""))
            if sub not in CEDEAR_SUBTYPES_OK:
                continue
            for md in subtype.get("market_data") or []:
                if isinstance(md, dict):
                    yield sub, md


def _collect_exact_short_matches(
    search_payload: list[Any],
    *,
    want_short: str,
) -> list[tuple[str, str]]:
    """
    Devuelve lista de (instrument_code, short_ticker) con match exacto case-insensitive
    a want_short, solo filas CEDEARS + subtype válido.
    """
    want = _norm_ticker(want_short)
    if not want:
        return []
    out: list[tuple[str, str]] = []
    for _sub, md in _iter_cedear_market_cells(search_payload):
        st = _norm_ticker(str(md.get("short_ticker") or ""))
        ic = md.get("instrument_code")
        if not st or ic is None:
            continue
        if st != want:
            continue
        out.append((str(ic).strip(), st))
    return out


def _dedupe_codes(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for code, st in pairs:
        if code in seen:
            continue
        seen.add(code)
        deduped.append((code, st))
    return deduped


def _resolve_cedear_instrument(search_payload: list[Any], yahoo_style_symbol: str) -> tuple[str, str] | None:
    """
    Elige (instrument_code, short_ticker) para cotizar.

    1) Coincidencia exacta short_ticker == símbolo completo (ej. TSLA.BA si Cocos lo usa así).
    2) Si no hay ninguna: coincidencia exacta short_ticker == parte antes del primer '.'
       (ej. TSLAD, MELID) solo si hay exactamente un candidato CEDEARS válido con ese short.
    Si hay 0 o >1 instrument_code distintos para el mismo criterio, None.
    """
    sym = (yahoo_style_symbol or "").strip()
    if not sym:
        return None
    want_full = _norm_ticker(sym)

    # 1) Exacto al símbolo pedido (tal cual en el maestro)
    m1 = _dedupe_codes(_collect_exact_short_matches(search_payload, want_short=want_full))
    if len(m1) == 1:
        return m1[0]
    if len(m1) > 1:
        codes = {c for c, _ in m1}
        if len(codes) == 1:
            return m1[0]
        return None

    # 2) Exacto al "stem" (solo si hay un único candidato; evita TSLA vs TSLAD vs TSLAC a la vez)
    if "." not in sym:
        return None
    stem = _norm_ticker(sym.split(".", 1)[0])
    if not stem:
        return None
    m2 = _dedupe_codes(_collect_exact_short_matches(search_payload, want_short=stem))
    if len(m2) == 1:
        return m2[0]
    return None


def _snapshot_rows_for_short(rows: list[Any], *, resolved_short: str) -> list[dict[str, Any]]:
    want = _norm_ticker(resolved_short)
    picked: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _norm_ticker(str(row.get("short_ticker") or "")) != want:
            continue
        picked.append(row)
    return picked


def fetch_last_price_cocos(*, api_jwt: str, yahoo_style_symbol: str) -> float | None:
    """
    Devuelve último precio operable o None si no hay match / sin datos.
    Lanza CocosAuthError ante 401.
    """
    sym = (yahoo_style_symbol or "").strip()
    if not sym or not api_jwt.strip():
        return None
    base = (sym.split(".")[0] or "").strip()
    if len(base) < 1:
        return None

    h = _headers(api_jwt)
    url_search = f"{COCOS_API_BASE}{SEARCH_PATH}?q={quote(base)}"
    try:
        r = requests.get(url_search, headers=h, timeout=REQUEST_TIMEOUT_S)
    except requests.RequestException:
        return None
    if r.status_code == 401:
        raise CocosAuthError("Cocos rechazó el token (401).")
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None

    resolved = _resolve_cedear_instrument(data, sym)
    if resolved is None:
        return None
    instrument_code, resolved_short = resolved

    snap_url = f"{COCOS_API_BASE}{SNAPSHOT_TMPL.format(quote(instrument_code, safe=''))}"
    try:
        r2 = requests.get(snap_url, headers=h, timeout=REQUEST_TIMEOUT_S)
    except requests.RequestException:
        return None
    if r2.status_code == 401:
        raise CocosAuthError("Cocos rechazó el token (401).")
    if r2.status_code != 200:
        return None
    try:
        rows = r2.json()
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(rows, list) or not rows:
        return None

    exact_rows = _snapshot_rows_for_short(rows, resolved_short=resolved_short)
    if not exact_rows:
        return None

    for row in exact_rows:
        p = _parse_price_from_snapshot_row(row)
        if p is not None:
            return p
    return None
