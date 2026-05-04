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
import threading
import subprocess
import sys
import json as _json



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


# --- Eventos USA (cache updater) ---
_USA_EVENTS_LOCK = threading.Lock()
_ESTIMATED_USA_EVENTS_UPDATE_S = 600.0

_USA_EVENTS_UPDATE: dict[str, Any] = {
    "status": "idle",  # idle | running | success | error
    "started_at": None,
    "finished_at": None,
    "message": None,
    "error": None,
    "last_updated_at": None,
    "progress_pct": 0.0,
    "progress_message": "Listo para actualizar",
}


def _events_cache_usa_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "events_cache_usa.json"


def _parse_utc_iso(s: Any) -> datetime | None:
    if s is None or not isinstance(s, str):
        return None
    t = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _running_progress_message(pct: float) -> str:
    if pct < 10:
        return "Iniciando actualización..."
    if pct < 40:
        return "Consultando eventos..."
    if pct < 75:
        return "Procesando dividendos y earnings..."
    return "Guardando cache..."


def _apply_usa_events_progress_locked() -> None:
    """
    Actualiza last_updated_at desde cache y progress_* según status (lock ya tomado).
    """
    _USA_EVENTS_UPDATE["last_updated_at"] = _compute_last_updated_at_from_cache()
    st = str(_USA_EVENTS_UPDATE.get("status") or "idle")

    if st == "idle":
        _USA_EVENTS_UPDATE["progress_pct"] = 0.0
        _USA_EVENTS_UPDATE["progress_message"] = "Listo para actualizar"
        return
    if st == "running":
        start = _parse_utc_iso(_USA_EVENTS_UPDATE.get("started_at"))
        now = datetime.now(timezone.utc)
        if start is None:
            pct = 0.0
        else:
            elapsed = (now - start).total_seconds()
            pct = min(95.0, max(0.0, elapsed / _ESTIMATED_USA_EVENTS_UPDATE_S * 100.0))
        _USA_EVENTS_UPDATE["progress_pct"] = round(pct, 1)
        _USA_EVENTS_UPDATE["progress_message"] = _running_progress_message(pct)
        return
    if st == "success":
        _USA_EVENTS_UPDATE["progress_pct"] = 100.0
        _USA_EVENTS_UPDATE["progress_message"] = "Eventos actualizados correctamente."
        return
    if st == "error":
        _USA_EVENTS_UPDATE["progress_message"] = "No se pudo actualizar eventos"
        p = _USA_EVENTS_UPDATE.get("progress_pct")
        if isinstance(p, (int, float)):
            return
        start = _parse_utc_iso(_USA_EVENTS_UPDATE.get("started_at"))
        end = _parse_utc_iso(_USA_EVENTS_UPDATE.get("finished_at")) or datetime.now(timezone.utc)
        if start is None:
            pct = 0.0
        else:
            elapsed = (end - start).total_seconds()
            pct = min(95.0, max(0.0, elapsed / _ESTIMATED_USA_EVENTS_UPDATE_S * 100.0))
        _USA_EVENTS_UPDATE["progress_pct"] = round(pct, 1)


def _compute_last_updated_at_from_cache() -> str | None:
    """
    1) Intenta max(updated_at) dentro de data/events_cache_usa.json
    2) Fallback: mtime del archivo (UTC)
    """
    p = _events_cache_usa_path()
    if not p.exists():
        return None
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except Exception:
        raw = ""
    if raw:
        try:
            obj = _json.loads(raw)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            best: str | None = None
            for _, v in obj.items():
                if not isinstance(v, dict):
                    continue
                u = v.get("updated_at")
                if isinstance(u, str) and u.strip():
                    # ISO comparable lexicográficamente cuando es UTC con Z
                    if best is None or u > best:
                        best = u
            if best is not None:
                return best
    try:
        ts = p.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return None


def _run_usa_events_cache_update_bg() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "tools" / "update_usa_events_cache.py"
    started_at = datetime.now(timezone.utc).isoformat()
    with _USA_EVENTS_LOCK:
        _USA_EVENTS_UPDATE.update(
            {
                "status": "running",
                "started_at": started_at,
                "finished_at": None,
                "message": "Actualizando eventos USA…",
                "error": None,
                "last_updated_at": _compute_last_updated_at_from_cache(),
                "progress_pct": 0.0,
                "progress_message": "Iniciando actualización...",
            }
        )

    try:
        if not script.exists():
            raise RuntimeError(f"Script no encontrado: {script}")
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        finished_at = datetime.now(timezone.utc).isoformat()
        if proc.returncode != 0:
            err_txt = (proc.stderr or "").strip() or (proc.stdout or "").strip()
            raise RuntimeError(f"exit_code={proc.returncode} {err_txt[:4000]}")
        with _USA_EVENTS_LOCK:
            _USA_EVENTS_UPDATE.update(
                {
                    "status": "success",
                    "finished_at": finished_at,
                    "message": "Eventos USA actualizados correctamente.",
                    "error": None,
                    "last_updated_at": _compute_last_updated_at_from_cache(),
                    "progress_pct": 100.0,
                    "progress_message": "Eventos actualizados correctamente.",
                }
            )
    except Exception as e:
        finished_at = datetime.now(timezone.utc).isoformat()
        start_dt = _parse_utc_iso(started_at)
        end_dt = _parse_utc_iso(finished_at)
        if start_dt is not None and end_dt is not None:
            elapsed = (end_dt - start_dt).total_seconds()
            err_pct = min(95.0, max(0.0, elapsed / _ESTIMATED_USA_EVENTS_UPDATE_S * 100.0))
        else:
            err_pct = 0.0
        with _USA_EVENTS_LOCK:
            _USA_EVENTS_UPDATE.update(
                {
                    "status": "error",
                    "finished_at": finished_at,
                    "message": "Falló la actualización de eventos USA.",
                    "error": f"{type(e).__name__}: {e}",
                    "last_updated_at": _compute_last_updated_at_from_cache(),
                    "progress_pct": round(err_pct, 1),
                    "progress_message": "No se pudo actualizar eventos",
                }
            )


# --- Scan en background (Dashboard) ---
_SCAN_RUN_LOCK = threading.Lock()
_ESTIMATED_SCAN_S = 300.0

_SCAN_RUN_STATE: dict[str, Any] = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "message": None,
    "error": None,
    "progress_pct": 0.0,
    "progress_message": "Listo para ejecutar scan",
    "last_scan_at": None,
}


def _scan_running_progress_message(pct: float) -> str:
    if pct < 10:
        return "Iniciando scan..."
    if pct < 40:
        return "Analizando acciones USA..."
    if pct < 70:
        return "Analizando acciones Argentina..."
    if pct < 90:
        return "Procesando alertas..."
    return "Generando export..."


def _apply_scan_run_progress_locked() -> None:
    st = str(_SCAN_RUN_STATE.get("status") or "idle")
    if st == "idle":
        _SCAN_RUN_STATE["progress_pct"] = 0.0
        _SCAN_RUN_STATE["progress_message"] = "Listo para ejecutar scan"
        return
    if st == "running":
        start = _parse_utc_iso(_SCAN_RUN_STATE.get("started_at"))
        now = datetime.now(timezone.utc)
        if start is None:
            pct = 0.0
        else:
            elapsed = (now - start).total_seconds()
            pct = min(95.0, max(0.0, elapsed / _ESTIMATED_SCAN_S * 100.0))
        _SCAN_RUN_STATE["progress_pct"] = round(pct, 1)
        _SCAN_RUN_STATE["progress_message"] = _scan_running_progress_message(pct)
        return
    if st == "success":
        _SCAN_RUN_STATE["progress_pct"] = 100.0
        _SCAN_RUN_STATE["progress_message"] = "Scan ejecutado correctamente."
        return
    if st == "error":
        _SCAN_RUN_STATE["progress_message"] = "No se pudo completar el scan"
        p = _SCAN_RUN_STATE.get("progress_pct")
        if isinstance(p, (int, float)):
            return
        start = _parse_utc_iso(_SCAN_RUN_STATE.get("started_at"))
        end = _parse_utc_iso(_SCAN_RUN_STATE.get("finished_at")) or datetime.now(timezone.utc)
        if start is None:
            pct = 0.0
        else:
            elapsed = (end - start).total_seconds()
            pct = min(95.0, max(0.0, elapsed / _ESTIMATED_SCAN_S * 100.0))
        _SCAN_RUN_STATE["progress_pct"] = round(pct, 1)


def _perform_full_run_scan(run_id: int) -> dict[str, Any]:
    """
    Pipeline completo + export (misma lógica que POST /run-scan).
    """
    scan_metrics: dict[str, Any] = {}
    try:
        outputs, scan_metrics = run_full_scan_timed(verbose=False)
        outputs.pop("previous_file")
        export_results(outputs)
    except Exception as e:
        persist_failed_scan_run(run_id, str(e), scan_metrics if scan_metrics else None)
        raise

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
        raise RuntimeError("Scan completado pero no se pudo leer el resumen del export")

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

    return {"status": "ok", "summary": summary, "scan_metrics": scan_metrics}


def _run_full_scan_bg(started_at: str) -> None:
    run_id: int | None = None
    try:
        with connection_scope() as conn:
            run_id = insert_running_scan_run(conn, started_at, source="api")
    except Exception as e:
        finished_at = datetime.now(timezone.utc).isoformat()
        with _SCAN_RUN_LOCK:
            _SCAN_RUN_STATE.update(
                {
                    "status": "error",
                    "finished_at": finished_at,
                    "message": "No se pudo registrar el scan",
                    "error": str(e),
                    "progress_pct": 0.0,
                    "progress_message": "No se pudo iniciar el scan",
                }
            )
        return

    try:
        _perform_full_run_scan(run_id)
    except Exception as e:
        finished_at = datetime.now(timezone.utc).isoformat()
        start_dt = _parse_utc_iso(started_at)
        end_dt = _parse_utc_iso(finished_at)
        if start_dt is not None and end_dt is not None:
            err_pct = min(95.0, max(0.0, (end_dt - start_dt).total_seconds() / _ESTIMATED_SCAN_S * 100.0))
        else:
            err_pct = 0.0
        with _SCAN_RUN_LOCK:
            _SCAN_RUN_STATE.update(
                {
                    "status": "error",
                    "finished_at": finished_at,
                    "message": "Falló el scan",
                    "error": str(e),
                    "progress_pct": round(err_pct, 1),
                    "progress_message": "No se pudo completar el scan",
                }
            )
        return

    finished_at = datetime.now(timezone.utc).isoformat()
    with _SCAN_RUN_LOCK:
        _SCAN_RUN_STATE.update(
            {
                "status": "success",
                "finished_at": finished_at,
                "message": "Scan ejecutado correctamente.",
                "error": None,
                "progress_pct": 100.0,
                "progress_message": "Scan ejecutado correctamente.",
                "last_scan_at": finished_at,
            }
        )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/options/iol/raw/{symbol}")
def iol_options_raw(symbol: str):
    """
    Inspección RAW: lista de opciones IOL para un subyacente ByMA (sin persistir ni transformar).
    """
    from services.market_data.providers.iol import IolOptionsRawError, get_iol_options_raw

    try:
        return get_iol_options_raw(symbol)
    except IolOptionsRawError as e:
        if getattr(e, "iol_resource_401", False):
            raise HTTPException(
                status_code=401,
                detail=(
                    "IOL rechazó el recurso de opciones con 401. La autenticación funciona para cotizaciones, "
                    "pero opciones parece restringido o usa otro endpoint."
                ),
            ) from e
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@app.post("/run-scan")
def run_scan():
    """
    Misma secuencia que el CLI: scan completo + export Excel/CSV.
    Sin prints de motores (verbose=False). Devuelve estado y resumen leído del export.
    """
    started_at = datetime.now(timezone.utc).isoformat()
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
        return _perform_full_run_scan(run_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/scan/run")
def trigger_scan_run():
    """
    Dispara el scan en background. Si ya está corriendo, devuelve el estado actual.
    """
    with _SCAN_RUN_LOCK:
        if str(_SCAN_RUN_STATE.get("status") or "idle") == "running":
            _apply_scan_run_progress_locked()
            return dict(_SCAN_RUN_STATE)
        started_at = datetime.now(timezone.utc).isoformat()
        prev_last = _SCAN_RUN_STATE.get("last_scan_at")
        _SCAN_RUN_STATE.update(
            {
                "status": "running",
                "started_at": started_at,
                "finished_at": None,
                "message": "Ejecutando scan…",
                "error": None,
                "progress_pct": 0.0,
                "progress_message": "Iniciando scan...",
                "last_scan_at": prev_last,
            }
        )
        t = threading.Thread(target=_run_full_scan_bg, args=(started_at,), daemon=True)
        t.start()
        _apply_scan_run_progress_locked()
        return dict(_SCAN_RUN_STATE)


@app.get("/scan/status")
def get_scan_status():
    with _SCAN_RUN_LOCK:
        _apply_scan_run_progress_locked()
        return dict(_SCAN_RUN_STATE)


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


@app.post("/events/usa/update")
def trigger_update_events_usa():
    """
    Dispara actualización de data/events_cache_usa.json en background.
    No bloquea. Si ya está running, devuelve el estado actual.
    """
    with _USA_EVENTS_LOCK:
        st = str(_USA_EVENTS_UPDATE.get("status") or "idle")
        if st == "running":
            _apply_usa_events_progress_locked()
            return dict(_USA_EVENTS_UPDATE)
        # lanzar thread
        t = threading.Thread(target=_run_usa_events_cache_update_bg, daemon=True)
        t.start()
        _apply_usa_events_progress_locked()
        return dict(_USA_EVENTS_UPDATE)


@app.get("/events/usa/update-status")
def get_update_events_usa_status():
    with _USA_EVENTS_LOCK:
        _apply_usa_events_progress_locked()
        return dict(_USA_EVENTS_UPDATE)
