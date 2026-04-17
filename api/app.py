from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from services import latest_export
from services.alert_event_log import read_alert_events
from services.alerts_analysis import AlertsAnalysisRow, build_alerts_analysis
from services.cedear_service import (
    CedearRow,
    CocosTokenRequired,
    build_cedear_rows_from_latest_radar,
)
from services.cocos_cedear import CocosAuthError
from services.cocos_token_store import set_cocos_api_token
from services.export_service import export_results
from services.scan_service import run_full_scan

app = FastAPI(title="Investment Radar API", version="0.1.0")


class CedearCocosTokenBody(BaseModel):
    token: str = Field(..., min_length=1, description="JWT Apikey / Bearer de la app Cocos (copiado del navegador).")


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


@app.post("/cedears/cocos-token")
def post_cedears_cocos_token(body: CedearCocosTokenBody):
    """
    Guarda en memoria del proceso el token de Cocos para cotizar líneas CEDEAR (ARS/CCL).
    No se persiste en disco.
    """
    set_cocos_api_token(body.token)
    return {"status": "ok"}


@app.get("/cedears", response_model=list[CedearRow], response_model_by_alias=True)
def get_cedears():
    """
    Vista CEDEAR sobre el último Radar USA: precios locales (ARS/USD) + CCL implícito
    y gap vs precio USA del export. Scores y señal se toman del radar sin recalcular.
    Precios CEDEAR locales: Cocos primero (requiere token vía POST /cedears/cocos-token), fallback Yahoo.
    """
    try:
        rows = build_cedear_rows_from_latest_radar()
    except CocosTokenRequired:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "cocos_token_required",
                "message": "Falta el token de Cocos. Ingresalo desde la app (se guarda en memoria en el servidor).",
            },
        ) from None
    except CocosAuthError as e:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "cocos_auth_failed",
                "message": str(e) or "Cocos rechazó el token.",
            },
        ) from None
    if rows is None:
        raise HTTPException(status_code=404, detail="No hay export radar_*.xlsx en la carpeta configurada")
    return rows


@app.get("/latest-radar-argentina")
def get_latest_radar_argentina():
    payload = latest_export.read_latest_radar_argentina()
    if payload is None:
        raise HTTPException(status_code=404, detail="No hay export radar_*.xlsx en la carpeta configurada")
    return payload
