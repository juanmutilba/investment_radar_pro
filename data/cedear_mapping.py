"""
Equivalencias USA ↔ CEDEAR y ratios auditables.

Fuente maestra (editar a mano, sin scraping ni inferencia de ratio):
    data/cedear_mappings.json

ticker_usa:
    Siempre el símbolo de la acción en el mercado USA (limpio: sin .BA ni sufijo local).
    El motor USA y el radar usan ese mismo valor en la columna Ticker.

ticker_cedear_ars / ticker_cedear_ccl:
    Símbolos Yahoo para ByMA; usar sufijo .BA de forma homogénea.
    Si `activo` es false, pueden ser null (fila sólo con ratio auditado hasta completar tickers ByMA).

Convención obligatoria:
    cedears_por_accion_usa = cantidad de CEDEAR que equivalen a 1 acción USA.
    precio_accion_usa_implicito_usd (servicio CEDEAR) =
        precio_1_cedear_en_linea_ccl_usd * cedears_por_accion_usa
    ccl_implicito = precio_cedear_ars / precio_cedear_ccl (tipo de cambio implícito ARS/USD del par).
    El ratio NO se deduce de precios; solo proviene del JSON.

Campos de auditoría (recomendados en cada fila del JSON):
    fuente_ratio           — texto libre: prospecto, URL, fecha de aviso, etc.
    fecha_validacion_ratio — string ISO "YYYY-MM-DD" o null si aún no validaste.

Cómo actualizar:
    1. Abrir cedear_mappings.json en el editor (o exportar desde planilla y pegar JSON válido).
    2. Ajustar cedears_por_accion_usa según fuente oficial; completar fuente_ratio y fecha.
    3. Guardar; reiniciar API si estaba en marcha (carga al importar el módulo).

Por qué JSON y no CSV:
    Campos opcionales y strings con comas son más simples en JSON; el loader valida tipos al arranque.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_MASTER_PATH = Path(__file__).resolve().with_name("cedear_mappings.json")


def _normalize_ticker(symbol: str) -> str:
    return (symbol or "").strip().upper()


def master_json_path() -> Path:
    """Ruta del archivo maestro (útil para mensajes de error o tooling)."""
    return _MASTER_PATH


@dataclass(frozen=True)
class CedearMapping:
    ticker_usa: str
    ticker_cedear_ars: str
    ticker_cedear_ccl: str
    cedears_por_accion_usa: float
    activo: bool
    nombre: str | None = None
    fuente_ratio: str | None = None
    fecha_validacion_ratio: str | None = None

    @property
    def ticker_cedear_usd(self) -> str:
        """Alias histórico: línea en dólares (CCL) = ticker_cedear_ccl."""
        return self.ticker_cedear_ccl

    @property
    def ratio_cedear_a_accion(self) -> float:
        """Solo lectura del maestro: igual a cedears_por_accion_usa."""
        return self.cedears_por_accion_usa


def _parse_bool(v: object, *, ctx: str) -> bool:
    if isinstance(v, bool):
        return v
    raise TypeError(f"{ctx}: activo debe ser boolean, no {type(v).__name__}")


def _local_ticker_from_json(
    raw: object, *, ctx: str, field: str, activo: bool
) -> str:
    if raw is None:
        if activo:
            raise ValueError(f"{ctx}: {field} es obligatorio cuando activo es true")
        return ""
    if not isinstance(raw, str):
        raise TypeError(f"{ctx}: {field} debe ser string o null, no {type(raw).__name__}")
    s = raw.strip()
    if activo and not s:
        raise ValueError(f"{ctx}: {field} no puede estar vacío cuando activo es true")
    return s


def _mapping_from_json_obj(o: object, *, index: int) -> CedearMapping:
    ctx = f"cedear_mappings.json[{index}]"
    if not isinstance(o, dict):
        raise TypeError(f"{ctx}: cada entrada debe ser un objeto JSON")
    req = ("ticker_usa", "cedears_por_accion_usa", "activo")
    for k in req:
        if k not in o:
            raise KeyError(f"{ctx}: falta clave obligatoria {k!r}")
    activo = _parse_bool(o["activo"], ctx=ctx)
    ars = _local_ticker_from_json(
        o.get("ticker_cedear_ars"), ctx=ctx, field="ticker_cedear_ars", activo=activo
    )
    ccl = _local_ticker_from_json(
        o.get("ticker_cedear_ccl"), ctx=ctx, field="ticker_cedear_ccl", activo=activo
    )
    ratio_raw = o["cedears_por_accion_usa"]
    try:
        ratio = float(ratio_raw)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{ctx}: cedears_por_accion_usa numérico inválido: {ratio_raw!r}") from e
    if ratio <= 0 or ratio != ratio:
        raise ValueError(f"{ctx}: cedears_por_accion_usa debe ser > 0 (valor: {ratio})")

    nombre = o.get("nombre")
    fuente = o.get("fuente_ratio")
    fecha = o.get("fecha_validacion_ratio")
    if nombre is not None and not isinstance(nombre, str):
        raise TypeError(f"{ctx}: nombre debe ser string o omitirse")
    if fuente is not None and not isinstance(fuente, str):
        raise TypeError(f"{ctx}: fuente_ratio debe ser string o null")
    if fecha is not None and not isinstance(fecha, str):
        raise TypeError(f"{ctx}: fecha_validacion_ratio debe ser string ISO o null")

    return CedearMapping(
        ticker_usa=str(o["ticker_usa"]).strip(),
        ticker_cedear_ars=ars,
        ticker_cedear_ccl=ccl,
        cedears_por_accion_usa=ratio,
        activo=activo,
        nombre=(str(nombre).strip() if nombre else None),
        fuente_ratio=(str(fuente).strip() if fuente else None),
        fecha_validacion_ratio=(str(fecha).strip() if fecha else None),
    )


def load_cedear_mappings_from_disk(path: Path | None = None) -> tuple[CedearMapping, ...]:
    """
    Lee y valida el maestro JSON. Lanza si el archivo falta o el contenido es inválido.
    """
    p = path if path is not None else _MASTER_PATH
    if not p.is_file():
        raise FileNotFoundError(
            f"No existe el maestro CEDEAR: {p}. Crearlo o restaurar desde el repo."
        )
    raw_text = p.read_text(encoding="utf-8")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON inválido en {p}: {e}") from e
    if not isinstance(data, list):
        raise TypeError(f"{p}: la raíz debe ser un array de objetos")
    out: list[CedearMapping] = []
    for i, item in enumerate(data):
        out.append(_mapping_from_json_obj(item, index=i))
    return tuple(out)


def _validate_and_build_indexes(
    mappings: tuple[CedearMapping, ...],
) -> tuple[dict[str, CedearMapping], dict[str, CedearMapping]]:
    by_usa: dict[str, CedearMapping] = {}
    by_local: dict[str, CedearMapping] = {}
    for m in mappings:
        u = _normalize_ticker(m.ticker_usa)
        if not u:
            raise ValueError("cedear_mapping: ticker_usa vacío")
        if u in by_usa:
            raise ValueError(f"cedear_mapping: ticker_usa duplicado: {u}")
        by_usa[u] = m
        for sym in (m.ticker_cedear_ars, m.ticker_cedear_ccl):
            k = _normalize_ticker(sym)
            if not k:
                continue
            prev = by_local.get(k)
            if prev is not None and _normalize_ticker(prev.ticker_usa) != u:
                raise ValueError(
                    f"cedear_mapping: ticker local {k!r} repetido (USA {prev.ticker_usa} vs {m.ticker_usa})"
                )
            by_local[k] = m
    return by_usa, by_local


CEDEAR_MAPPINGS: tuple[CedearMapping, ...] = load_cedear_mappings_from_disk()
CEDEAR_BY_USA: dict[str, CedearMapping]
CEDEAR_BY_LOCAL: dict[str, CedearMapping]
CEDEAR_BY_USA, CEDEAR_BY_LOCAL = _validate_and_build_indexes(CEDEAR_MAPPINGS)


def normalize_usa_ticker_for_cedear_lookup(ticker):
    if not ticker:
        return None
    t = str(ticker).strip().upper()
    if t.endswith(".BA"):
        t = t[:-3]
    t = t.replace(".", "-")
    return t


def get_active_cedear_usa_tickers():
    out = set()
    for m in CEDEAR_MAPPINGS:
        if m.activo:
            k = normalize_usa_ticker_for_cedear_lookup(m.ticker_usa)
            if k:
                out.add(k)
    return out


def ticker_usa_list_for_universe_merge() -> list[str]:
    """
    tickers USA (limpios) de filas CEDEAR activas, en orden del maestro, sin duplicados.
    Se concatena al universo USA del motor para que el radar incluya subyacentes aunque
    no estén en las listas estáticas de universe_usa.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in CEDEAR_MAPPINGS:
        if not m.activo:
            continue
        u = _normalize_ticker(m.ticker_usa)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def get_cedear_by_usa(ticker_usa: str) -> CedearMapping | None:
    """USA → fila maestra. None si no hay entrada o `activo` es False."""
    m = CEDEAR_BY_USA.get(_normalize_ticker(ticker_usa))
    if m is None or not m.activo:
        return None
    return m


def get_cedear_by_local(ticker_local: str) -> CedearMapping | None:
    """Ticker ByMA (ARS o CCL) → fila maestra. None si no hay entrada o inactiva."""
    m = CEDEAR_BY_LOCAL.get(_normalize_ticker(ticker_local))
    if m is None or not m.activo:
        return None
    return m


def has_cedear(ticker_usa: str) -> bool:
    """True si existe equivalencia activa para el ticker USA."""
    return get_cedear_by_usa(ticker_usa) is not None


def cedear_fields_for_usa_row(ticker_usa: str) -> dict[str, object]:
    """
    Valores para columnas del radar USA (una fila).
    TieneCedear solo True con entrada activa; filas inactivas quedan en False sin tickers.
    """
    m_active = get_cedear_by_usa(ticker_usa)
    if m_active is not None:
        return {
            "TieneCedear": True,
            "TickerCedearARS": m_active.ticker_cedear_ars,
            "TickerCedearCCL": m_active.ticker_cedear_ccl,
            "CedearsPorAccionUSA": m_active.cedears_por_accion_usa,
        }
    return {
        "TieneCedear": False,
        "TickerCedearARS": None,
        "TickerCedearCCL": None,
        "CedearsPorAccionUSA": None,
    }


def enrich_usa_radar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Añade TieneCedear, TickerCedearARS, TickerCedearCCL, CedearsPorAccionUSA
    al DataFrame del radar USA, insertadas justo después de la columna Ticker.
    """
    if df.empty or "Ticker" not in df.columns:
        return df
    out = df.copy()
    fields = [cedear_fields_for_usa_row(str(t)) for t in out["Ticker"]]
    extra = pd.DataFrame(
        {
            "TieneCedear": [f["TieneCedear"] for f in fields],
            "TickerCedearARS": [f["TickerCedearARS"] for f in fields],
            "TickerCedearCCL": [f["TickerCedearCCL"] for f in fields],
            "CedearsPorAccionUSA": [f["CedearsPorAccionUSA"] for f in fields],
        },
        index=out.index,
    )
    loc = out.columns.get_loc("Ticker")
    if isinstance(loc, slice):
        raise TypeError("cedear_mapping: columna Ticker no debe ser MultiIndex slice")
    cut = int(loc) + 1
    left = out.iloc[:, :cut]
    right = out.iloc[:, cut:]
    result = pd.concat([left, extra, right], axis=1)
    cedear_set = get_active_cedear_usa_tickers()
    result["CEDEAR"] = result["Ticker"].apply(
        lambda t: "SI" if normalize_usa_ticker_for_cedear_lookup(t) in cedear_set else "NO"
    )
    return result
