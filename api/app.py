from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

# Cargar .env al importar (no solo en lifespan): uvicorn puede arrancar antes del lifespan
# y dotenv por defecto no pisa variables ya definidas en el proceso.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.is_file():
    load_dotenv(_ENV_FILE, override=True)

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

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
    if _ENV_FILE.is_file():
        load_dotenv(_ENV_FILE, override=True)

    iol_u_present = bool(os.getenv("IOL_USERNAME", "").strip())
    iol_p_present = bool(os.getenv("IOL_PASSWORD", "").strip())
    iol_enabled_after = False
    try:
        from services.market_data.providers.iol import ensure_iol_credentials_from_env, is_iol_enabled

        ensure_iol_credentials_from_env()
        iol_enabled_after = is_iol_enabled()
    except Exception as ex:
        print(
            f"[IOL_STARTUP_DEBUG] ensure_iol_credentials_failed={type(ex).__name__}: {ex}",
            flush=True,
        )
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


@app.get("/crypto/status")
def crypto_status():
    """Estado de configuración Binance/ccxt (sin secretos; puede intentar leer balance)."""
    from services.crypto.providers.binance_provider import crypto_status_payload

    return crypto_status_payload()


@app.get("/crypto/testnet/status")
def crypto_testnet_status():
    """Estado Binance Spot Testnet (capa separada; sin secretos)."""
    from services.crypto import binance_testnet as tn

    return tn.get_testnet_status()


@app.get("/crypto/testnet/auth-debug")
def crypto_testnet_auth_debug():
    """Diagnóstico firma/tiempo sólo si CRYPTO_TESTNET_DEBUG=true (default off)."""
    from services.crypto import binance_testnet as tn

    if not tn.is_testnet_auth_debug_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    return tn.get_testnet_auth_debug()


@app.get("/crypto/testnet/balances")
def crypto_testnet_balances():
    """Balances spot testnet (solo lectura)."""
    from services.crypto import binance_testnet as tn

    return tn.get_testnet_balances()


@app.get("/crypto/testnet/positions")
def crypto_testnet_positions():
    """Posiciones spot valorizadas desde Binance Spot Testnet (balances + tickers); no historial local."""
    from services.crypto import binance_testnet as tn

    return tn.get_testnet_positions()


@app.get("/crypto/testnet/open-orders")
def crypto_testnet_open_orders(
    symbol: str | None = Query(
        None,
        description="Par CCXT en whitelist (ej. BTC/USDT). Si se omite, se consultan todos los pares permitidos.",
    ),
):
    """Órdenes abiertas spot testnet desde Binance (solo lectura); no archivo local."""
    from services.crypto import binance_testnet as tn

    raw = (symbol or "").strip()
    return tn.get_testnet_open_orders(raw if raw else None)


@app.get("/crypto/testnet/ticker")
def crypto_testnet_ticker(
    symbol: str = Query("BTC/USDT", min_length=3, description="Par spot CCXT, ej. BTC/USDT"),
):
    """Ticker spot testnet (sandbox; solo lectura)."""
    from services.crypto import binance_testnet as tn

    try:
        return tn.get_testnet_ticker(symbol.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Binance testnet: {e}") from e


class CryptoTestnetMarketOrderBody(BaseModel):
    """Spot market testnet: BUY por USDT (máx. 25) o SELL por cantidad base o ~USDT a liquidar. Sandbox únicamente."""

    symbol: str = Field(..., min_length=3, max_length=24)
    side: Literal["buy", "sell"]
    quote_amount_usdt: float | None = Field(default=None, description="BUY: monto USDT (máx. 25)")
    amount_base: float | None = Field(default=None, description="SELL avanzado: cantidad del activo base")
    sell_quote_amount_usdt: float | None = Field(default=None, description="SELL recomendado: ~USDT a recibir al vender")

    @model_validator(mode="after")
    def check_side_fields(self) -> "CryptoTestnetMarketOrderBody":
        if self.side == "buy":
            if self.quote_amount_usdt is None:
                raise ValueError("BUY requiere quote_amount_usdt")
            q = float(self.quote_amount_usdt)
            if q < 0.01:
                raise ValueError("quote_amount_usdt debe ser ≥ 0.01")
            if q > 25:
                raise ValueError("quote_amount_usdt máximo 25 USDT por orden")
            if self.amount_base is not None or self.sell_quote_amount_usdt is not None:
                raise ValueError("BUY no admite amount_base ni sell_quote_amount_usdt")
        else:
            has_base = self.amount_base is not None
            has_sq = self.sell_quote_amount_usdt is not None
            if has_base and has_sq:
                raise ValueError("SELL: usá cantidad base o sell_quote_amount_usdt, no ambos")
            if not has_base and not has_sq:
                raise ValueError("SELL requiere amount_base o sell_quote_amount_usdt")
            if self.quote_amount_usdt is not None:
                raise ValueError("SELL no admite quote_amount_usdt")
            if has_base:
                if float(self.amount_base) <= 0:
                    raise ValueError("amount_base debe ser > 0")
            else:
                sq = float(self.sell_quote_amount_usdt)
                if sq < 0.01:
                    raise ValueError("sell_quote_amount_usdt debe ser ≥ 0.01")
                if sq > 25:
                    raise ValueError("sell_quote_amount_usdt máximo 25 USDT por orden")
        return self


@app.post("/crypto/testnet/order/market")
def crypto_testnet_market_order(body: CryptoTestnetMarketOrderBody):
    """Spot market testnet: BUY (USDT) o SELL (base o ~USDT); whitelist; sandbox."""
    from services.crypto import binance_testnet as tn

    try:
        r = tn.place_testnet_market_order(
            body.symbol.strip(),
            str(body.side),
            body.quote_amount_usdt,
            amount_base=body.amount_base,
            sell_quote_amount_usdt=body.sell_quote_amount_usdt,
        )
    except Exception as e:
        msg = str(e).strip()
        if len(msg) > 600:
            msg = msg[:600] + "…"
        raise HTTPException(status_code=502, detail=msg or type(e).__name__) from e

    if not r.get("ok"):
        code = int(r.get("http_status") or 502)
        if code not in (400, 502, 503):
            code = 502
        raise HTTPException(
            status_code=code,
            detail=str(r.get("error") or "Error testnet"),
        )
    return {"ok": True, "order": r.get("order")}


@app.get("/crypto/testnet/orders")
def crypto_testnet_orders(limit: int = Query(50, ge=1, le=500)):
    """Historial local de órdenes enviadas desde esta app (data/crypto_testnet_orders.json)."""
    from services.crypto import binance_testnet as tn

    return tn.get_testnet_order_history(limit)


@app.get("/crypto/ticker")
def crypto_ticker(
    symbol: str = Query(..., min_length=3, description="Par spot CCXT, ej. BTC/USDT"),
):
    """Ticker spot vía Binance (ccxt); solo lectura."""
    from services.crypto.providers import binance_provider as bp

    try:
        return bp.fetch_ticker(symbol.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Binance/ccxt: {e}") from e


@app.get("/crypto/ohlcv")
def crypto_ohlcv(
    symbol: str = Query(..., min_length=3, description="Par spot CCXT, ej. BTC/USDT"),
    timeframe: str = Query("1h", min_length=1, max_length=16),
    limit: int = Query(100, ge=1, le=1000),
):
    """OHLCV spot vía Binance (ccxt); solo lectura."""
    from services.crypto.providers import binance_provider as bp

    try:
        rows = bp.fetch_ohlcv(symbol.strip(), timeframe=timeframe.strip(), limit=limit)
        return {"symbol": symbol.strip(), "timeframe": timeframe.strip(), "limit": limit, "candles": rows}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Binance/ccxt: {e}") from e


@app.get("/crypto/analysis")
def crypto_analysis(
    symbol: str = Query(..., min_length=3, description="Par spot CCXT, ej. BTC/USDT"),
    timeframe: str = Query("1h", min_length=1, max_length=16),
    limit: int = Query(200, ge=50, le=1000),
):
    """Indicadores técnicos sobre OHLCV (solo lectura; sin órdenes)."""
    from services.crypto.providers import binance_provider as bp
    from services.crypto.signals import MIN_OHLCV_ROWS, analyze_ohlcv

    sym = symbol.strip()
    tf = timeframe.strip()
    print(f"[CRYPTO] /crypto/analysis symbol={sym} timeframe={tf} limit={limit}", flush=True)
    try:
        candles = bp.fetch_ohlcv(sym, timeframe=tf, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Binance/ccxt: {e}") from e

    if len(candles) < MIN_OHLCV_ROWS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Velas insuficientes para el análisis: se recibieron {len(candles)}; "
                f"se requieren al menos {MIN_OHLCV_ROWS} (SMA50, MACD, RSI)."
            ),
        )

    try:
        analysis = analyze_ohlcv(candles)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {"symbol": sym, "timeframe": tf, "limit": limit, "analysis": analysis}


@app.get("/crypto/watchlist")
def crypto_watchlist():
    """Pares incluidos en el scanner cripto."""
    from services.crypto.watchlist import get_crypto_watchlist

    symbols = get_crypto_watchlist()
    return {"symbols": symbols, "count": len(symbols)}


@app.get("/crypto/scan")
def crypto_scan(
    timeframe: str = Query("1h", min_length=1, max_length=16),
    limit: int = Query(200, ge=50, le=1000),
):
    """Scanner multi-activo: ranking por score (errores al final). Solo lectura."""
    from services.crypto.watchlist import scan_crypto_watchlist

    tf = timeframe.strip()
    print(f"[CRYPTO_SCAN] /crypto/scan timeframe={tf} limit={limit}", flush=True)
    try:
        results = scan_crypto_watchlist(timeframe=tf, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Scanner cripto: {e}") from e
    return {"timeframe": tf, "limit": limit, "results": results}


class CryptoPaperOpenBody(BaseModel):
    symbol: str = Field(..., min_length=3)
    side: str = Field(default="long")
    price: float = Field(..., gt=0)
    quantity: float = Field(..., gt=0)
    reason: str = ""


class CryptoPaperOpenMarketBody(BaseModel):
    symbol: str = Field(..., min_length=3)
    side: str = Field(default="long")
    quantity: float = Field(..., gt=0)
    reason: str = ""
    stop_loss_pct: float = Field(default=0, ge=0)
    take_profit_pct: float = Field(default=0, ge=0)
    trailing_stop_pct: float = Field(default=0, ge=0)
    break_even_trigger_pct: float = Field(default=0, ge=0)
    break_even_plus_pct: float = Field(default=0, ge=0)


class CryptoPaperOpenMarketAmountBody(BaseModel):
    symbol: str = Field(..., min_length=3)
    side: str = Field(default="long")
    amount_usdt: float = Field(..., gt=0)
    reason: str = ""
    stop_loss_pct: float = Field(default=0, ge=0)
    take_profit_pct: float = Field(default=0, ge=0)
    trailing_stop_pct: float = Field(default=0, ge=0)
    break_even_trigger_pct: float = Field(default=0, ge=0)
    break_even_plus_pct: float = Field(default=0, ge=0)


class CryptoPaperCloseBody(BaseModel):
    position_id: str = Field(..., min_length=1)
    price: float = Field(..., gt=0)
    reason: str = ""


class CryptoPaperBotAutoStartBody(BaseModel):
    exits_interval_minutes: float = Field(default=5, gt=0)
    strategy_interval_minutes: float = Field(default=30, gt=0)
    timeframe: str = "1h"
    limit: int = Field(default=200, ge=50, le=1000)
    amount_usdt: float = Field(default=100, gt=0)
    stop_loss_pct: float = Field(default=2, ge=0)
    take_profit_pct: float = Field(default=4, ge=0)
    trailing_stop_pct: float = Field(default=1.5, ge=0)
    max_open_positions: int = Field(default=3, ge=1, le=50)
    break_even_trigger_pct: float = Field(default=0, ge=0)
    break_even_plus_pct: float = Field(default=0, ge=0)
    cooldown_minutes: int = Field(default=0, ge=0)
    require_btc_trend_up: bool = False
    min_entry_score: float = Field(default=0, ge=0, le=100)


@app.get("/crypto/paper/portfolio")
def crypto_paper_portfolio_get():
    """Cartera paper cripto (simulación local; sin órdenes Binance)."""
    from services.crypto.paper_portfolio import get_paper_portfolio

    return get_paper_portfolio()


@app.get("/crypto/paper/metrics")
def crypto_paper_metrics_get():
    """Métricas de trades cerrados paper (simulación local)."""
    from services.crypto.paper_portfolio import get_paper_trade_metrics

    return get_paper_trade_metrics()


@app.get("/crypto/paper/equity-curve")
def crypto_paper_equity_curve_get():
    """Curva de equity y drawdown de trades cerrados paper."""
    from services.crypto.paper_portfolio import get_paper_equity_curve

    return get_paper_equity_curve()


@app.post("/crypto/paper/reset")
def crypto_paper_portfolio_reset(initial_cash: float = Query(10000, ge=0)):
    from services.crypto.paper_portfolio import get_paper_portfolio, reset_paper_portfolio

    try:
        reset_paper_portfolio(initial_cash=initial_cash)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return get_paper_portfolio()


@app.post("/crypto/paper/open")
def crypto_paper_open(body: CryptoPaperOpenBody):
    from services.crypto.paper_portfolio import get_paper_portfolio, open_paper_position

    try:
        open_paper_position(
            symbol=body.symbol,
            side=body.side,
            price=body.price,
            quantity=body.quantity,
            reason=body.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return get_paper_portfolio()


@app.post("/crypto/paper/open-market")
def crypto_paper_open_market(body: CryptoPaperOpenMarketBody):
    from services.crypto.paper_portfolio import get_paper_portfolio, open_paper_position_market

    try:
        open_paper_position_market(
            symbol=body.symbol,
            side=body.side,
            quantity=body.quantity,
            reason=body.reason,
            stop_loss_pct=body.stop_loss_pct if body.stop_loss_pct > 0 else None,
            take_profit_pct=body.take_profit_pct if body.take_profit_pct > 0 else None,
            trailing_stop_pct=body.trailing_stop_pct if body.trailing_stop_pct > 0 else None,
            break_even_trigger_pct=body.break_even_trigger_pct
            if body.break_even_trigger_pct > 0
            else None,
            break_even_plus_pct=body.break_even_plus_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ticker Binance: {e}") from e
    return get_paper_portfolio()


@app.post("/crypto/paper/open-market-amount")
def crypto_paper_open_market_amount(body: CryptoPaperOpenMarketAmountBody):
    from services.crypto.paper_portfolio import get_paper_portfolio, open_paper_position_market_by_amount

    try:
        open_paper_position_market_by_amount(
            symbol=body.symbol,
            side=body.side,
            amount_usdt=body.amount_usdt,
            reason=body.reason,
            stop_loss_pct=body.stop_loss_pct if body.stop_loss_pct > 0 else None,
            take_profit_pct=body.take_profit_pct if body.take_profit_pct > 0 else None,
            trailing_stop_pct=body.trailing_stop_pct if body.trailing_stop_pct > 0 else None,
            break_even_trigger_pct=body.break_even_trigger_pct
            if body.break_even_trigger_pct > 0
            else None,
            break_even_plus_pct=body.break_even_plus_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ticker Binance: {e}") from e
    return get_paper_portfolio()


@app.get("/crypto/bot/paper-cycle")
def crypto_bot_paper_cycle(
    timeframe: str = Query("1h"),
    limit: int = Query(200, ge=50, le=1000),
):
    """Ciclo bot paper (solo evaluación; sin trading real ni acciones automáticas)."""
    from services.crypto.bot_runner import run_crypto_paper_cycle

    try:
        return run_crypto_paper_cycle(timeframe=timeframe, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Bot paper cycle: {e}") from e


@app.post("/crypto/bot/review-paper-exits")
def crypto_bot_review_paper_exits():
    """Revisa SL/TP/trailing y cierra posiciones paper que cumplan reglas de salida."""
    from services.crypto.paper_portfolio import review_paper_positions_for_exit

    try:
        actions = review_paper_positions_for_exit()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Revisión salidas paper: {e}") from e
    return {"actions": actions}


@app.post("/crypto/bot/execute-paper-strategy")
def crypto_bot_execute_paper_strategy(
    timeframe: str = Query("1h"),
    limit: int = Query(200, ge=50, le=1000),
    amount_usdt: float = Query(100, gt=0),
    stop_loss_pct: float = Query(2, ge=0),
    take_profit_pct: float = Query(4, ge=0),
    trailing_stop_pct: float = Query(1.5, ge=0),
    max_open_positions: int = Query(3, ge=1, le=50),
    break_even_trigger_pct: float = Query(0, ge=0),
    break_even_plus_pct: float = Query(0, ge=0),
    cooldown_minutes: int = Query(0, ge=0),
    require_btc_trend_up: bool = Query(False),
    min_entry_score: float = Query(0, ge=0, le=100),
):
    """Ejecuta estrategia paper con gestión de riesgo (simulación; sin órdenes reales)."""
    from services.crypto.bot_runner import execute_paper_strategy

    try:
        return execute_paper_strategy(
            timeframe=timeframe,
            limit=limit,
            amount_usdt=amount_usdt,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            trailing_stop_pct=trailing_stop_pct,
            max_open_positions=max_open_positions,
            break_even_trigger_pct=break_even_trigger_pct,
            break_even_plus_pct=break_even_plus_pct,
            cooldown_minutes=cooldown_minutes,
            require_btc_trend_up=require_btc_trend_up,
            min_entry_score=min_entry_score,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Estrategia paper: {e}") from e


@app.get("/crypto/bot/auto-status")
def crypto_bot_auto_status():
    """Estado del auto-run paper (memoria; no persiste)."""
    from services.crypto.paper_bot_scheduler import get_paper_bot_scheduler_status

    return get_paper_bot_scheduler_status()


@app.post("/crypto/bot/auto-start")
def crypto_bot_auto_start(body: CryptoPaperBotAutoStartBody):
    """Inicia auto-run paper: revisión de salidas y estrategia por intervalos."""
    from services.crypto.paper_bot_scheduler import start_paper_bot_scheduler

    exits_s = max(60, int(body.exits_interval_minutes * 60))
    strategy_s = max(60, int(body.strategy_interval_minutes * 60))
    strategy_params = {
        "timeframe": (body.timeframe or "1h").strip() or "1h",
        "limit": body.limit,
        "amount_usdt": body.amount_usdt,
        "stop_loss_pct": body.stop_loss_pct,
        "take_profit_pct": body.take_profit_pct,
        "trailing_stop_pct": body.trailing_stop_pct,
        "max_open_positions": body.max_open_positions,
        "break_even_trigger_pct": body.break_even_trigger_pct,
        "break_even_plus_pct": body.break_even_plus_pct,
        "cooldown_minutes": body.cooldown_minutes,
        "require_btc_trend_up": body.require_btc_trend_up,
        "min_entry_score": body.min_entry_score,
    }
    try:
        return start_paper_bot_scheduler(
            exits_interval_seconds=exits_s,
            strategy_interval_seconds=strategy_s,
            strategy_params=strategy_params,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Auto-run paper: {e}") from e


@app.post("/crypto/bot/auto-stop")
def crypto_bot_auto_stop():
    """Detiene el auto-run paper."""
    from services.crypto.paper_bot_scheduler import stop_paper_bot_scheduler

    return stop_paper_bot_scheduler()


@app.post("/crypto/paper/close")
def crypto_paper_close(body: CryptoPaperCloseBody):
    from services.crypto.paper_portfolio import close_paper_position, get_paper_portfolio

    try:
        close_paper_position(
            position_id=body.position_id,
            price=body.price,
            reason=body.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return get_paper_portfolio()


@app.get("/iol/status")
def iol_status():
    """Estado de credenciales y token IOL en memoria (sin secretos)."""
    from services.market_data.providers.iol import get_iol_status_payload

    return get_iol_status_payload()


@app.post("/iol/reconnect")
def iol_reconnect():
    """
    Limpia token y último error de auth IOL en RAM; no vacía cachés de cadena de opciones.
    El próximo uso de IOL obtendrá token de nuevo.
    """
    from services.market_data.providers.iol import clear_iol_auth_session, ensure_iol_credentials_from_env

    clear_iol_auth_session()
    ensure_iol_credentials_from_env()
    return {"ok": True, "message": "IOL reconnect requested"}


@app.get("/options/iv-smile")
def options_iv_smile(
    underlying: str = Query(..., min_length=1, description="Subyacente ByMA (ej. GGAL)"),
):
    """
    Curva de IV por strike (misma lógica de mark/BS que el panel; bid/ask/último de la cadena mergeada).
    """
    from services.options.iv_history import (
        enrich_iv_smile_items_with_temporal,
        load_previous_snapshots_by_underlying,
        schedule_iv_history_snapshots,
    )
    from services.options.options_service import get_options_chain_with_spot
    from services.options.volatility import build_iv_smile, iv_smile_input_rows_from_chain

    u = (underlying or "").strip().upper()
    chain, spot_info = get_options_chain_with_spot(u, enrich_sources=False)
    spot = spot_info.get("spot")
    try:
        s_num = float(spot) if spot is not None else None
    except (TypeError, ValueError):
        s_num = None
    if s_num is None or not (s_num > 0) or s_num != s_num:
        s_num = None
    rows = iv_smile_input_rows_from_chain(chain, s_num)
    items = build_iv_smile(rows)
    prev_by = load_previous_snapshots_by_underlying(u)
    items = enrich_iv_smile_items_with_temporal(items, prev_by)
    schedule_iv_history_snapshots(u, items)
    return {"items": items}


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


@app.get("/options/chain")
def options_chain(
    underlying: str = Query(default="GGAL", description="Subyacente (ej. GGAL, YPFD, ALUA)"),
    enrich_sources: bool = Query(
        False,
        description="Si true, enriquece IOL con Allaria/Rava por contrato. Default false (más rápido).",
    ),
):
    """
    Cadena de opciones (IOL primario si hay contratos IOL; si no, merge Allaria + Rava).
    No incluye raw completo; sí field_sources / iol_universe / bidask_source_mode cuando aplica.
    """
    from services.options.normalizer import normalize_option_type
    from services.options.options_service import get_options_chain_with_spot

    t0 = time.perf_counter()
    chain, spot_info = get_options_chain_with_spot(underlying, enrich_sources=enrich_sources)
    spot = spot_info.get("spot")
    spot_source = spot_info.get("spot_source")
    spot_symbol = spot_info.get("spot_symbol")
    print(
        "[OPTIONS_SPOT]"
        f" underlying={underlying!r}"
        f" spot={spot!r}"
        f" source={spot_source!r}"
        f" cache_hit={spot_info.get('spot_cache_hit')!r}"
        f" fetch_ms={spot_info.get('spot_fetch_ms')!r}"
        f" symbol_used={spot_info.get('spot_symbol_used')!r}"
        f" updated_at={spot_info.get('spot_updated_at')!r}"
        f" detail={spot_info.get('spot_source_detail')!r}",
        flush=True,
    )
    contracts_sorted = sorted(
        chain.contracts,
        key=lambda c: (
            c.expiry or "",
            normalize_option_type(c.option_type) or (c.option_type or ""),
            c.strike if c.strike is not None else -1.0,
            c.symbol or "",
        ),
    )
    items: list[dict[str, Any]] = []
    for c in contracts_sorted:
        fs: dict[str, Any] | None = None
        iol_u = False
        ba_mode: str | None = None
        if isinstance(c.raw, dict):
            v = c.raw.get("field_sources")
            if isinstance(v, dict):
                fs = dict(v)
            iol_u = bool(c.raw.get("iol_universe"))
            bm = c.raw.get("bidask_source_mode")
            if isinstance(bm, str) and bm.strip():
                ba_mode = bm.strip()
        items.append(
            {
                "underlying": c.underlying,
                "symbol": c.symbol,
                "expiry": c.expiry,
                "option_type": normalize_option_type(c.option_type) or c.option_type,
                "strike": c.strike,
                "bid": c.bid,
                "ask": c.ask,
                "last": c.last,
                "volume": c.volume,
                "open_interest": c.open_interest,
                "source": c.source,
                "field_sources": fs if fs is not None else {},
                "iol_universe": iol_u,
                "bidask_source_mode": ba_mode,
            }
        )

    chain_total_ms = (time.perf_counter() - t0) * 1000.0
    print(
        f"[OPTIONS_API_TIMING] chain_total_ms={chain_total_ms:.1f} underlying={underlying!r} "
        f"total={len(items)} enrich_sources={enrich_sources}",
        flush=True,
    )
    print(
        f"[OPTIONS_API] chain underlying={underlying!r} normalized={chain.underlying!r} "
        f"spot={spot!r} spot_symbol={spot_symbol!r} total={len(items)} enrich_sources={enrich_sources}",
        flush=True,
    )
    out: dict[str, Any] = {
        "underlying": chain.underlying,
        "spot": spot,
        "spot_source": spot_source,
        "spot_symbol": spot_symbol,
        "total": len(items),
        "enrich_sources": enrich_sources,
        "contracts": items,
    }
    for k in (
        "spot_source_detail",
        "spot_cache_hit",
        "spot_fetch_ms",
        "spot_symbol_used",
        "spot_updated_at",
    ):
        if k not in spot_info:
            continue
        v = spot_info[k]
        if v is None:
            continue
        out[k] = v
    return out


@app.get("/options/quotes")
def options_quotes_batch(
    symbols: str = Query(..., description="Especies coma-separadas (máx. 35). Ej: GFGC66553J,GFGC66554J"),
):
    """
    Cotización individual IOL por especie (batch, pool 5 workers, caché RAM TTL corto en backend).
    """
    from services.market_data.providers.iol import ensure_iol_credentials_from_env, is_iol_enabled
    from services.options.iol_quote_enrichment import fetch_iol_option_quotes_batch

    ensure_iol_credentials_from_env()
    if not is_iol_enabled():
        raise HTTPException(status_code=503, detail="IOL no configurado (credenciales)")

    parts = [p.strip().upper().replace(" ", "") for p in (symbols or "").split(",") if p.strip()]
    if not parts:
        raise HTTPException(status_code=400, detail="Query 'symbols' requerido (coma-separado)")
    if len(parts) > 35:
        raise HTTPException(status_code=400, detail="Máximo 35 símbolos por request")

    t0 = time.perf_counter()
    batch = fetch_iol_option_quotes_batch(parts, max_workers=5)
    quotes_payload: dict[str, Any] = {k: v.to_api_dict() for k, v in batch.items()}
    ms = (time.perf_counter() - t0) * 1000.0
    print(
        f"[OPTIONS_API_TIMING] quotes_batch_ms={ms:.1f} requested={len(parts)} returned={len(quotes_payload)}",
        flush=True,
    )
    return {"quotes": quotes_payload}


@app.get("/options/scrape/raw")
def options_scrape_raw(url: str = Query(..., description="URL pública a inspeccionar (RAW)")):
    """
    Descarga RAW de una URL pública (sin parsear/estructurar) para inspección manual.
    """
    import requests

    u = (url or "").strip()
    if not u:
        raise HTTPException(status_code=400, detail="Query param 'url' es requerido")
    if not (u.startswith("http://") or u.startswith("https://")):
        raise HTTPException(status_code=400, detail="La URL debe empezar con http:// o https://")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        )
    }

    try:
        r = requests.get(u, headers=headers, timeout=20)
    except requests.RequestException as e:
        print(f"[OPTIONS_SCRAPE_RAW] url={u!r} status=error error={type(e).__name__}: {e}", flush=True)
        raise HTTPException(status_code=502, detail=f"Error de red: {type(e).__name__}: {e}") from e

    content_type = str(r.headers.get("content-type") or "")
    length = len(r.content or b"")
    print(
        f"[OPTIONS_SCRAPE_RAW] url={u!r} status_code={r.status_code} content_type={content_type!r} length={length}",
        flush=True,
    )

    try:
        body_text = r.text or ""
    except Exception:
        body_text = ""

    return {
        "status_code": int(r.status_code),
        "content_type": content_type,
        "length": int(length),
        "body_prefix": body_text[:5000],
    }


def _fetch_rava_prices_datos() -> list[Any]:
    """
    GET https://mercado.rava.com/api/prices/arg → lista raíz "datos".
    Misma fuente que /options/rava/raw.
    """
    import requests

    src_url = "https://mercado.rava.com/api/prices/arg"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        )
    }

    try:
        r = requests.get(src_url, headers=headers, timeout=30)
    except requests.RequestException as e:
        print(f"[RAVA_OPTIONS_RAW] status=error error={type(e).__name__}: {e}", flush=True)
        raise HTTPException(status_code=502, detail=f"Error de red: {type(e).__name__}: {e}") from e

    if not r.ok:
        body_prefix = (r.text or "")[:500]
        print(f"[RAVA_OPTIONS_RAW] status=http_error http_status={r.status_code} body_prefix={body_prefix!r}", flush=True)
        raise HTTPException(status_code=int(r.status_code), detail=f"Rava respondió {r.status_code}: {body_prefix}")

    try:
        obj: Any = r.json()
    except ValueError as e:
        body_prefix = (r.text or "")[:2000]
        print(f"[RAVA_OPTIONS_RAW] status=invalid_json body_prefix={body_prefix!r}", flush=True)
        raise HTTPException(status_code=502, detail=f"Respuesta Rava no es JSON válido: {e}") from e

    datos = obj.get("datos") if isinstance(obj, dict) else None
    if not isinstance(datos, list):
        root_keys = list(obj.keys()) if isinstance(obj, dict) else None
        print(
            f"[RAVA_OPTIONS_RAW] status=missing_datos root_type={type(obj).__name__} root_keys={root_keys}",
            flush=True,
        )
        raise HTTPException(status_code=502, detail="Respuesta Rava no contiene lista 'datos'")

    return datos


@app.get("/options/rava/raw")
def options_rava_raw():
    """
    Opciones RAW desde Rava (mercado.rava.com) para inspección (sin parsear/estructurar).
    Fuente: https://mercado.rava.com/api/prices/arg  (raíz JSON: datos)
    """
    datos = _fetch_rava_prices_datos()

    opt_items: list[Any] = []
    updated_max: str | None = None
    first_keys: list[str] | None = None

    for it in datos:
        if not isinstance(it, dict):
            continue
        st = str(it.get("securitytype") or "").strip().upper()
        if st != "OPT":
            continue
        opt_items.append(it)
        if first_keys is None:
            first_keys = list(it.keys())
        # datetime suele venir ISO; max lexicográfico funciona si es ISO comparable.
        dt = it.get("datetime")
        if isinstance(dt, str) and dt.strip():
            s = dt.strip()
            if updated_max is None or s > updated_max:
                updated_max = s

    print(
        f"[RAVA_OPTIONS_RAW] total_items={len(datos)} opt_items={len(opt_items)} "
        f"first_keys={first_keys or []} updated_max={updated_max!r}",
        flush=True,
    )

    return opt_items


@app.get("/options/rava/chain")
def options_rava_chain(underlying: str | None = Query(default=None, description="Filtrar por subyacente parseado")):
    """
    Cadena de opciones Rava (misma fuente que /options/rava/raw), agrupada por subyacente / vencimiento / strike.
    """
    from services.options.rava_chain_builder import build_rava_option_chain

    datos = _fetch_rava_prices_datos()

    def _rava_ultimo_float(v: Any) -> float | None:
        if v is None:
            return None
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        if x != x or x <= 0:
            return None
        return x

    # Solo acciones CS en ARS; preferir plazo 2, si no hay usar plazo 1.
    prices_by_symbol: dict[str, tuple[float, int]] = {}
    for it in datos:
        if not isinstance(it, dict):
            continue
        if str(it.get("securitytype") or "").strip().upper() != "CS":
            continue
        if str(it.get("moneda") or "").strip().upper() != "ARS":
            continue
        symbol = str(it.get("simbolo") or "").strip().upper()
        if not symbol:
            continue
        try:
            plazo = int(it.get("plazo"))
        except (TypeError, ValueError):
            continue
        if plazo not in (1, 2):
            continue
        uf = _rava_ultimo_float(it.get("ultimo"))
        if uf is None:
            continue

        cur = prices_by_symbol.get(symbol)
        if cur is None:
            prices_by_symbol[symbol] = (uf, plazo)
        elif plazo == 2:
            prices_by_symbol[symbol] = (uf, plazo)
        elif cur[1] != 2 and plazo == 1:
            prices_by_symbol[symbol] = (uf, plazo)

    underlying_prices: dict[str, float] = {s: t[0] for s, t in prices_by_symbol.items()}

    # Alias de símbolo "acción" → símbolo "opciones" o viceversa (para spot / moneyness y filtros).
    # Nota: en algunas series, el prefijo de opciones puede no coincidir 1:1 con el ticker del subyacente.
    OPTION_UNDERLYING_PREFIX_ALIASES: dict[str, list[str]] = {
        # Transener: opciones suelen venir como TRA{C|V}..., pero el subyacente es TRAN.
        "TRAN": ["TRA"],
    }

    for src, dst in (("GGAL", "GFG"), ("ALUA", "ALU"), ("COME", "COM"), ("BYMA", "BYM")):
        if src in underlying_prices:
            underlying_prices[dst] = underlying_prices[src]

    # Replicar spot del subyacente hacia aliases de prefijo de opciones.
    for main, aliases in OPTION_UNDERLYING_PREFIX_ALIASES.items():
        if main in underlying_prices:
            for a in aliases:
                underlying_prices.setdefault(a, underlying_prices[main])

    opt_items = [
        it
        for it in datos
        if isinstance(it, dict) and str(it.get("securitytype") or "").strip().upper() == "OPT"
    ]

    chain = build_rava_option_chain(opt_items, underlying_prices)
    underlyings_count = len(chain)
    u_filter = (underlying or "").strip().upper() or None
    prices_sample = sorted(underlying_prices.keys())[:30]
    print(
        f"[RAVA_CHAIN_API] opt_items={len(opt_items)} underlyings_count={underlyings_count} "
        f"underlying_prices_count={len(underlying_prices)} underlying_filter={u_filter!r}",
        flush=True,
    )
    print(f"[RAVA_CHAIN_API] has_GGAL={'GGAL' in underlying_prices}", flush=True)
    print(f"[RAVA_CHAIN_API] GGAL_price={underlying_prices.get('GGAL')!r}", flush=True)
    print(f"[RAVA_CHAIN_API] has_GFG={'GFG' in underlying_prices}", flush=True)
    print(f"[RAVA_CHAIN_API] GFG_price={underlying_prices.get('GFG')!r}", flush=True)
    print(f"[RAVA_CHAIN_API] underlying_prices_sample={prices_sample!r}", flush=True)

    if u_filter:
        # Si el subyacente filtrado no coincide con el prefijo de opciones, intentar aliases.
        if u_filter in chain:
            return chain.get(u_filter, {})
        aliases = OPTION_UNDERLYING_PREFIX_ALIASES.get(u_filter) or []
        merged: dict[str, Any] = {}
        for a in aliases:
            part = chain.get(a)
            if not isinstance(part, dict):
                continue
            for exp, bucket in part.items():
                if not isinstance(bucket, dict):
                    continue
                cur = merged.get(exp)
                if not isinstance(cur, dict):
                    cur = {"calls": {}, "puts": {}}
                    merged[exp] = cur
                for side in ("calls", "puts"):
                    m = bucket.get(side)
                    if isinstance(m, dict):
                        cur.setdefault(side, {})
                        cur[side].update(m)
        return merged
    return chain


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
