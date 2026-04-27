from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query

from api.portfolio import router as portfolio_router
from persistence.sqlite import init_database
from persistence.sqlite.connection import connection_scope
from persistence.sqlite.scan_runs_repo import (
    finalize_scan_run,
    insert_running_scan_run,
    insert_scan_metrics_row,
    persist_failed_scan_run,
)
from services import latest_export
from services.alert_event_log import read_alert_events
from services.alerts_analysis import AlertsAnalysisRow, build_alerts_analysis
from datetime import datetime, timezone

from data.cedear_mapping import get_active_cedear_usa_tickers, normalize_usa_ticker_for_cedear_lookup
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # .env en la raíz del repo (api/ -> padre); no depender solo del CWD de uvicorn.
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    iol_u_present = bool(os.getenv("IOL_USERNAME", "").strip())
    iol_p_present = bool(os.getenv("IOL_PASSWORD", "").strip())
    iol_enabled_after = False
    try:
        from services.market_data.providers.iol import configure_iol_credentials, is_iol_enabled

        iol_user = os.getenv("IOL_USERNAME", "").strip()
        iol_pass = os.getenv("IOL_PASSWORD", "").strip()
        configure_iol_credentials(iol_user, iol_pass)
        iol_enabled_after = is_iol_enabled()
    except Exception:
        pass
    print(
        "[IOL_STARTUP_DEBUG] username_present=%s password_present=%s enabled_after_config=%s"
        % (iol_u_present, iol_p_present, iol_enabled_after),
        flush=True,
    )
    init_database()
    yield


app = FastAPI(title="Investment Radar API", version="0.1.0", lifespan=lifespan)

app.include_router(portfolio_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run-scan")
def run_scan():
    """
    Misma secuencia que el CLI: scan completo + export Excel/CSV.
    Sin prints de motores (verbose=False). Devuelve estado y resumen leído del export.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    scan_metrics: dict[str, Any] = {}
    run_id: int | None = None

    try:
        with connection_scope() as conn:
            run_id = insert_running_scan_run(conn, started_at, source="api")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo registrar el scan en SQLite: {e}",
        ) from e

    try:
        outputs, scan_metrics = run_full_scan_timed(verbose=False)
        outputs.pop("previous_file")
        export_results(outputs)
    except Exception as e:
        persist_failed_scan_run(run_id, str(e), scan_metrics if scan_metrics else None)
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
        persist_failed_scan_run(
            run_id,
            "Scan completado pero no se pudo leer el resumen del export",
            scan_metrics,
        )
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

    finished_at = datetime.now(timezone.utc).isoformat()
    ep = latest_export.resolve_latest_export_path()
    export_key = str(ep.resolve()) if ep is not None else None
    run_finalized = False
    try:
        with connection_scope() as conn:
            finalize_scan_run(
                conn,
                run_id,
                finished_at=finished_at,
                status="completed",
                export_file=export_key,
                error_message=None,
            )
        run_finalized = True
    except Exception:
        pass
    if run_finalized:
        try:
            with connection_scope() as conn:
                insert_scan_metrics_row(conn, run_id, scan_metrics)
        except Exception:
            pass

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
    events = read_alert_events(limit=limit)
    if not events:
        return events

    cedear_set = get_active_cedear_usa_tickers()
    for ev in events:
        try:
            mercado = str(ev.get("mercado") or "").strip().upper()
        except Exception:
            mercado = ""
        if mercado != "USA":
            ev["CEDEAR"] = None
            continue
        t = ev.get("ticker")
        k = normalize_usa_ticker_for_cedear_lookup(t)
        ev["CEDEAR"] = "SI" if k and k in cedear_set else "NO"
    return events


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
