"""
Lectura local de data/events_cache_usa.json (sin APIs externas).

El archivo lo genera tools/update_usa_events_cache.py; cada ticker es un dict
con fechas de earnings/dividendos y updated_at por fila.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "events_cache_usa.json"
_load_mtime: float | None = None
_load_data: dict[str, dict[str, Any]] | None = None

_TICKER_OK = re.compile(r"^[\^A-Z0-9.\-]{1,32}$")


def _read_cache_dict() -> dict[str, dict[str, Any]]:
    global _load_mtime, _load_data
    try:
        st = _CACHE_PATH.stat().st_mtime
    except FileNotFoundError:
        _load_mtime, _load_data = None, {}
        return {}
    if _load_data is not None and _load_mtime == st:
        return _load_data
    try:
        raw = _CACHE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        _load_mtime, _load_data = st, {}
        return {}
    if not raw:
        _load_mtime, _load_data = st, {}
        return {}
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        _load_mtime, _load_data = st, {}
        return {}
    if not isinstance(obj, dict):
        _load_mtime, _load_data = st, {}
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in obj.items():
        if isinstance(k, str) and isinstance(v, dict):
            kk = k.strip().upper()
            if kk:
                out[kk] = v
    _load_mtime, _load_data = st, out
    return out


def _parse_iso_date(s: Any) -> date | None:
    if s is None or not isinstance(s, str):
        return None
    t = s.strip()
    if len(t) >= 10:
        t = t[:10]
    try:
        return date.fromisoformat(t)
    except ValueError:
        return None


def _row_age_days(updated_at: Any) -> int | None:
    if not isinstance(updated_at, str) or not updated_at.strip():
        return None
    ts = updated_at.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - dt.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds() // 86400))


def get_events_for_ticker(ticker: str) -> dict[str, Any]:
    """
    Devuelve campos normalizados desde el cache local.

    No llama Yahoo ni recalcula el cache; sí recalcula deltas de días
    usando la fecha de hoy y las fechas ISO ya guardadas (solo presentación).
    """
    sym = (ticker or "").strip().upper()
    today = date.today()

    empty: dict[str, Any] = {
        "ok": True,
        "ticker": sym or None,
        "found": False,
        "skipped": None,
        "skip_reason": None,
        "cache_row_error": None,
        "fecha_ultimo_earnings": None,
        "fecha_proximo_earnings": None,
        "dias_desde_ultimo_earnings": None,
        "dias_hasta_proximo_earnings": None,
        "fecha_ultimo_dividendo": None,
        "fecha_ex_dividendo": None,
        "ultimo_dividendo": None,
        "fecha_proximo_dividendo_estimado": None,
        "dias_hasta_proximo_dividendo": None,
        "dividend_yield_pago_pct": None,
        "dividend_yield_anual_estimado_pct": None,
        "frecuencia_dividendos": None,
        "dias_promedio_entre_dividendos": None,
        "dividendos_estimados_12m": None,
        "flujo_dividendos_12m_por_accion": None,
        "earnings_en_7d": None,
        "earnings_en_30d": None,
        "updated_at": None,
        "cache_row_age_days": None,
        "cache_stale_warning": False,
        "evento_sensible": False,
        "evento_sensible_motivos": [],
        "has_eventos_en_cache": False,
    }

    if not sym or not _TICKER_OK.match(sym):
        return {**empty, "ok": False, "error": "invalid_ticker"}

    cache = _read_cache_dict()
    row = cache.get(sym)
    if row is None:
        return empty

    out = {**empty, "found": True}
    skipped = bool(row.get("skipped"))
    out["skipped"] = skipped
    if isinstance(row.get("reason"), str):
        out["skip_reason"] = row.get("reason")
    err = row.get("error")
    if isinstance(err, dict):
        out["cache_row_error"] = err
    elif err is not None:
        out["cache_row_error"] = {"detail": str(err)}

    u_at = row.get("updated_at")
    out["updated_at"] = str(u_at).strip() if isinstance(u_at, str) and u_at.strip() else None
    age = _row_age_days(out["updated_at"])
    out["cache_row_age_days"] = age
    out["cache_stale_warning"] = bool(age is not None and age > 7)

    def _num(key: str) -> float | int | None:
        v = row.get(key)
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return v
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _bool(key: str) -> bool | None:
        v = row.get(key)
        if isinstance(v, bool):
            return v
        return None

    fe_next = _parse_iso_date(row.get("fecha_proximo_earnings"))
    out["fecha_proximo_earnings"] = fe_next.isoformat() if fe_next else None
    if fe_next is not None:
        out["dias_hasta_proximo_earnings"] = int((fe_next - today).days)
        if fe_next < today:
            out["dias_desde_ultimo_earnings"] = int((today - fe_next).days)
    else:
        out["dias_hasta_proximo_earnings"] = None

    # El cache no guarda explícitamente "último earnings"; la fecha de calendario pasada
    # se interpreta solo como referencia de días transcurridos (misma clave fecha_proximo_*).
    out["fecha_ultimo_earnings"] = None

    fd_last = _parse_iso_date(row.get("fecha_ultimo_dividendo"))
    out["fecha_ultimo_dividendo"] = fd_last.isoformat() if fd_last else None
    out["fecha_ex_dividendo"] = None

    fd_next = _parse_iso_date(row.get("fecha_proximo_dividendo_estimado"))
    out["fecha_proximo_dividendo_estimado"] = fd_next.isoformat() if fd_next else None
    if fd_next is not None:
        out["dias_hasta_proximo_dividendo"] = int((fd_next - today).days)

    out["ultimo_dividendo"] = _num("ultimo_dividendo")
    if isinstance(out["ultimo_dividendo"], float):
        if out["ultimo_dividendo"] == int(out["ultimo_dividendo"]):
            out["ultimo_dividendo"] = int(out["ultimo_dividendo"])
    out["dividend_yield_pago_pct"] = _num("dividend_yield_pago_pct")
    out["dividend_yield_anual_estimado_pct"] = _num("dividend_yield_anual_estimado_pct")
    fv = row.get("frecuencia_dividendos")
    out["frecuencia_dividendos"] = str(fv).strip() if isinstance(fv, str) and fv.strip() else None
    dpe = _num("dias_promedio_entre_dividendos")
    out["dias_promedio_entre_dividendos"] = int(dpe) if dpe is not None and dpe == int(dpe) else dpe
    de12 = _num("dividendos_estimados_12m")
    out["dividendos_estimados_12m"] = int(de12) if de12 is not None and de12 == int(de12) else de12
    out["flujo_dividendos_12m_por_accion"] = _num("flujo_dividendos_12m_por_accion")
    out["earnings_en_7d"] = _bool("earnings_en_7d")
    out["earnings_en_30d"] = _bool("earnings_en_30d")

    motivos: list[str] = []
    d_earn = out.get("dias_hasta_proximo_earnings")
    if isinstance(d_earn, int):
        if 0 <= d_earn <= 7:
            motivos.append("earnings_proximo_7d")
        if -3 <= d_earn <= -1:
            motivos.append("earnings_fecha_cache_reciente_pasada")
    if fd_last is not None:
        dd = (today - fd_last).days
        if 0 <= dd <= 3:
            motivos.append("dividendo_reciente_3d")

    out["evento_sensible_motivos"] = motivos
    out["evento_sensible"] = len(motivos) > 0

    if skipped or out.get("cache_row_error") is not None:
        out["has_eventos_en_cache"] = True
    else:
        out["has_eventos_en_cache"] = bool(
            fe_next or fd_last or fd_next or out.get("ultimo_dividendo") is not None
        )

    return out
