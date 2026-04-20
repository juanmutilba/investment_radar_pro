from __future__ import annotations

import math
import os
import sys
from datetime import date
from typing import Any, Literal

import yfinance as yf
from pydantic import BaseModel, ConfigDict, Field

from data.cedear_mapping import CEDEAR_MAPPINGS
from services import latest_export

RatioEstado = Literal["ok", "pendiente_validar", "revisar"]
ModUsa = Literal["SI", "NO"]
FuenteCedearLocal = Literal["Yahoo"]
_RATIO_STALE_DAYS = 180


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


def _fetch_cedear_local_spot(symbol: str) -> tuple[float | None, FuenteCedearLocal]:
    """Precio spot línea CEDEAR (ARS o cable) vía Yahoo."""
    sym = (symbol or "").strip()
    if not sym:
        return None, "Yahoo"
    return _fetch_last_price(sym), "Yahoo"


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

    Datos del maestro (load_cedear_mappings_from_disk → CEDEAR_MAPPINGS):
        ticker_cedear_ars, ticker_cedear_ccl, cedears_por_accion_usa
    No usar en la lógica los alias ticker_cedear_usd / ratio_cedear_a_accion del dataclass.

    Fórmulas:
        ccl_implicito = precio_ars / precio_ccl
        precio_implicito_usd = precio_ccl * cedears_por_accion_usa
        gap_pct = (precio_implicito_usd / precio_usa_real - 1) * 100

    Diagnóstico: CEDEAR_DEBUG=1 en el entorno imprime ARS/CCL/ratio/precios por fila en stderr.
    """
    payload = latest_export.read_latest_radar()
    if payload is None:
        return None
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        return []

    by_ticker = _usa_row_index(raw_rows)
    out: list[CedearRow] = []

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
            precio_usa = _fetch_last_price(usa_key)
            total_score = None
            signal_state = None
            mod_usa = "NO"

        sym_ars = m.ticker_cedear_ars.strip()
        sym_ccl = m.ticker_cedear_ccl.strip()
        p_ars, _ = _fetch_cedear_local_spot(sym_ars)
        p_ccl, _ = _fetch_cedear_local_spot(sym_ccl)
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

        estado_r, dias_val = _derive_ratio_audit(m.fecha_validacion_ratio)

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
            )
        )

    return out
