from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from persistence.sqlite.connection import connection_scope


def _real(d: dict[str, Any], key: str) -> float | None:
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(d: dict[str, Any], key: str) -> int | None:
    v = d.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def insert_running_scan_run(
    conn: sqlite3.Connection,
    started_at: str,
    *,
    source: str = "api",
) -> int:
    cur = conn.execute(
        "INSERT INTO scan_runs (started_at, status, source) VALUES (?, 'running', ?)",
        (started_at, source),
    )
    return int(cur.lastrowid)


def finalize_scan_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    finished_at: str,
    status: str,
    export_file: str | None = None,
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE scan_runs
        SET finished_at = ?, status = ?, export_file = ?, error_message = ?
        WHERE id = ?
        """,
        (finished_at, status, export_file, error_message, run_id),
    )


def insert_scan_metrics_row(
    conn: sqlite3.Connection,
    run_id: int,
    metrics: dict[str, Any],
) -> None:
    payload = json.dumps(metrics, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO scan_metrics (
          scan_run_id,
          total_scan_seconds,
          usa_scan_seconds,
          arg_scan_seconds,
          cedear_scan_seconds,
          alerts_seconds,
          usa_total_activos,
          arg_total_activos,
          cedear_total_activos,
          usa_alertas,
          arg_alertas,
          cedear_alertas,
          metrics_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            _real(metrics, "total_scan_seconds"),
            _real(metrics, "usa_scan_seconds"),
            _real(metrics, "arg_scan_seconds"),
            _real(metrics, "cedear_scan_seconds"),
            _real(metrics, "alerts_seconds"),
            _int(metrics, "usa_total_activos"),
            _int(metrics, "arg_total_activos"),
            _int(metrics, "cedear_total_activos"),
            _int(metrics, "usa_alertas"),
            _int(metrics, "arg_alertas"),
            _int(metrics, "cedear_alertas"),
            payload,
        ),
    )


def persist_failed_scan_run(
    run_id: int,
    error_message: str,
    metrics: dict[str, Any] | None = None,
    *,
    export_file: str | None = None,
) -> None:
    """Best-effort: marca failed y guarda métricas parciales si hay dict no vacío."""
    finished_at = datetime.now(timezone.utc).isoformat()
    m = metrics if metrics else {}
    try:
        with connection_scope() as conn:
            finalize_scan_run(
                conn,
                run_id,
                finished_at=finished_at,
                status="failed",
                export_file=export_file,
                error_message=error_message,
            )
            if m:
                insert_scan_metrics_row(conn, run_id, m)
    except Exception:
        pass
