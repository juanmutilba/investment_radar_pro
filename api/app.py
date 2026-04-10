from __future__ import annotations

from fastapi import FastAPI, HTTPException

from services import latest_export
from services.scan_service import run_full_scan

app = FastAPI(title="Investment Radar API", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run-scan")
def run_scan():
    """
    Ejecuta el mismo pipeline que el CLI (sin prints de motores).
    No escribe Excel/CSV; solo devuelve un resumen JSON.
    """
    result = run_full_scan(verbose=False)

    usa_alerts = result["usa_alerts"]
    arg_alerts = result["arg_alerts"]

    usa_alerts_count = len(usa_alerts) if usa_alerts is not None else 0
    arg_alerts_count = len(arg_alerts) if arg_alerts is not None else 0

    prev = result.get("previous_file")
    previous_export = str(prev) if prev is not None else None

    return {
        "usa_alerts_count": usa_alerts_count,
        "arg_alerts_count": arg_alerts_count,
        "usa_tickers_count": len(result["usa_df"]),
        "arg_tickers_count": len(result["arg_df"]),
        "previous_export_used": previous_export,
    }


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
