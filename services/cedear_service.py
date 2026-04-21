from __future__ import annotations

import logging
import math
import os
import sys
import time
from datetime import date
from typing import Any, Literal

import yfinance as yf
from pydantic import BaseModel, ConfigDict, Field

from data.cedear_mapping import CEDEAR_MAPPINGS
from services import latest_export

logger = logging.getLogger(__name__)

RatioEstado = Literal["ok", "pendiente_validar", "revisar"]
ModUsa = Literal["SI", "NO"]
FuenteCedearLocal = Literal["Yahoo"]
_RATIO_STALE_DAYS = 180

# Tickers para marcar focus=1 en líneas [CEDEAR_AUDIT] (grep: focus=1).
_CEDEAR_AUDIT_FOCUS = frozenset(
    {
        "ABT",
        "ADI",
        "ADP",
        "AMAT",
        "AMGN",
        "BMY",
        "CAH",
        "CL",
        "DIS",
        "GOOGL",
        "AAL",
        "BP",
        "ADBE",
        "ABNB",
        "AVGO",
        "AZN",
    }
)


def _derive_ratio_audit(fecha_raw: str | None) -> tuple[RatioEstado, int | None]:
    """
    Auditoría de frescura del ratio según fecha_validacion_ratio (ISO YYYY-MM-DD).
    Sin fecha / vacío → pendiente_validar. Fecha inválida → pendiente_validar.
    Fecha futura → revisar (dato sospechoso). >180 días → revisar.
    """
    if fecha_raw is None or not str(fecha_raw).strip():
        return "pendiente_validar", None
    s = str(fecha_raw).strip()
    for sep in ("T", " "):
        if sep in s:
            s = s.split(sep, 1)[0]
    try:
        validated = date.fromisoformat(s)
    except ValueError:
        return "pendiente_validar", None
    today = date.today()
    delta = (today - validated).days
    if delta < 0:
        return "revisar", None
    if delta > _RATIO_STALE_DAYS:
        return "revisar", delta
    return "ok", delta


class CedearRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ticker_usa: str
    ticker_cedear_ars: str
    ticker_cedear_usd: str
    ratio: float = Field(
        ...,
        description="cedears_por_accion_usa del maestro JSON (sin inferir desde precios).",
    )
    fuente_ratio: str | None = Field(
        None,
        description="Cita o referencia al ratio en cedear_mappings.json.",
    )
    fecha_validacion_ratio: str | None = Field(
        None,
        description="Fecha ISO de validación del ratio en el maestro, si existe.",
    )
    estado_ratio: RatioEstado = Field(
        ...,
        description="ok | pendiente_validar | revisar (según fecha y antigüedad).",
    )
    dias_desde_validacion: int | None = Field(
        None,
        description="Días desde fecha_validacion_ratio; null si no aplica.",
    )
    precio_cedear_ars: float | None
    precio_cedear_usd: float | None
    ccl_implicito: float | None = Field(
        None,
        description="precio_cedear_ars / precio línea CCL (USD por CEDEAR en cable).",
    )
    precio_usa_real: float | None
    precio_implicito_usd: float | None = Field(
        None,
        description="precio línea CCL * cedears_por_accion_usa (USD implícitos por 1 acción USA).",
    )
    gap_pct: float | None = Field(
        None,
        description="(precio_implicito_usd / precio_usa_real - 1) * 100",
    )
    total_score: float | None = Field(None, serialization_alias="TotalScore")
    signal_state: str | None = Field(None, serialization_alias="SignalState")
    mod_usa: ModUsa = Field(
        ...,
        description='SI: precio/score/señal desde el radar USA; NO: precio USA vía Yahoo (sin radar).',
    )
    fuente_cedear: FuenteCedearLocal = Field(
        ...,
        description="Precios locales CEDEAR (ARS y cable) vía Yahoo.",
    )
    cobertura_usa_mensaje: str | None = Field(
        None,
        description="null si hay fila USA y precio en export; texto si falta radar o precio USA.",
    )
    pricing_cedear_local_mensaje: str | None = Field(
        None,
        description="null si ARS/CCL Yahoo e implícitos locales completos; resume campos faltantes.",
    )


def _cobertura_usa_mensaje(row: dict[str, Any] | None, precio_usa: float | None) -> str | None:
    if row is None:
        return "Falta en módulo Acciones USA"
    if precio_usa is None or precio_usa <= 0:
        return "Sin precio USA en export radar"
    return None


def _pricing_cedear_local_mensaje(
    p_ars: float | None,
    p_ccl: float | None,
    ccl_impl: float | None,
    precio_impl: float | None,
) -> str | None:
    missing: list[str] = []
    if p_ars is None:
        missing.append("precio_cedear_ars")
    if p_ccl is None:
        missing.append("precio_cedear_usd")
    elif p_ccl <= 0:
        missing.append("precio_cedear_usd")
    if ccl_impl is None:
        missing.append("ccl_implicito")
    if precio_impl is None:
        missing.append("precio_implicito_usd")
    if not missing:
        return None
    return "Pricing local CEDEAR incompleto: " + ",".join(missing)


def _radar_get(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k not in row:
            continue
        v = row[k]
        if v is None:
            continue
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            continue
        return v
    return None


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def _fetch_last_price(symbol: str) -> float | None:
    """
    Ultimo precio operable via Yahoo (fast_info o ultimo cierre corto).
    No recalcula tecnica ni fundamentales; solo spot para CEDEAR.
    """
    sym = (symbol or "").strip()
    if not sym:
        return None
    try:
        asset = yf.Ticker(sym)
        fi = getattr(asset, "fast_info", None)
        raw: Any = None
        if isinstance(fi, dict):
            raw = fi.get("last_price") or fi.get("lastPrice") or fi.get("regularMarketPrice")
        if raw is None and fi is not None:
            try:
                raw = fi["last_price"]  # type: ignore[index]
            except Exception:
                raw = None
        p = _to_float(raw)
        if p is not None and p > 0:
            return round(p, 6)

        hist = asset.history(period="5d", auto_adjust=False, actions=False, repair=False)
        if hist is not None and not hist.empty and "Close" in hist.columns:
            close = _to_float(hist["Close"].iloc[-1])
            if close is not None and close > 0:
                return round(close, 6)
    except Exception:
        return None
    return None


def _yahoo_spot_cached(symbol: str, cache: dict[str, float | None], stats: dict[str, int]) -> float | None:
    """
    Mismo contrato que _fetch_last_price, pero deduplica por símbolo dentro del mismo armado
    de filas CEDEAR (un request GET /cedears).

    Un precio None (sin datos / fallo) queda guardado en cache igual que un número: no se
    reconsulta Yahoo para el mismo símbolo en el resto de ese armado.
    """
    sym = (symbol or "").strip()
    if not sym:
        return None
    key = sym.upper()
    if key in cache:
        stats["yahoo_cache_hits"] += 1
        return cache[key]
    stats["yahoo_queries"] += 1
    p: float | None = None
    try:
        p = _fetch_last_price(sym)
    finally:
        cache[key] = p
    return p


def _cedear_debug_line(
    ticker_usa: str,
    sym_ars: str,
    sym_ccl: str,
    cedears_por_accion: float,
    p_ars: float | None,
    p_ccl: float | None,
) -> None:
    """
    Diagnóstico temporal: setear CEDEAR_DEBUG=1 en el entorno del proceso API.
    Muestra por stderr símbolos y precios usados por fila (no dejar en producción ruidosa).
    """
    flag = os.environ.get("CEDEAR_DEBUG", "").strip().lower()
    if flag not in ("1", "true", "yes"):
        return
    print(
        "[CEDEAR_DEBUG] "
        f"usa={ticker_usa!r} ticker_cedear_ars={sym_ars!r} ticker_cedear_ccl={sym_ccl!r} "
        f"cedears_por_accion_usa={cedears_por_accion} precio_ars={p_ars!r} precio_ccl={p_ccl!r}",
        file=sys.stderr,
        flush=True,
    )


def _cedear_audit_enabled() -> bool:
    return os.environ.get("CEDEAR_AUDIT", "").strip().lower() in ("1", "true", "yes")


def _cedear_audit_tickers_filter() -> frozenset[str] | None:
    """
    Si CEDEAR_AUDIT_TICKERS está definido y no vacío, solo esos ticker_usa (coma-separados)
    generan línea [CEDEAR_AUDIT]. Si no está definido, con CEDEAR_AUDIT=1 se auditan todos.
    """
    raw = os.environ.get("CEDEAR_AUDIT_TICKERS", "")
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    if not parts:
        return None
    return frozenset(parts)


def _cedear_audit_log(
    *,
    ticker_usa: str,
    sym_ars: str,
    sym_ccl: str,
    usa_hit: bool,
    mod_usa: ModUsa,
    p_ars: float | None,
    p_ccl: float | None,
    ccl_impl: float | None,
    precio_impl: float | None,
    precio_usa: float | None,
    ratio: float,
) -> None:
    """
    Una línea INFO por fila, prefijo fijo [CEDEAR_AUDIT] para grep.
    Activar: CEDEAR_AUDIT=1. Opcional: CEDEAR_AUDIT_TICKERS=ABT,AZN (subconjunto).
    No altera precios ni ramas de cálculo.
    """
    if not _cedear_audit_enabled():
        return
    filt = _cedear_audit_tickers_filter()
    u = ticker_usa.strip().upper()
    if filt is not None and u not in filt:
        return

    y_ars = "ok" if p_ars is not None else "miss"
    y_ccl = "ok" if p_ccl is not None else "miss"
    # precio_cedear_usd en API = spot Yahoo línea CCL (mismo valor que p_ccl).
    cedear_usd_line = "ok" if p_ccl is not None else "miss"
    ccl_i = "ok" if ccl_impl is not None else "miss"
    p_impl = "ok" if precio_impl is not None else "miss"
    usa_row = "hit" if usa_hit else "miss"
    usa_price = "ok" if precio_usa is not None else "miss"

    reasons: list[str] = []
    if not usa_hit:
        reasons.append("no_fila_radar_usa")
    elif precio_usa is None:
        reasons.append("radar_usa_sin_precio")
    if p_ars is None:
        reasons.append("yahoo_sin_precio_ars")
    if p_ccl is None:
        reasons.append("yahoo_sin_precio_ccl")
    elif p_ccl <= 0:
        reasons.append("yahoo_ccl_no_positivo")
    if ratio <= 0:
        reasons.append("ratio_maestro_no_positivo")
    focus = 1 if u in _CEDEAR_AUDIT_FOCUS else 0
    reason_s = ";".join(reasons) if reasons else "ok"

    logger.info(
        "[CEDEAR_AUDIT] ticker_usa=%s ticker_cedear_ars=%s ticker_cedear_ccl=%s "
        "yahoo_ars=%s yahoo_ccl=%s usa_radar_row=%s usa_radar_precio=%s mod_usa=%s "
        "precio_cedear_usd_linea_ccl=%s ccl_implicito=%s precio_implicito_accion_usd=%s "
        "ratio=%s focus=%s reasons=%s",
        u,
        sym_ars,
        sym_ccl,
        y_ars,
        y_ccl,
        usa_row,
        usa_price,
        mod_usa,
        cedear_usd_line,
        ccl_i,
        p_impl,
        ratio,
        focus,
        reason_s,
    )


def _usa_row_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        raw = _radar_get(r, "Ticker", "ticker")
        if raw is None:
            continue
        key = str(raw).strip().upper()
        if key:
            out[key] = r
    return out


def build_cedear_rows_from_latest_radar() -> list[CedearRow] | None:
    """
    None si no hay export radar_*.xlsx.
    Incluye todos los mapeos activos. Si ticker_usa no está en el radar, se conserva la fila:
    precio USA con Yahoo (mismo ticker limpio); TotalScore y SignalState en null; mod_usa=NO.

    Cobertura USA vs pricing local: `cobertura_usa_mensaje` y `pricing_cedear_local_mensaje` separan
    ambos mundos sin ocultar filas ni cambiar fórmulas (precios/implícitos siguen en null si faltan datos).

    Datos del maestro (load_cedear_mappings_from_disk → CEDEAR_MAPPINGS):
        ticker_cedear_ars, ticker_cedear_ccl, cedears_por_accion_usa
    No usar en la lógica los alias ticker_cedear_usd / ratio_cedear_a_accion del dataclass.

    Fórmulas:
        ccl_implicito = precio_ars / precio_ccl
        precio_implicito_usd = precio_ccl * cedears_por_accion_usa
        gap_pct = (precio_implicito_usd / precio_usa_real - 1) * 100

    Diagnóstico:
        CEDEAR_DEBUG=1 → stderr por fila (símbolos y precios Yahoo).
        CEDEAR_AUDIT=1 → una línea INFO [CEDEAR_AUDIT] por fila (grep). Opcional:
        CEDEAR_AUDIT_TICKERS=ABT,AZN para acotar tickers.
    """
    t0 = time.perf_counter()
    yahoo_stats = {"yahoo_queries": 0, "yahoo_cache_hits": 0}

    payload = latest_export.read_latest_radar()
    if payload is None:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        logger.info(
            "cedear_build elapsed_ms=%.1f rows=0 yahoo_queries=0 yahoo_cache_hits=0 (no_export)",
            elapsed_ms,
        )
        return None
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        logger.info(
            "cedear_build elapsed_ms=%.1f rows=0 yahoo_queries=0 yahoo_cache_hits=0 (invalid_rows)",
            elapsed_ms,
        )
        return []

    by_ticker = _usa_row_index(raw_rows)
    out: list[CedearRow] = []
    yahoo_cache: dict[str, float | None] = {}

    for m in CEDEAR_MAPPINGS:
        if not m.activo:
            continue
        usa_key = m.ticker_usa.strip().upper()
        row = by_ticker.get(usa_key)
        if row is not None:
            precio_usa = _to_float(_radar_get(row, "Precio", "precio"))
            total_score = _to_float(_radar_get(row, "TotalScore", "total_score"))
            sig = _radar_get(row, "SignalState", "signal_state")
            signal_state = str(sig).strip() if sig is not None else None
            mod_usa: ModUsa = "SI"
        else:
            precio_usa = _yahoo_spot_cached(usa_key, yahoo_cache, yahoo_stats)
            total_score = None
            signal_state = None
            mod_usa = "NO"

        sym_ars = m.ticker_cedear_ars.strip()
        sym_ccl = m.ticker_cedear_ccl.strip()
        p_ars = _yahoo_spot_cached(sym_ars, yahoo_cache, yahoo_stats)
        p_ccl = _yahoo_spot_cached(sym_ccl, yahoo_cache, yahoo_stats)
        fuente_cedear: FuenteCedearLocal = "Yahoo"

        cedears_por = float(m.cedears_por_accion_usa)
        _cedear_debug_line(usa_key, sym_ars, sym_ccl, cedears_por, p_ars, p_ccl)

        ccl_impl: float | None = None
        if p_ars is not None and p_ccl is not None and p_ccl > 0:
            ccl_impl = round(p_ars / p_ccl, 6)

        precio_impl: float | None = None
        if p_ccl is not None and cedears_por > 0:
            precio_impl = round(p_ccl * cedears_por, 6)

        gap: float | None = None
        if precio_impl is not None and precio_usa is not None and precio_usa > 0:
            gap = round((precio_impl / precio_usa - 1.0) * 100.0, 4)

        _cedear_audit_log(
            ticker_usa=usa_key,
            sym_ars=sym_ars,
            sym_ccl=sym_ccl,
            usa_hit=row is not None,
            mod_usa=mod_usa,
            p_ars=p_ars,
            p_ccl=p_ccl,
            ccl_impl=ccl_impl,
            precio_impl=precio_impl,
            precio_usa=precio_usa,
            ratio=cedears_por,
        )

        estado_r, dias_val = _derive_ratio_audit(m.fecha_validacion_ratio)

        cob_msg = _cobertura_usa_mensaje(row, precio_usa)
        loc_msg = _pricing_cedear_local_mensaje(p_ars, p_ccl, ccl_impl, precio_impl)

        out.append(
            CedearRow(
                ticker_usa=m.ticker_usa.strip().upper(),
                ticker_cedear_ars=sym_ars,
                ticker_cedear_usd=sym_ccl,
                ratio=cedears_por,
                fuente_ratio=m.fuente_ratio,
                fecha_validacion_ratio=m.fecha_validacion_ratio,
                estado_ratio=estado_r,
                dias_desde_validacion=dias_val,
                precio_cedear_ars=p_ars,
                precio_cedear_usd=p_ccl,
                ccl_implicito=ccl_impl,
                precio_usa_real=precio_usa,
                precio_implicito_usd=precio_impl,
                gap_pct=gap,
                total_score=total_score,
                signal_state=signal_state,
                mod_usa=mod_usa,
                fuente_cedear=fuente_cedear,
                cobertura_usa_mensaje=cob_msg,
                pricing_cedear_local_mensaje=loc_msg,
            )
        )

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    logger.info(
        "cedear_build elapsed_ms=%.1f rows=%s yahoo_queries=%s yahoo_cache_hits=%s",
        elapsed_ms,
        len(out),
        yahoo_stats["yahoo_queries"],
        yahoo_stats["yahoo_cache_hits"],
    )
    return out
