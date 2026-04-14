from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ALERT_PRIORIDAD

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ALERT_EVENTS_FILE = DATA_DIR / "alert_events.jsonl"


def _ensure_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")


def _norm_mercado(raw: Any, *, fallback: str) -> str:
    s = str(raw or "").strip()
    if not s or s.lower() == "nan":
        return fallback
    up = s.upper()
    if up in {"USA", "US", "UNITED STATES", "NYSE", "NASDAQ", "NMS"}:
        return "USA"
    if up in {"AR", "ARG", "ARGENTINA"}:
        return "Argentina"
    return s


def _get_cell(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            v = row[name]
            if isinstance(v, float) and str(v).lower() == "nan":
                continue
            return v
    return None


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return {k: row.get(k) for k in row.keys()}  # pandas Series
    except Exception:
        return {}


def _build_event(
    *,
    scan_id: str,
    scan_at: str,
    alert_row: dict[str, Any],
    radar_row: dict[str, Any] | None,
    mercado_fallback: str,
) -> dict[str, Any]:
    ticker = _get_cell(alert_row, "Ticker", "ticker")
    tipo_key = _get_cell(alert_row, "tipo_alerta")
    tipo_label = _get_cell(alert_row, "TipoAlerta")

    fingerprint = _get_cell(alert_row, "fingerprint", "Fingerprint")
    motivo = _get_cell(alert_row, "motivo", "Motivo", "reason", "Reason")
    setup = _get_cell(radar_row or {}, "Setup", "setup") if radar_row else None

    universo = _get_cell(radar_row or {}, "Universo", "universo", "TipoUniverso", "tipoUniverso")
    panel = _get_cell(radar_row or {}, "Panel", "panel")

    mercado = _norm_mercado(_get_cell(alert_row, "mercado", "Mercado"), fallback=mercado_fallback)

    prioridad_num = None
    if isinstance(tipo_key, str) and tipo_key in ALERT_PRIORIDAD:
        prioridad_num = int(ALERT_PRIORIDAD[tipo_key])

    prioridad_radar = _get_cell(radar_row or {}, "PrioridadRadar", "prioridad_radar") if radar_row else None

    conviccion = _get_cell(radar_row or {}, "Conviccion", "conviccion", "Conviction") if radar_row else None

    total_score = _get_cell(radar_row or {}, "TotalScore", "total_score", "score") if radar_row else None
    rsi = _get_cell(radar_row or {}, "RSI", "rsi") if radar_row else None
    precio = _get_cell(radar_row or {}, "Precio", "precio") if radar_row else None

    senales = _get_cell(alert_row, "senales_activas", "SenalesActivas", "senalesActivas")

    return {
        "scan_id": scan_id,
        "scan_at": scan_at,
        "ticker": str(ticker).strip() if ticker is not None else None,
        "mercado": mercado,
        "universo": universo,
        "panel": panel,
        "tipo_alerta": tipo_key,
        "tipo_alerta_label": str(tipo_label).strip() if tipo_label is not None else None,
        "prioridad": prioridad_num,
        "prioridad_radar": prioridad_radar,
        "conviccion": conviccion,
        "total_score": total_score,
        "rsi": rsi,
        "precio": precio,
        "setup": setup,
        "motivo": motivo,
        "fingerprint": fingerprint,
        "score": _get_cell(alert_row, "score", "Score"),
        "score_anterior": _get_cell(alert_row, "score_anterior", "ScoreAnterior"),
        "cambio_score": _get_cell(alert_row, "cambio_score", "CambioScore"),
        "senales_activas": senales,
        "mensaje": _get_cell(alert_row, "Mensaje", "mensaje"),
    }


def _radar_index(df: Any) -> dict[str, dict[str, Any]]:
    try:
        import pandas as pd
    except Exception:
        pd = None  # type: ignore[assignment]

    if df is None or pd is None:
        return {}

    try:
        if hasattr(df, "empty") and bool(df.empty):
            return {}
    except Exception:
        return {}

    ticker_col = None
    for c in ("Ticker", "ticker"):
        if hasattr(df, "columns") and c in df.columns:
            ticker_col = c
            break
    if not ticker_col:
        return {}

    out: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        rd = _row_to_dict(row)
        t = rd.get(ticker_col)
        if t is None:
            continue
        key = str(t).strip().upper()
        if key:
            out[key] = rd
    return out


def append_scan_alert_events(
    *,
    scan_id: str,
    usa_alerts: Any,
    arg_alerts: Any,
    usa_df: Any,
    arg_df: Any,
    scan_at: str | None = None,
) -> int:
    """
    Persiste (append-only) un registro por alerta detectada en un scan.

    Usa la lista de alertas ya evaluadas por fila (p. ej. collect_detected_alerts), no el subconjunto
    que pasó cooldown/envío en generate_alerts.

    Returns
    -------
    int
        Cantidad de eventos escritos.
    """
    _ensure_file(ALERT_EVENTS_FILE)

    ts = scan_at or datetime.now(timezone.utc).isoformat()

    usa_idx = _radar_index(usa_df)
    arg_idx = _radar_index(arg_df)

    events: list[dict[str, Any]] = []

    def consume(alerts: Any, idx: dict[str, dict[str, Any]], mercado_fallback: str) -> None:
        if alerts is None:
            return
        rows: list[dict[str, Any]] = []
        try:
            import pandas as pd

            if isinstance(alerts, pd.DataFrame):
                if alerts.empty:
                    return
                rows = alerts.to_dict(orient="records")
            elif isinstance(alerts, list):
                rows = [x for x in alerts if isinstance(x, dict)]
        except Exception:
            if isinstance(alerts, list):
                rows = [x for x in alerts if isinstance(x, dict)]

        for r in rows:
            ar = _row_to_dict(r)
            t = _get_cell(ar, "Ticker", "ticker")
            key = str(t).strip().upper() if t is not None else ""
            radar_row = idx.get(key) if key else None
            events.append(
                _build_event(
                    scan_id=scan_id,
                    scan_at=ts,
                    alert_row=ar,
                    radar_row=radar_row,
                    mercado_fallback=mercado_fallback,
                )
            )

    consume(usa_alerts, usa_idx, "USA")
    consume(arg_alerts, arg_idx, "Argentina")

    if not events:
        return 0

    with ALERT_EVENTS_FILE.open("a", encoding="utf-8", newline="\n") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")

    return len(events)


def read_alert_events(*, limit: int = 500) -> list[dict[str, Any]]:
    """
    Lee los últimos N eventos del log (orden cronológico del archivo: más viejo → más nuevo).
    """
    _ensure_file(ALERT_EVENTS_FILE)
    lim = max(1, min(int(limit), 50_000))

    try:
        lines = ALERT_EVENTS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    tail = lines[-lim:]
    out: list[dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out
