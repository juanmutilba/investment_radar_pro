from __future__ import annotations

from fastapi import FastAPI, HTTPException

from services import latest_export
from services.export_service import export_results
from services.scan_service import run_full_scan

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
        outputs = run_full_scan(verbose=False)
        outputs.pop("previous_file")
        export_results(outputs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    summary = latest_export.read_latest_summary()
    if summary is None:
        raise HTTPException(
            status_code=500,
            detail="Scan completado pero no se pudo leer el resumen del export",
        )

    return {"status": "ok", "summary": summary}


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


@app.get("/latest-radar")
def get_latest_radar():
    payload = latest_export.read_latest_radar()
    if payload is None:
        raise HTTPException(status_code=404, detail="No hay export radar_*.xlsx en la carpeta configurada")
    return payload


@app.get("/latest-radar-argentina")
def get_latest_radar_argentina():
    payload = latest_export.read_latest_radar_argentina()
    if payload is None:
        raise HTTPException(status_code=404, detail="No hay export radar_*.xlsx en la carpeta configurada")
    return payload
