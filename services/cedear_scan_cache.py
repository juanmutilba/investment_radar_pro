from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from services import latest_export
from services.cedear_service import CedearRow, build_cedear_rows_from_latest_radar


def _snapshot_path() -> Path:
    base = Path(__file__).resolve().parent.parent
    d = base / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "last_cedears_build.json"


def read_cedears_build_meta() -> dict[str, Any] | None:
    path = _snapshot_path()
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return None
        return obj
    except Exception:
        return None


def _count_cedear_signal_rows(rows: list[dict[str, Any]]) -> int:
    n = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        sig = r.get("SignalState")
        if sig is None:
            continue
        if isinstance(sig, str) and sig.strip():
            n += 1
    return n


def _export_path_key() -> str | None:
    p = latest_export.resolve_latest_export_path()
    if p is None:
        return None
    try:
        return str(p.resolve())
    except OSError:
        return str(p)


def persist_cedear_snapshot_from_models(
    *,
    scan_finished_at: str,
    built: list[CedearRow] | None,
    source_export_file: str | None,
) -> tuple[int, int]:
    """
    Serializa y guarda el snapshot usado por GET /cedears (sin Yahoo en lecturas posteriores).
    """
    rows_json: list[dict[str, Any]] = []
    if built:
        for row in built:
            rows_json.append(row.model_dump(mode="json", by_alias=True))

    cedear_alertas = _count_cedear_signal_rows(rows_json)
    snapshot: dict[str, Any] = {
        "scan_finished_at": scan_finished_at,
        "source_export_file": source_export_file or "",
        "row_count": len(rows_json),
        "rows": rows_json,
        "cedear_alertas": cedear_alertas,
    }
    try:
        path = _snapshot_path()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass

    return len(rows_json), cedear_alertas


def try_load_cedear_snapshot_rows() -> list[CedearRow] | None:
    """
    Si existe snapshot y apunta al mismo radar_*.xlsx que el último export, devuelve filas
    ya materializadas (sin Yahoo). Si no aplica, devuelve None.
    """
    meta = read_cedears_build_meta()
    if meta is None:
        return None

    cur = latest_export.resolve_latest_export_path()
    if cur is None:
        return None

    snap_file = meta.get("source_export_file")
    if not snap_file or not isinstance(snap_file, str) or not snap_file.strip():
        return None

    try:
        if Path(snap_file).resolve() != cur.resolve():
            return None
    except OSError:
        return None

    rows_raw = meta.get("rows")
    if not isinstance(rows_raw, list):
        return None

    rc = meta.get("row_count")
    if isinstance(rc, int) and rc != len(rows_raw):
        return None

    out: list[CedearRow] = []
    for item in rows_raw:
        if not isinstance(item, dict):
            return None
        try:
            out.append(CedearRow.model_validate(item))
        except Exception:
            return None
    return out


def run_cedear_build_for_scan(*, scan_finished_at: str) -> tuple[float, dict[str, Any]]:
    """
    Ejecuta el mismo armado que GET /cedears (build_cedear_rows_from_latest_radar),
    persiste snapshot en disco y devuelve (seconds, metrics_patch).
    """
    t0 = time.perf_counter()
    export_key = _export_path_key()
    built = build_cedear_rows_from_latest_radar()
    elapsed = time.perf_counter() - t0

    if built is None:
        n_act, n_alert = persist_cedear_snapshot_from_models(
            scan_finished_at=scan_finished_at,
            built=None,
            source_export_file=export_key,
        )
        return elapsed, {
            "cedear_scan_seconds": round(elapsed, 3),
            "cedear_total_activos": n_act,
            "cedear_alertas": n_alert,
        }

    n_act, n_alert = persist_cedear_snapshot_from_models(
        scan_finished_at=scan_finished_at,
        built=built,
        source_export_file=export_key,
    )

    return elapsed, {
        "cedear_scan_seconds": round(elapsed, 3),
        "cedear_total_activos": n_act,
        "cedear_alertas": n_alert,
    }
