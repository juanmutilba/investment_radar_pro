from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


Tendencia = Literal["subiendo", "bajando", "plano"]
DireccionRegimen = Literal["mejora", "deterioro", "sin_cambio"]


class AlertsAnalysisRow(BaseModel):
    ticker: str
    score_actual: float = Field(..., description="Score del evento más reciente del ticker")
    tipo_actual: str | None = Field(None, description="tipo_alerta del evento más reciente del ticker")
    cantidad_eventos: int
    cantidad_scans: int
    aceleracion: float = Field(..., description="Suma de cambio_score de los últimos 3 eventos del ticker")
    novedad: int = Field(..., description="Fingerprints distintos en los últimos N eventos del ticker")
    recencia_segundos: int = Field(..., description="Segundos desde el último evento hasta ahora")
    recencia_score: float = Field(
        ...,
        description="Puntaje simple derivado de recencia_segundos (más reciente = mayor)",
    )
    cambio_regimen: bool = Field(
        ...,
        description="True si hubo cambio relevante de régimen (compra_* vs venta/toma_ganancia) en eventos recientes",
    )
    direccion_regimen: DireccionRegimen = Field(
        ...,
        description="Dirección del cambio de régimen (mejora/deterioro/sin_cambio)",
    )
    racha_scans: int = Field(
        ...,
        description="Cantidad de scans consecutivos recientes (según el orden del historial) en los que apareció el ticker",
    )
    score_promedio: float
    ranking_score: float
    tendencia: Tendencia


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return ""


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = _to_str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _parse_iso_dt(v: Any) -> datetime | None:
    s = _to_str(v).strip()
    if not s:
        return None
    try:
        # Acepta "Z"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _regimen_for_tipo(tipo_alerta: Any) -> Literal["bull", "bear", "other"]:
    """
    Regímenes operativos simplificados para detectar cambios útiles:
    - bull: compra_potencial / compra_fuerte
    - bear: venta / toma_ganancia
    - other: resto / faltantes
    """
    t = _to_str(tipo_alerta).strip().lower()
    if t in {"compra_potencial", "compra_fuerte"}:
        return "bull"
    if t in {"venta", "toma_ganancia"}:
        return "bear"
    return "other"


def _recencia_score_from_seconds(recencia_segundos: int | None, *, half_life_hours: float = 6.0) -> float:
    """
    Puntaje de recencia simple, estable y fácil de entender:
    score = 10 / (1 + horas / half_life_hours)

    - 0s → 10.0
    - 6h → 5.0
    - 24h → 2.0
    - Eventos sin recencia válida → 0.0 (manejados por el caller)
    """
    if recencia_segundos is None:
        return 0.0
    sec = int(recencia_segundos)
    if sec < 0:
        sec = 0
    h = sec / 3600.0
    denom = 1.0 + (h / max(0.1, float(half_life_hours)))
    return float(10.0 / denom)


def build_alerts_analysis(
    *,
    events: list[dict[str, Any]],
    now: datetime | None = None,
    novelty_last_n: int = 5,
) -> list[AlertsAnalysisRow]:
    """
    Construye un ranking por ticker a partir del historial append-only de eventos.

    - Toma el evento "más reciente" por ticker según el orden del archivo (tail en orden cronológico).
    - novelty_last_n controla cuántos eventos recientes por ticker se usan para medir novedad (fingerprints distintos).
    """
    if not events:
        return []

    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    # Orden global de scan_id según el historial (cronológico).
    global_scan_ids: list[str] = []
    seen_scan: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        sid = _to_str(ev.get("scan_id")).strip()
        if not sid or sid in seen_scan:
            continue
        seen_scan.add(sid)
        global_scan_ids.append(sid)
    global_scan_index = {sid: i for i, sid in enumerate(global_scan_ids)}

    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        t = _to_str(ev.get("ticker")).strip().upper()
        if not t:
            continue
        by_ticker.setdefault(t, []).append(ev)

    out: list[AlertsAnalysisRow] = []

    for ticker, rows in by_ticker.items():
        if not rows:
            continue

        ultimo = rows[-1]
        score_actual = _to_float(ultimo.get("score")) or 0.0
        tipo_actual = _to_str(ultimo.get("tipo_alerta")).strip() or None

        cantidad_eventos = len(rows)
        scans: set[str] = set()
        score_vals: list[float] = []

        last_scan_id = _to_str(ultimo.get("scan_id")).strip() or None

        for r in rows:
            sid = _to_str(r.get("scan_id")).strip()
            if sid:
                scans.add(sid)
            sv = _to_float(r.get("score"))
            if sv is not None:
                score_vals.append(sv)

        cantidad_scans = len(scans)
        score_promedio = (sum(score_vals) / len(score_vals)) if score_vals else 0.0

        ultimos3 = rows[-3:]
        aceleracion = 0.0
        for r in ultimos3:
            aceleracion += _to_float(r.get("cambio_score")) or 0.0

        ultimosN = rows[-max(1, int(novelty_last_n)) :]
        fps: set[str] = set()
        for r in ultimosN:
            fp = _to_str(r.get("fingerprint")).strip()
            if fp:
                fps.add(fp)
        novedad = len(fps)

        last_dt = _parse_iso_dt(ultimo.get("scan_at"))
        recencia_valida = last_dt is not None
        if not recencia_valida:
            recencia_segundos = 0
        else:
            delta = (now_utc - last_dt).total_seconds()
            recencia_segundos = int(max(0.0, delta))

        recencia_score = _recencia_score_from_seconds(recencia_segundos) if recencia_valida else 0.0

        # Cambio de régimen (compra_* <-> venta/toma_ganancia) en eventos recientes.
        cambio_regimen = False
        direccion_regimen: DireccionRegimen = "sin_cambio"
        if len(rows) >= 2:
            recientes = rows[-4:]  # ventana chica y estable
            reg_first = _regimen_for_tipo(recientes[0].get("tipo_alerta"))
            reg_last = _regimen_for_tipo(recientes[-1].get("tipo_alerta"))
            if reg_first != "other" and reg_last != "other" and reg_first != reg_last:
                cambio_regimen = True
                if reg_first == "bear" and reg_last == "bull":
                    direccion_regimen = "mejora"
                elif reg_first == "bull" and reg_last == "bear":
                    direccion_regimen = "deterioro"

        # Racha de scans consecutivos recientes (según orden global del historial leído).
        # Si no hay scan_id, por requisito la racha es al menos 1 si hay eventos.
        racha_scans = 1
        if last_scan_id and global_scan_index and scans:
            idx = global_scan_index.get(last_scan_id)
            if idx is not None:
                streak = 1
                j = idx - 1
                while j >= 0 and global_scan_ids[j] in scans:
                    streak += 1
                    j -= 1
                racha_scans = max(1, streak)

        # Ranking: mantiene la estructura original y agrega recencia con peso bajo.
        ranking_score = (
            (score_actual * 0.35)
            + (aceleracion * 0.3)
            + (float(cantidad_scans) * 0.2)
            + (float(novedad) * 0.1)
            + (float(recencia_score) * 0.05)
        )

        if aceleracion > 0:
            tendencia: Tendencia = "subiendo"
        elif aceleracion < 0:
            tendencia = "bajando"
        else:
            tendencia = "plano"

        out.append(
            AlertsAnalysisRow(
                ticker=ticker,
                score_actual=float(score_actual),
                tipo_actual=tipo_actual,
                cantidad_eventos=int(cantidad_eventos),
                cantidad_scans=int(cantidad_scans),
                aceleracion=float(aceleracion),
                novedad=int(novedad),
                recencia_segundos=int(recencia_segundos),
                recencia_score=float(recencia_score),
                cambio_regimen=bool(cambio_regimen),
                direccion_regimen=direccion_regimen,
                racha_scans=int(max(1, racha_scans)),
                score_promedio=float(score_promedio),
                ranking_score=float(ranking_score),
                tendencia=tendencia,
            )
        )

    out.sort(key=lambda r: r.ranking_score, reverse=True)
    return out

