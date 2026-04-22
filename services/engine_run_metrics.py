from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _metrics_path() -> Path:
    base = Path(__file__).resolve().parent.parent
    d = base / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "scan_engine_metrics.json"


def load_previous_engine(engine_key: str) -> dict[str, Any] | None:
    path = _metrics_path()
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        obj = json.loads(raw)
        prev = obj.get(engine_key)
        return prev if isinstance(prev, dict) else None
    except Exception:
        return None


def save_engine_metrics(engine_key: str, metrics: dict[str, Any]) -> None:
    path = _metrics_path()
    try:
        existing: dict[str, Any] = {}
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
            if raw:
                o = json.loads(raw)
                if isinstance(o, dict):
                    existing = o
        existing[engine_key] = {
            **metrics,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _last_scan_metrics_path() -> Path:
    base = Path(__file__).resolve().parent.parent
    d = base / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "last_scan_metrics.json"


def load_last_scan_metrics() -> dict[str, Any] | None:
    path = _last_scan_metrics_path()
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def save_last_scan_metrics(metrics: dict[str, Any]) -> None:
    """
    Persiste métricas agregadas del último scan (para mostrar en Dashboard).
    Best-effort: no debe romper el pipeline si falla I/O.
    """
    path = _last_scan_metrics_path()
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def format_delta_line(label: str, prev: dict[str, Any] | None, cur_t: float) -> str | None:
    if not prev:
        return None
    try:
        pt = float(prev.get("elapsed_s", 0))
    except (TypeError, ValueError):
        return None
    if pt <= 0:
        return None
    delta = cur_t - pt
    pct = (delta / pt) * 100.0
    sign = "+" if delta >= 0 else ""
    return f"{label} corrida anterior: t={pt:.1f}s → ahora {cur_t:.1f}s ({sign}{delta:.1f}s, {sign}{pct:.0f}%)"
