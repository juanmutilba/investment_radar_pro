from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from services import latest_export
from services.alert_event_log import read_alert_events
from services.alerts_analysis import AlertsAnalysisRow, build_alerts_analysis
from datetime import datetime, timezone

from services.cedear_service import CedearRow, build_cedear_rows_from_latest_radar
from services.cedear_scan_cache import (
    persist_cedear_snapshot_from_models,
    read_cedears_build_meta,
    run_cedear_build_for_scan,
    try_load_cedear_snapshot_rows,
)
from services.export_service import export_results
from services.engine_run_metrics import load_last_scan_metrics, save_last_scan_metrics
from services.scan_service import run_full_scan_timed
import time

app = FastAPI(title="Investment Radar API", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run-scan")
def run_scan():
    """
    Misma secuencia que el CLI: scan completo + export Excel/CSV.
    Sin prints de motores (verbose=False). Devuelve estado y resumen leído del export.
    """
    try:
        outputs, scan_metrics = run_full_scan_timed(verbose=False)
        outputs.pop("previous_file")
        export_results(outputs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    scan_finished_at = str(scan_metrics.get("scan_finished_at") or "")
    try:
        _, cedear_patch = run_cedear_build_for_scan(scan_finished_at=scan_finished_at)
        scan_metrics.update(cedear_patch)
    except Exception:
        scan_metrics.setdefault("cedear_scan_seconds", 0.0)
        scan_metrics.setdefault("cedear_total_activos", 0)
        scan_metrics.setdefault("cedear_alertas", 0)

    t0 = time.perf_counter()
    summary = latest_export.read_latest_summary()
    summary_s = time.perf_counter() - t0
    if summary is None:
        raise HTTPException(
            status_code=500,
            detail="Scan completado pero no se pudo leer el resumen del export",
        )

    scan_metrics["summary_seconds"] = round(summary_s, 3)
    scan_metrics["total_scan_seconds"] = round(
        float(scan_metrics.get("usa_scan_seconds", 0))
        + float(scan_metrics.get("arg_scan_seconds", 0))
        + float(scan_metrics.get("cedear_scan_seconds", 0))
        + float(scan_metrics.get("alerts_seconds", 0)),
        3,
    )
    save_last_scan_metrics(scan_metrics)

    # Compat: mantener summary como antes; agregar scan_metrics consolidado.
    return {"status": "ok", "summary": summary, "scan_metrics": scan_metrics}


@app.get("/latest-summary")
def get_latest_summary():
    summary = latest_export.read_latest_summary()
    if summary is None:
        raise HTTPException(status_code=404, detail="No hay export radar_*.xlsx en la carpeta configurada")
    return summary


@app.get("/latest-alerts")
def get_latest_alerts():
    alerts = latest_export.read_latest_alerts()
    if alerts is None:
        raise HTTPException(status_code=404, detail="No hay export radar_*.xlsx en la carpeta configurada")
    return alerts


@app.get("/alert-history")
def get_alert_history(limit: int = Query(default=500, ge=1, le=50_000)):
    """
    Historial append-only de alertas detectadas por scan (JSONL en disco).
    """
    return read_alert_events(limit=limit)


@app.get("/alerts-analysis", response_model=list[AlertsAnalysisRow])
def get_alerts_analysis(limit: int = Query(default=5000, ge=1, le=50_000)):
    """
    Ranking analítico por ticker (derivado únicamente del historial cargado).
    """
    events = read_alert_events(limit=limit)
    if not events:
        return []
    return build_alerts_analysis(events=events)


@app.get("/latest-radar")
def get_latest_radar():
    payload = latest_export.read_latest_radar()
    if payload is None:
        raise HTTPException(status_code=404, detail="No hay export radar_*.xlsx en la carpeta configurada")
    return payload


@app.get("/cedears", response_model=list[CedearRow], response_model_by_alias=True)
def get_cedears(force: bool = Query(default=False, description="1: reconstruir vía Yahoo y actualizar snapshot")):
    """
    Por defecto sirve el snapshot generado en POST /run-scan (sin nuevas consultas Yahoo).
    Con force=1 reconstruye como antes y persiste snapshot para las siguientes lecturas.
    """
    if not force:
        snap = try_load_cedear_snapshot_rows()
        if snap is not None:
            return snap

    rows = build_cedear_rows_from_latest_radar()
    if rows is None:
        raise HTTPException(status_code=404, detail="No hay export radar_*.xlsx en la carpeta configurada")

    m = load_last_scan_metrics()
    scan_at = str(m.get("scan_finished_at") or "").strip() if m else ""
    if not scan_at:
        scan_at = datetime.now(timezone.utc).isoformat()

    ep = latest_export.resolve_latest_export_path()
    export_key = str(ep.resolve()) if ep is not None else None
    persist_cedear_snapshot_from_models(
        scan_finished_at=scan_at,
        built=rows,
        source_export_file=export_key,
    )
    return rows


@app.get("/cedears/build-meta")
def get_cedears_build_meta():
    """
    Meta del último armado CEDEAR persistido por /run-scan (sin filas; para invalidar cache FE).
    """
    meta = read_cedears_build_meta()
    if meta is None:
        raise HTTPException(status_code=404, detail="No hay snapshot CEDEAR (ejecutar scan)")
    return {
        "scan_finished_at": meta.get("scan_finished_at"),
        "source_export_file": meta.get("source_export_file"),
        "row_count": meta.get("row_count"),
        "cedear_alertas": meta.get("cedear_alertas"),
    }


@app.get("/latest-radar-argentina")
def get_latest_radar_argentina():
    payload = latest_export.read_latest_radar_argentina()
    if payload is None:
        raise HTTPException(status_code=404, detail="No hay export radar_*.xlsx en la carpeta configurada")
    return payload
