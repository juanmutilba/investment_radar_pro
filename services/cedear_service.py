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

from data.cedear_mapping import CEDEAR_MAPPINGS, CedearMapping
from services import latest_export

logger = logging.getLogger(__name__)

RatioEstado = Literal["ok", "pendiente_validar", "revisar"]
ModUsa = Literal["SI", "NO"]
FuenteCedearLocal = Literal["IOL", "Yahoo", "IOL/Yahoo", "Sin datos", "IOL (sin CCL)"]
_RATIO_STALE_DAYS = 180

# Máximo de consultas HTTP IOL por build CEDEAR (ARS/CCL); el resto va directo a Yahoo / None.
IOL_MAX_CALLS = 300

# TEMP: diagnóstico IOL (primeros N intentos por build); quitar cuando cierre el incidente.
_IOL_PATH_DEBUG_PRINTS_MAX = 20
_iol_path_debug_prints: int = 0


def _iol_path_debug_reset() -> None:
    global _iol_path_debug_prints
    _iol_path_debug_prints = 0


def _iol_path_debug_emit(raw: str, iol_sym: str, *, action: str) -> None:
    global _iol_path_debug_prints
    if _iol_path_debug_prints >= _IOL_PATH_DEBUG_PRINTS_MAX:
        return
    _iol_path_debug_prints += 1
    print("[IOL_PATH_DEBUG] raw=%r iol_sym=%r action=%s" % (raw, iol_sym, action), flush=True)


# Fallback get_usa_price/Yahoo en CEDEAR: tickers USA que no resuelven y solo suman latencia.
_USA_PRICE_KNOWN_BAD: frozenset[str] = frozenset({"AUY", "DISN", "MMC"})

# Cache global (por proceso) para precios Yahoo locales CEDEAR (ARS/CCL).
# Evita repetir consultas entre corridas cercanas (p. ej. scan + requests API).
# TTL corto para minimizar staleness: configurar con CEDEAR_LOCAL_YAHOO_CACHE_TTL_S.
_LOCAL_YAHOO_CACHE: dict[str, tuple[float, float | None]] = {}
_LOCAL_YAHOO_CACHE_TTL_S_DEFAULT = 60.0

# Fallback Yahoo local: símbolos que yfinance no resuelve (ruido / latencia). Claves en UPPER.
_LOCAL_YAHOO_KNOWN_BAD: frozenset[str] = frozenset(
    {"GOOGLC.BA", "AUY", "AUYC.BA", "BBC.BA", "BKC.BA"}
)

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
    usa_radar_match: bool = Field(
        default=False,
        description="True si hubo fila en Radar_Completo para la clave de lookup USA normalizada.",
    )
    ticker_usa_lookup: str | None = Field(
        None,
        description="Clave usada para unir con el índice del radar USA (_norm_usa_ticker(ticker_usa)).",
    )
    usa_radar_match_reason: str | None = Field(
        None,
        description='Solo si no hay match; p. ej. "no_match_in_radar".',
    )
    fuente_cedear: FuenteCedearLocal = Field(
        ...,
        description="Origen precios locales ARS/CCL: IOL, Yahoo, mixto, Sin datos, o IOL (sin CCL) si falta línea USD.",
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


def _cedear_radar_total_score(row: dict[str, Any]) -> float | None:
    raw = _radar_get(
        row,
        "TotalScore",
        "total_score",
        "totalScore",
        "Score",
        "score",
    )
    return _to_float(raw)


def _cedear_radar_signal_state(row: dict[str, Any]) -> str | None:
    sig = _radar_get(
        row,
        "SignalState",
        "signal_state",
        "signalState",
        "EstadoSenal",
        "estado_senal",
    )
    if sig is None:
        return None
    s = str(sig).strip()
    return s if s else None


def _usa_price_from_radar_row(row: dict[str, Any]) -> float | None:
    """
    Precio spot USA ya presente en la fila del radar export (evita get_usa_price/Yahoo por fila).
    """
    raw = _radar_get(
        row,
        "Precio",
        "precio",
        "Price",
        "price",
        "LastPrice",
        "lastPrice",
        "Close",
        "close",
    )
    x = _to_float(raw)
    if x is None or x <= 0:
        return None
    return round(x, 6)


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

    # Cache local (por corrida/build) - dedupe intra-build
    if key in cache:
        stats["yahoo_cache_hits"] += 1
        return cache[key]

    # Cache global (por proceso) - dedupe inter-build (TTL corto)
    try:
        ttl_s = float(os.environ.get("CEDEAR_LOCAL_YAHOO_CACHE_TTL_S", str(_LOCAL_YAHOO_CACHE_TTL_S_DEFAULT)))
    except (TypeError, ValueError):
        ttl_s = _LOCAL_YAHOO_CACHE_TTL_S_DEFAULT
    ttl_s = max(0.0, min(ttl_s, 3600.0))
    if ttl_s > 0:
        now = time.monotonic()
        prev = _LOCAL_YAHOO_CACHE.get(key)
        if prev is not None:
            ts, val = prev
            if now - ts <= ttl_s:
                # También cachea None para evitar hammering cuando Yahoo no trae datos.
                stats["yahoo_cache_hits"] += 1
                cache[key] = val
                return val

    stats["yahoo_queries"] += 1
    p: float | None = None
    try:
        p = _fetch_last_price(sym)
    finally:
        cache[key] = p
        if ttl_s > 0:
            try:
                _LOCAL_YAHOO_CACHE[key] = (time.monotonic(), p)
            except Exception:
                pass
    return p


def _yahoo_spot_cached_local_fallback(
    symbol: str,
    cache: dict[str, float | None],
    stats: dict[str, int],
    yahoo_negative: set[str],
) -> float | None:
    """
    Envuelve _yahoo_spot_cached sin modificarlo: cache negativa por corrida para símbolos
    locales que ya fallaron en Yahoo (evita reintentos costosos en la misma build).
    Además, `_LOCAL_YAHOO_KNOWN_BAD` evita llamar yfinance para tickers que no existen en Yahoo.
    Tickers que parecen variante CEDEAR C (`_is_probably_cedear_c_variant`) no llaman Yahoo si llegaron aquí
    (IOL ya se intentó antes en el caller).
    """
    sym = (symbol or "").strip()
    if not sym:
        return None
    key = sym.upper()
    if key in yahoo_negative or key in _LOCAL_YAHOO_KNOWN_BAD:
        stats["local_yahoo_negative_cache_hits"] = int(stats.get("local_yahoo_negative_cache_hits", 0)) + 1
        if key in _LOCAL_YAHOO_KNOWN_BAD:
            stats["local_yahoo_known_bad_skips"] = int(stats.get("local_yahoo_known_bad_skips", 0)) + 1
        return None
    if _is_probably_cedear_c_variant(sym):
        stats["local_yahoo_c_variant_skips"] = int(stats.get("local_yahoo_c_variant_skips", 0)) + 1
        yahoo_negative.add(key)
        return None
    queries_before = int(stats.get("yahoo_queries", 0))
    p = _yahoo_spot_cached(sym, cache, stats)
    if p is None:
        yahoo_negative.add(key)
        if int(stats.get("yahoo_queries", 0)) > queries_before:
            stats["local_yahoo_failures"] = int(stats.get("local_yahoo_failures", 0)) + 1
    return p


def _normalize_iol_ticker(symbol: str) -> str:
    """
    Normaliza el símbolo solo para IOL (sin tocar el usado para Yahoo fallback):
    - quita prefijo '$' si aparece (logs/formatos antiguos)
    - quita sufijo '.BA' (símbolo Yahoo ByMA)
    """
    s = (symbol or "").strip()
    if not s:
        return ""
    if s.startswith("$"):
        s = s[1:].strip()
    su = s.upper()
    if su.endswith(".BA"):
        s = s[: -len(".BA")].strip()
    return s.strip().upper()


# Local tickers tipo XXXC (ratio C) suelen no existir en Yahoo; INTC es NYSE real (termina en C sin ser variante C).
_LOCAL_YAHOO_C_SUFFIX_EXCEPTIONS: frozenset[str] = frozenset({"INTC"})


def _is_probably_cedear_c_variant(symbol: str) -> bool:
    """
    Heurística para CEDEAR "variante C" (sufijo C en ByMA). Normaliza ($, .BA, upper).
    Base: >= 3 letras, solo alfabético, termina en C (excepción INTC).
    Tickers base de 3 letras (p. ej. BBC): solo si el original termina en .BA (evita falsos positivos).
    Con base de 4+ letras, basta el sufijo C (p. ej. ADIC / ADIC.BA).
    """
    raw = (symbol or "").strip().upper()
    base = _normalize_iol_ticker(symbol)
    if len(base) < 3 or not base.isalpha():
        return False
    if base in _LOCAL_YAHOO_C_SUFFIX_EXCEPTIONS:
        return False
    if not base.endswith("C"):
        return False
    if len(base) == 3:
        return raw.endswith(".BA")
    return True


def _fuente_cedear_local(
    p_ars: float | None,
    p_ccl: float | None,
    ars_from_iol: bool,
    ccl_from_iol: bool,
) -> FuenteCedearLocal:
    """Resume fuente real de precios locales (ARS y línea CCL) sin mirar valores numéricos."""
    has_ars = p_ars is not None
    has_ccl = p_ccl is not None
    if not has_ars and not has_ccl:
        return "Sin datos"
    ars_src = "iol" if has_ars and ars_from_iol else ("yahoo" if has_ars else None)
    ccl_src = "iol" if has_ccl and ccl_from_iol else ("yahoo" if has_ccl else None)
    kinds = {s for s in (ars_src, ccl_src) if s is not None}
    if kinds == {"iol"}:
        return "IOL"
    if kinds == {"yahoo"}:
        return "Yahoo"
    if kinds == {"iol", "yahoo"}:
        return "IOL/Yahoo"
    return "Sin datos"


def _try_local_iol_price(symbol: str, stats: dict[str, int]) -> tuple[float | None, bool, bool]:
    """
    Intenta precio local (ARS/CCL) vía IOL. Retorna (precio, allow_yahoo_fallback, from_iol).

    ``from_iol`` es True solo si ``precio`` no es None y proviene de IOL (RAM o red).
    ``allow_yahoo_fallback`` es False si se omitió la red por ``IOL_MAX_CALLS``, o si IOL
    dejó el símbolo en caché negativa (404 / sin precio conocido): no insistir con Yahoo local.
    En otros fallos (IOL deshabilitado, token, caché RAM inválida, excepción local), se mantiene
    True para conservar IOL → Yahoo → None donde aplique.
    """
    sym = (symbol or "").strip()
    if not sym:
        _iol_path_debug_emit("", "", action="empty_symbol")
        return None, True, False
    try:
        from services.market_data.providers.iol import get_iol_quote, is_iol_enabled, read_iol_quote_ram_only

        if not is_iol_enabled():
            iol_sym0 = _normalize_iol_ticker(sym)
            _iol_path_debug_emit(sym, iol_sym0, action="disabled")
            return None, True, False
        iol_sym = _normalize_iol_ticker(sym)
        if not iol_sym:
            stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
            _iol_path_debug_emit(sym, "", action="empty_symbol")
            return None, True, False
        if iol_sym != sym.strip().upper():
            stats["local_iol_normalized_symbols"] = int(stats.get("local_iol_normalized_symbols", 0)) + 1

        ram = read_iol_quote_ram_only(iol_sym)
        if ram == "negative":
            print("[IOL_NEGATIVE_CACHE] symbol_raw=%s iol_symbol=%s" % (sym, iol_sym))
            stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
            _iol_path_debug_emit(sym, iol_sym, action="ram_negative")
            return None, False, False
        if ram is not None:
            q = ram
            if not getattr(q, "is_valid", False):
                stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
                _iol_path_debug_emit(sym, iol_sym, action="http_none")
                return None, True, False
            if getattr(q, "source", None) != "iol":
                stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
                _iol_path_debug_emit(sym, iol_sym, action="http_none")
                return None, True, False
            v = q.value
            if v is None:
                stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
                _iol_path_debug_emit(sym, iol_sym, action="http_none")
                return None, True, False
            try:
                x = float(v)
            except (TypeError, ValueError):
                stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
                _iol_path_debug_emit(sym, iol_sym, action="http_none")
                return None, True, False
            if x != x or x <= 0:
                stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
                _iol_path_debug_emit(sym, iol_sym, action="http_none")
                return None, True, False
            stats["local_iol_hits"] = int(stats.get("local_iol_hits", 0)) + 1
            _iol_path_debug_emit(sym, iol_sym, action="ram_positive")
            return round(x, 6), False, True

        if int(stats.get("local_iol_calls", 0)) >= IOL_MAX_CALLS:
            stats["local_iol_skipped_by_limit"] = int(stats.get("local_iol_skipped_by_limit", 0)) + 1
            _iol_path_debug_emit(sym, iol_sym, action="limit_skip")
            return None, False, False
        _iol_path_debug_emit(sym, iol_sym, action="http_call")
        stats["local_iol_calls"] = int(stats.get("local_iol_calls", 0)) + 1
        q = get_iol_quote(iol_sym)

        def _allow_yahoo_after_iol_miss() -> bool:
            return read_iol_quote_ram_only(iol_sym) != "negative"

        if q is None or not getattr(q, "is_valid", False):
            stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
            _iol_path_debug_emit(sym, iol_sym, action="http_none")
            return None, _allow_yahoo_after_iol_miss(), False
        if getattr(q, "source", None) != "iol":
            stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
            _iol_path_debug_emit(sym, iol_sym, action="http_none")
            return None, _allow_yahoo_after_iol_miss(), False
        v = q.value
        if v is None:
            stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
            _iol_path_debug_emit(sym, iol_sym, action="http_none")
            return None, _allow_yahoo_after_iol_miss(), False
        try:
            x = float(v)
        except (TypeError, ValueError):
            stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
            _iol_path_debug_emit(sym, iol_sym, action="http_none")
            return None, _allow_yahoo_after_iol_miss(), False
        if x != x or x <= 0:
            stats["local_iol_misses"] = int(stats.get("local_iol_misses", 0)) + 1
            _iol_path_debug_emit(sym, iol_sym, action="http_none")
            return None, _allow_yahoo_after_iol_miss(), False
        stats["local_iol_hits"] = int(stats.get("local_iol_hits", 0)) + 1
        _iol_path_debug_emit(sym, iol_sym, action="http_ok")
        return round(x, 6), False, True
    except Exception:
        try:
            iol_sym_e = _normalize_iol_ticker(sym)
        except Exception:
            iol_sym_e = ""
        _iol_path_debug_emit(sym, iol_sym_e, action="exception")
        return None, True, False


def _build_single_cedear_row(
    m: CedearMapping,
    *,
    by_ticker: dict[str, dict[str, Any]],
    yahoo_stats: dict[str, int],
    yahoo_cache: dict[str, float | None],
    usa_price_cache: dict[str, float | None],
    yahoo_negative_local: set[str],
    ccl_debug_count_holder: list[int],
) -> tuple[CedearRow, float, float, float, float, int, int]:
    """
    Una fila CEDEAR activa. Devuelve
    (row, usa_price_ms, local_iol_ms, loc_yahoo_ms, row_total_ms, usa_matches_inc, usa_misses_inc).
    """
    t_row0 = time.perf_counter()
    ticker_usa_disp = m.ticker_usa.strip().upper()
    usa_key = _norm_usa_ticker(m.ticker_usa)
    row = by_ticker.get(usa_key) if usa_key is not None else None
    if row is not None:
        usa_matches_inc = 1
        usa_misses_inc = 0
        usa_radar_match = True
        ticker_usa_lookup = usa_key
        usa_radar_match_reason: str | None = None
    else:
        usa_matches_inc = 0
        usa_misses_inc = 1
        usa_radar_match = False
        ticker_usa_lookup = usa_key
        usa_radar_match_reason = "no_match_in_radar"
    if row is not None:
        total_score = _cedear_radar_total_score(row)
        if total_score is not None:
            yahoo_stats["usa_enrichment_hits_total_score"] = int(
                yahoo_stats.get("usa_enrichment_hits_total_score", 0)
            ) + 1
        signal_state = _cedear_radar_signal_state(row)
        if signal_state is not None:
            yahoo_stats["usa_enrichment_hits_signal_state"] = int(
                yahoo_stats.get("usa_enrichment_hits_signal_state", 0)
            ) + 1
        mod_usa: ModUsa = "SI"
    else:
        total_score = None
        signal_state = None
        mod_usa = "NO"

    t_usa0 = time.perf_counter()
    precio_usa: float | None = None
    if row is not None:
        pr_usa = _usa_price_from_radar_row(row)
        if pr_usa is not None:
            yahoo_stats["usa_price_from_radar_hits"] = int(yahoo_stats.get("usa_price_from_radar_hits", 0)) + 1
            precio_usa = pr_usa
            if usa_key is not None:
                usa_price_cache[usa_key] = pr_usa
    if precio_usa is None:
        if ticker_usa_disp in _USA_PRICE_KNOWN_BAD:
            yahoo_stats["usa_price_fallback_known_bad_skips"] = int(
                yahoo_stats.get("usa_price_fallback_known_bad_skips", 0)
            ) + 1
        else:
            yahoo_stats["usa_price_fallback_calls"] = int(yahoo_stats.get("usa_price_fallback_calls", 0)) + 1
            precio_usa = _usa_price_spot_cached(
                usa_key if usa_key is not None else ticker_usa_disp,
                usa_price_cache,
                yahoo_stats,
            )
            if precio_usa is None:
                yahoo_stats["usa_price_fallback_failures"] = int(
                    yahoo_stats.get("usa_price_fallback_failures", 0)
                ) + 1
    t_usa1 = time.perf_counter()
    usa_price_ms = (t_usa1 - t_usa0) * 1000.0

    sym_ars = m.ticker_cedear_ars.strip()
    sym_ccl = m.ticker_cedear_ccl.strip()
    loc_yahoo_ms_spent = 0.0
    acc_iol_row_ms = 0.0

    t_iol0 = time.perf_counter()
    p_ars, yahoo_ok_ars, ars_from_iol = _try_local_iol_price(sym_ars, yahoo_stats)
    t_iol1 = time.perf_counter()
    acc_iol_row_ms += (t_iol1 - t_iol0) * 1000.0
    if p_ars is None and yahoo_ok_ars:
        yahoo_stats["local_yahoo_fallback_calls"] += 1
        t_loc0 = time.perf_counter()
        p_ars = _yahoo_spot_cached_local_fallback(sym_ars, yahoo_cache, yahoo_stats, yahoo_negative_local)
        t_loc1 = time.perf_counter()
        loc_yahoo_ms_spent += (t_loc1 - t_loc0) * 1000.0
        ars_from_iol = False
    elif p_ars is None and not yahoo_ok_ars:
        yahoo_stats["local_yahoo_skipped_due_iol_limit"] = int(
            yahoo_stats.get("local_yahoo_skipped_due_iol_limit", 0)
        ) + 1

    t_iol0 = time.perf_counter()
    p_ccl, yahoo_ok_ccl, ccl_from_iol = _try_local_iol_price(sym_ccl, yahoo_stats)
    t_iol1 = time.perf_counter()
    acc_iol_row_ms += (t_iol1 - t_iol0) * 1000.0
    if p_ccl is None and yahoo_ok_ccl:
        yahoo_stats["local_yahoo_fallback_calls"] += 1
        t_loc0 = time.perf_counter()
        p_ccl = _yahoo_spot_cached_local_fallback(sym_ccl, yahoo_cache, yahoo_stats, yahoo_negative_local)
        t_loc1 = time.perf_counter()
        loc_yahoo_ms_spent += (t_loc1 - t_loc0) * 1000.0
        ccl_from_iol = False
    elif p_ccl is None and not yahoo_ok_ccl:
        yahoo_stats["local_yahoo_skipped_due_iol_limit"] = int(
            yahoo_stats.get("local_yahoo_skipped_due_iol_limit", 0)
        ) + 1

    fuente_cedear: FuenteCedearLocal = _fuente_cedear_local(p_ars, p_ccl, ars_from_iol, ccl_from_iol)
    if p_ccl is None:
        fuente_cedear = "IOL (sin CCL)"

    cedears_por = float(m.cedears_por_accion_usa)
    _cedear_debug_line(ticker_usa_disp, sym_ars, sym_ccl, cedears_por, p_ars, p_ccl)

    ccl_impl: float | None = None
    if p_ars is not None and p_ccl is not None and p_ccl > 0:
        ccl_impl = round(p_ars / p_ccl, 6)

    ccl_debug_count = ccl_debug_count_holder[0]
    if ccl_debug_count < 20:
        if p_ars is None:
            reason = "missing_ars"
        elif p_ccl is None:
            reason = "missing_usd_line"
        elif p_ccl <= 0:
            reason = "usd_line_nonpositive"
        else:
            reason = "ok"
        print(
            "[CEDEAR_CCL_DEBUG] ticker_usa=%s ars_symbol=%s usd_symbol=%s precio_ars=%r precio_usd=%r ccl=%r fuente=%s reason=%s"
            % (
                ticker_usa_disp,
                sym_ars,
                sym_ccl,
                p_ars,
                p_ccl,
                ccl_impl,
                fuente_cedear,
                reason,
            )
        )
        ccl_debug_count_holder[0] = ccl_debug_count + 1

    precio_impl: float | None = None
    if p_ccl is not None and p_ccl > 0 and cedears_por > 0:
        precio_impl = round(p_ccl * cedears_por, 6)

    gap: float | None = None
    if precio_impl is not None and precio_usa is not None and precio_usa > 0:
        gap = round((precio_impl / precio_usa - 1.0) * 100.0, 4)

    _cedear_audit_log(
        ticker_usa=ticker_usa_disp,
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

    built = CedearRow(
        ticker_usa=ticker_usa_disp,
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
        usa_radar_match=usa_radar_match,
        ticker_usa_lookup=ticker_usa_lookup,
        usa_radar_match_reason=usa_radar_match_reason,
        fuente_cedear=fuente_cedear,
        cobertura_usa_mensaje=cob_msg,
        pricing_cedear_local_mensaje=loc_msg,
    )
    t_row1 = time.perf_counter()
    row_total_ms = (t_row1 - t_row0) * 1000.0
    return (
        built,
        usa_price_ms,
        acc_iol_row_ms,
        loc_yahoo_ms_spent,
        row_total_ms,
        usa_matches_inc,
        usa_misses_inc,
    )


def _usa_price_spot_cached(ticker_usa: str, cache: dict[str, float | None], stats: dict[str, int]) -> float | None:
    """
    precio_usa_real vía services.market_data.get_usa_price cuando no hay precio usable en la fila radar.
    Cache dedicado (no compartir con _yahoo_spot_cached de ARS/CCL) para evitar colisiones de ticker.
    """
    sym = (ticker_usa or "").strip()
    if not sym:
        return None
    key = sym.upper()
    if key in cache:
        stats["yahoo_cache_hits"] += 1
        return cache[key]
    stats["yahoo_queries"] += 1
    p: float | None = None
    try:
        from services.market_data import get_usa_price

        q = get_usa_price(sym, prefer_export=True)
        p = q.value
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


def _norm_usa_ticker(ticker: Any) -> str | None:
    """
    Clave estable para unir maestro CEDEAR (ticker_usa) con Radar_Completo.
    Corrige ticker_usa con sufijo .BA por error; alinea BRK.B con BRK-B.
    """
    if not ticker:
        return None
    t = str(ticker).strip().upper()
    if not t:
        return None
    if t.endswith(".BA"):
        t = t[:-3]
    t = t.replace(".", "-")
    return t if t else None


def _usa_row_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        raw_symbol = _radar_get(r, "Ticker", "ticker", "Symbol", "symbol")
        if raw_symbol is None:
            continue
        key = _norm_usa_ticker(raw_symbol)
        if not key:
            continue
        out[key] = r
    return out


def _log_cedear_timing_breakdown(
    *,
    total_ms: float,
    maestro_scan_ms: float,
    maestro_entries: int,
    maestro_active: int,
    radar_usa_ms: float | None,
    usa_rows_indexed: int | None,
    loop_rows: int,
    usa_price_ms: float,
    usa_price_from_radar_hits: int,
    usa_price_fallback_calls: int,
    usa_price_fallback_failures: int,
    usa_price_fallback_known_bad_skips: int,
    usa_enrichment_hits_total_score: int,
    usa_enrichment_hits_signal_state: int,
    local_iol_ms: float,
    local_yahoo_ms: float,
    row_other_ms: float,
    yahoo_queries: int,
    yahoo_cache_hits: int,
    local_iol_calls: int,
    local_iol_hits: int,
    local_iol_misses: int,
    local_iol_cache_hits: int,
    local_iol_skipped_by_limit: int,
    local_yahoo_fallback_calls: int,
    local_iol_normalized_symbols: int,
    local_yahoo_failures: int,
    local_yahoo_negative_cache_hits: int,
    local_yahoo_known_bad_skips: int,
    local_yahoo_c_variant_skips: int,
    local_yahoo_skipped_due_iol_limit: int,
    phase_note: str | None = None,
) -> None:
    """
    Resumen de performance por fase (grep: CEDEAR_TIMING).
    maestro: tupla CEDEAR_MAPPINGS ya cargada al import; maestro_scan_ms es recorrido en memoria.
    radar_usa: lectura radar_*.xlsx (USA) + índice por ticker.
    usa_price: suma wall-clock de resolución precio USA (columna radar si existe, si no _usa_price_spot_cached).
    local_yahoo: suma wall-clock de _yahoo_spot_cached ARS + CCL por fila activa.
    row_other: lookup fila USA, gap, debug/audit, mensajes cobertura, CedearRow y append (sin red).
    """
    radar_s = f"{radar_usa_ms:.1f} (usa_rows_indexed={usa_rows_indexed})" if radar_usa_ms is not None else "n/a"
    extra = f" note={phase_note}" if phase_note else ""
    msg = (
        "[CEDEAR_TIMING] total_ms=%.1f rows_out=%s yahoo_queries=%s yahoo_cache_hits=%s%s\n"
        "  local_iol_calls=%s local_iol_hits=%s local_iol_misses=%s local_iol_cache_hits=%s local_iol_skipped_by_limit=%s local_yahoo_fallback_calls=%s local_iol_normalized_symbols=%s\n"
        "  local_yahoo_failures=%s local_yahoo_negative_cache_hits=%s local_yahoo_known_bad_skips=%s local_yahoo_c_variant_skips=%s local_yahoo_skipped_due_iol_limit=%s\n"
        "  maestro_scan_ms=%.1f (entries=%s active=%s; tupla ya en RAM al import)\n"
        "  radar_usa_ms=%s\n"
        "  usa_price_resolve_ms=%.1f usa_price_from_radar_hits=%s usa_price_fallback_calls=%s usa_price_fallback_failures=%s usa_price_fallback_known_bad_skips=%s\n"
        "  usa_enrichment_hits_total_score=%s usa_enrichment_hits_signal_state=%s\n"
        "  local_iol_ms=%.1f\n"
        "  local_yahoo_ars_ccl_ms=%.1f\n"
        "  row_other_ms=%.1f"
        % (
            total_ms,
            loop_rows,
            yahoo_queries,
            yahoo_cache_hits,
            extra,
            local_iol_calls,
            local_iol_hits,
            local_iol_misses,
            local_iol_cache_hits,
            local_iol_skipped_by_limit,
            local_yahoo_fallback_calls,
            local_iol_normalized_symbols,
            local_yahoo_failures,
            local_yahoo_negative_cache_hits,
            local_yahoo_known_bad_skips,
            local_yahoo_c_variant_skips,
            local_yahoo_skipped_due_iol_limit,
            maestro_scan_ms,
            maestro_entries,
            maestro_active,
            radar_s,
            usa_price_ms,
            usa_price_from_radar_hits,
            usa_price_fallback_calls,
            usa_price_fallback_failures,
            usa_price_fallback_known_bad_skips,
            usa_enrichment_hits_total_score,
            usa_enrichment_hits_signal_state,
            local_iol_ms,
            local_yahoo_ms,
            row_other_ms,
        )
    )
    logger.info(msg)
    print(msg, file=sys.stderr, flush=True)


def build_cedear_rows_from_latest_radar() -> list[CedearRow] | None:
    """
    None si no hay export radar_*.xlsx.
    Incluye todos los mapeos activos. precio_usa_real: columna Precio de la fila radar USA si existe;
    si no, market_data.get_usa_price (export + Yahoo). TotalScore / SignalState desde fila radar USA
    (Radar_Completo) cuando existe; si no hay fila o dato, null. mod_usa=NO si el ticker no está en el radar.

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
        Siempre: una línea INFO [CEDEAR_TIMING] con desglose de ms por fase (grep CEDEAR_TIMING).
    """
    t0 = time.perf_counter()
    try:
        from services.market_data.providers.iol import clear_iol_negative_cache, reset_iol_quote_usage_stats

        reset_iol_quote_usage_stats()
        clear_iol_negative_cache()
    except Exception:
        pass
    _iol_path_debug_reset()
    yahoo_stats: dict[str, int] = {
        "yahoo_queries": 0,
        "yahoo_cache_hits": 0,
        "local_iol_calls": 0,
        "local_iol_hits": 0,
        "local_iol_misses": 0,
        "local_iol_skipped_by_limit": 0,
        "local_yahoo_fallback_calls": 0,
        "local_iol_normalized_symbols": 0,
        "local_yahoo_failures": 0,
        "local_yahoo_negative_cache_hits": 0,
        "local_yahoo_known_bad_skips": 0,
        "local_yahoo_c_variant_skips": 0,
        "local_yahoo_skipped_due_iol_limit": 0,
        "usa_price_from_radar_hits": 0,
        "usa_price_fallback_calls": 0,
        "usa_price_fallback_failures": 0,
        "usa_price_fallback_known_bad_skips": 0,
        "usa_enrichment_hits_total_score": 0,
        "usa_enrichment_hits_signal_state": 0,
    }

    t_maestro0 = time.perf_counter()
    maestro_entries = len(CEDEAR_MAPPINGS)
    maestro_active = sum(1 for m in CEDEAR_MAPPINGS if m.activo)
    maestro_scan_ms = (time.perf_counter() - t_maestro0) * 1000.0

    t_radar0 = time.perf_counter()
    payload = latest_export.read_latest_radar()
    if payload is None:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        radar_usa_ms = (time.perf_counter() - t_radar0) * 1000.0
        logger.info(
            "cedear_build elapsed_ms=%.1f rows=0 yahoo_queries=0 yahoo_cache_hits=0 (no_export)",
            elapsed_ms,
        )
        _log_cedear_timing_breakdown(
            total_ms=elapsed_ms,
            maestro_scan_ms=maestro_scan_ms,
            maestro_entries=maestro_entries,
            maestro_active=maestro_active,
            radar_usa_ms=radar_usa_ms,
            usa_rows_indexed=None,
            loop_rows=0,
            usa_price_ms=0.0,
            usa_price_from_radar_hits=0,
            usa_price_fallback_calls=0,
            usa_price_fallback_failures=0,
            usa_price_fallback_known_bad_skips=0,
            usa_enrichment_hits_total_score=0,
            usa_enrichment_hits_signal_state=0,
            local_iol_ms=0.0,
            local_yahoo_ms=0.0,
            row_other_ms=0.0,
            yahoo_queries=0,
            yahoo_cache_hits=0,
            local_iol_calls=0,
            local_iol_hits=0,
            local_iol_misses=0,
            local_iol_cache_hits=0,
            local_iol_skipped_by_limit=0,
            local_yahoo_fallback_calls=0,
            local_iol_normalized_symbols=0,
            local_yahoo_failures=0,
            local_yahoo_negative_cache_hits=0,
            local_yahoo_known_bad_skips=0,
            local_yahoo_c_variant_skips=0,
            local_yahoo_skipped_due_iol_limit=0,
            phase_note="no_export",
        )
        return None
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        radar_usa_ms = (time.perf_counter() - t_radar0) * 1000.0
        logger.info(
            "cedear_build elapsed_ms=%.1f rows=0 yahoo_queries=0 yahoo_cache_hits=0 (invalid_rows)",
            elapsed_ms,
        )
        _log_cedear_timing_breakdown(
            total_ms=elapsed_ms,
            maestro_scan_ms=maestro_scan_ms,
            maestro_entries=maestro_entries,
            maestro_active=maestro_active,
            radar_usa_ms=radar_usa_ms,
            usa_rows_indexed=None,
            loop_rows=0,
            usa_price_ms=0.0,
            usa_price_from_radar_hits=0,
            usa_price_fallback_calls=0,
            usa_price_fallback_failures=0,
            usa_price_fallback_known_bad_skips=0,
            usa_enrichment_hits_total_score=0,
            usa_enrichment_hits_signal_state=0,
            local_iol_ms=0.0,
            local_yahoo_ms=0.0,
            row_other_ms=0.0,
            yahoo_queries=0,
            yahoo_cache_hits=0,
            local_iol_calls=0,
            local_iol_hits=0,
            local_iol_misses=0,
            local_iol_cache_hits=0,
            local_iol_skipped_by_limit=0,
            local_yahoo_fallback_calls=0,
            local_iol_normalized_symbols=0,
            local_yahoo_failures=0,
            local_yahoo_negative_cache_hits=0,
            local_yahoo_known_bad_skips=0,
            local_yahoo_c_variant_skips=0,
            local_yahoo_skipped_due_iol_limit=0,
            phase_note="invalid_rows",
        )
        return []

    by_ticker = _usa_row_index(raw_rows)
    radar_usa_ms = (time.perf_counter() - t_radar0) * 1000.0
    usa_rows_indexed = len(by_ticker)

    out: list[CedearRow] = []
    yahoo_cache: dict[str, float | None] = {}
    usa_price_cache: dict[str, float | None] = {}
    yahoo_negative_local: set[str] = set()

    acc_usa_price_ms = 0.0
    acc_local_iol_ms = 0.0
    acc_local_yahoo_ms = 0.0
    acc_row_other_ms = 0.0
    usa_matches = 0
    usa_misses = 0
    ccl_debug_count_holder = [0]

    for m in CEDEAR_MAPPINGS:
        if not m.activo:
            continue
        built, usa_m, iol_m, ly_m, rt_m, um_inc, uM_inc = _build_single_cedear_row(
            m,
            by_ticker=by_ticker,
            yahoo_stats=yahoo_stats,
            yahoo_cache=yahoo_cache,
            usa_price_cache=usa_price_cache,
            yahoo_negative_local=yahoo_negative_local,
            ccl_debug_count_holder=ccl_debug_count_holder,
        )
        out.append(built)
        usa_matches += um_inc
        usa_misses += uM_inc
        acc_usa_price_ms += usa_m
        acc_local_iol_ms += iol_m
        acc_local_yahoo_ms += ly_m
        acc_row_other_ms += rt_m - usa_m - ly_m

    logger.info(
        "[CEDEAR_ENRICH] usa_matches=%s usa_misses=%s",
        usa_matches,
        usa_misses,
    )

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    logger.info(
        "cedear_build elapsed_ms=%.1f rows=%s yahoo_queries=%s yahoo_cache_hits=%s",
        elapsed_ms,
        len(out),
        yahoo_stats["yahoo_queries"],
        yahoo_stats["yahoo_cache_hits"],
    )
    try:
        from services.market_data.providers.iol import get_iol_quote_usage_stats

        _iol_st = get_iol_quote_usage_stats()
        _iol_cache_hits = int(_iol_st.get("iol_cache_positive_hits", 0)) + int(
            _iol_st.get("iol_cache_negative_hits", 0)
        )
    except Exception:
        _iol_cache_hits = 0
    _log_cedear_timing_breakdown(
        total_ms=elapsed_ms,
        maestro_scan_ms=maestro_scan_ms,
        maestro_entries=maestro_entries,
        maestro_active=maestro_active,
        radar_usa_ms=radar_usa_ms,
        usa_rows_indexed=usa_rows_indexed,
        loop_rows=len(out),
        usa_price_ms=acc_usa_price_ms,
        usa_price_from_radar_hits=yahoo_stats.get("usa_price_from_radar_hits", 0),
        usa_price_fallback_calls=yahoo_stats.get("usa_price_fallback_calls", 0),
        usa_price_fallback_failures=yahoo_stats.get("usa_price_fallback_failures", 0),
        usa_price_fallback_known_bad_skips=yahoo_stats.get("usa_price_fallback_known_bad_skips", 0),
        usa_enrichment_hits_total_score=yahoo_stats.get("usa_enrichment_hits_total_score", 0),
        usa_enrichment_hits_signal_state=yahoo_stats.get("usa_enrichment_hits_signal_state", 0),
        local_iol_ms=acc_local_iol_ms,
        local_yahoo_ms=acc_local_yahoo_ms,
        row_other_ms=acc_row_other_ms,
        yahoo_queries=yahoo_stats["yahoo_queries"],
        yahoo_cache_hits=yahoo_stats["yahoo_cache_hits"],
        local_iol_calls=yahoo_stats.get("local_iol_calls", 0),
        local_iol_hits=yahoo_stats.get("local_iol_hits", 0),
        local_iol_misses=yahoo_stats.get("local_iol_misses", 0),
        local_iol_cache_hits=_iol_cache_hits,
        local_iol_skipped_by_limit=yahoo_stats.get("local_iol_skipped_by_limit", 0),
        local_yahoo_fallback_calls=yahoo_stats.get("local_yahoo_fallback_calls", 0),
        local_iol_normalized_symbols=yahoo_stats.get("local_iol_normalized_symbols", 0),
        local_yahoo_failures=yahoo_stats.get("local_yahoo_failures", 0),
        local_yahoo_negative_cache_hits=yahoo_stats.get("local_yahoo_negative_cache_hits", 0),
        local_yahoo_known_bad_skips=yahoo_stats.get("local_yahoo_known_bad_skips", 0),
        local_yahoo_c_variant_skips=yahoo_stats.get("local_yahoo_c_variant_skips", 0),
        local_yahoo_skipped_due_iol_limit=yahoo_stats.get("local_yahoo_skipped_due_iol_limit", 0),
        phase_note=None,
    )
    return out


def _self_test_fuente_cedear_local() -> None:
    """Prueba rápida de etiquetas fuente_cedear (ejecutar desde raíz del repo)."""
    assert _fuente_cedear_local(1.0, 2.0, True, True) == "IOL"
    assert _fuente_cedear_local(1.0, 2.0, False, False) == "Yahoo"
    assert _fuente_cedear_local(1.0, 2.0, True, False) == "IOL/Yahoo"
    assert _fuente_cedear_local(1.0, None, False, False) == "Yahoo"
    assert _fuente_cedear_local(None, 2.0, False, True) == "IOL"
    assert _fuente_cedear_local(None, None, False, False) == "Sin datos"
    assert _fuente_cedear_local(1.0, None, True, False) == "IOL"
