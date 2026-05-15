"""
Historial liviano de snapshots IV (JSONL por subyacente).

Append-only, rate-limit por subyacente, truncado a ~3000 líneas.
Escritura en background; fallos silenciosos.
"""

from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
IV_HISTORY_DIR = _REPO_ROOT / "data" / "options_iv_history"

MAX_LINES = 3000
MIN_APPEND_INTERVAL_SEC = 300
TAIL_READ_BYTES = 512 * 1024

IV_EXPAND_THRESHOLD = 8.0
IV_CRUSH_THRESHOLD = -8.0

_locks_guard = threading.Lock()
_file_locks: dict[str, threading.Lock] = {}


def _underlying_lock(u: str) -> threading.Lock:
    with _locks_guard:
        return _file_locks.setdefault(u, threading.Lock())


def _jsonl_path(underlying: str) -> Path:
    return IV_HISTORY_DIR / f"{(underlying or '').strip().upper()}.jsonl"


def _iso_utc_z(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts_iso(s: object) -> datetime | None:
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def _ensure_dir() -> None:
    try:
        IV_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _read_file_tail_text(path: Path, max_bytes: int = TAIL_READ_BYTES) -> str:
    try:
        size = path.stat().st_size
    except Exception:
        return ""
    try:
        with open(path, "rb") as f:
            if size <= max_bytes:
                raw = f.read()
            else:
                f.seek(max(0, size - max_bytes))
                raw = f.read()
                nl = raw.find(b"\n")
                if nl != -1:
                    raw = raw[nl + 1 :]
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _last_line_ts_in_file(path: Path) -> datetime | None:
    text = _read_file_tail_text(path, max_bytes=65536)
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        return _parse_ts_iso(obj.get("ts"))
    return None


def load_previous_snapshots_by_underlying(underlying: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    """
    Por cada terna (underlying, expiration, option_type), el snapshot más reciente
    encontrado en la cola del JSONL (orden cronológico por línea).
    """
    u = (underlying or "").strip().upper()
    if not u:
        return {}
    path = _jsonl_path(u)
    if not path.is_file():
        return {}
    text = _read_file_tail_text(path)
    lines = text.splitlines()
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        und = str(obj.get("underlying") or "").strip().upper()
        exp = str(obj.get("expiration") or "").strip()[:10]
        ot = str(obj.get("option_type") or "").strip().upper()
        if not und or not exp or ot not in ("CALL", "PUT"):
            continue
        key = (und, exp, ot)
        if key not in out:
            out[key] = obj
    return out


def load_recent_iv_snapshot(
    underlying: str,
    expiration: str,
    option_type: str,
) -> dict[str, Any] | None:
    """Último snapshot guardado para la terna (misma lógica que ``load_previous_snapshots_by_underlying``)."""
    u = (underlying or "").strip().upper()
    exp = (expiration or "").strip()[:10]
    ot = (option_type or "").strip().upper()
    if not u or not exp or ot not in ("CALL", "PUT"):
        return None
    return load_previous_snapshots_by_underlying(u).get((u, exp, ot))


def _prev_iv_maps(snapshot: dict[str, Any]) -> tuple[dict[str, float], dict[float, float]]:
    by_sym: dict[str, float] = {}
    by_k: dict[float, float] = {}
    pts = snapshot.get("points")
    if not isinstance(pts, list):
        return by_sym, by_k
    for raw in pts:
        if not isinstance(raw, dict):
            continue
        try:
            iv = float(raw.get("iv_pct"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(iv) or iv <= 0:
            continue
        sym = str(raw.get("symbol") or "").strip().upper()
        if sym:
            by_sym[sym] = iv
        try:
            k = float(raw.get("strike"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(k) and k > 0:
            by_k[k] = iv
    return by_sym, by_k


def enrich_iv_smile_items_with_temporal(
    items: list[dict[str, Any]],
    prev_by_key: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Añade ``iv_change_pct``, ``iv_expanding``, ``iv_crushing`` por punto si hay snapshot previo comparable."""
    out_groups: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        und = str(item.get("underlying") or "").strip().upper()
        exp = str(item.get("expiration") or "").strip()[:10]
        ot = str(item.get("option_type") or "").strip().upper()
        prev = prev_by_key.get((und, exp, ot)) if und and exp and ot in ("CALL", "PUT") else None
        by_sym, by_k = _prev_iv_maps(prev) if isinstance(prev, dict) else ({}, {})
        pts_in = item.get("points")
        pts_out: list[dict[str, Any]] = []
        if isinstance(pts_in, list):
            for p in pts_in:
                if not isinstance(p, dict):
                    continue
                try:
                    iv = float(p.get("iv_pct"))
                except (TypeError, ValueError):
                    pts_out.append(dict(p))
                    continue
                if not math.isfinite(iv):
                    pts_out.append(dict(p))
                    continue
                sym = str(p.get("symbol") or "").strip().upper()
                prev_iv: float | None = None
                try:
                    k = float(p.get("strike"))
                except (TypeError, ValueError):
                    k = float("nan")
                if sym and sym in by_sym:
                    prev_iv = by_sym[sym]
                elif math.isfinite(k) and k in by_k:
                    prev_iv = by_k[k]
                ch: float | None = None
                expanding = False
                crushing = False
                if prev_iv is not None and prev_iv > 0 and math.isfinite(prev_iv):
                    ch = (iv / prev_iv - 1.0) * 100.0
                    if math.isfinite(ch):
                        expanding = ch >= IV_EXPAND_THRESHOLD
                        crushing = ch <= IV_CRUSH_THRESHOLD
                    else:
                        ch = None
                np = dict(p)
                np["iv_change_pct"] = round(ch, 4) if ch is not None else None
                np["iv_expanding"] = expanding
                np["iv_crushing"] = crushing
                pts_out.append(np)
        ng = dict(item)
        ng["points"] = pts_out
        out_groups.append(ng)
    return out_groups


def _group_to_snapshot_record(item: dict[str, Any], ts: str) -> dict[str, Any]:
    pts_raw = item.get("points") or []
    points: list[dict[str, Any]] = []
    if isinstance(pts_raw, list):
        for p in pts_raw:
            if not isinstance(p, dict):
                continue
            try:
                strike = float(p.get("strike"))
                ivp = float(p.get("iv_pct"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(strike) or not math.isfinite(ivp):
                continue
            points.append(
                {
                    "symbol": str(p.get("symbol") or ""),
                    "strike": strike,
                    "iv_pct": round(ivp, 6),
                }
            )
    avg = item.get("avg_iv_pct")
    avg_f: float | None
    try:
        avg_f = float(avg) if avg is not None else None
    except (TypeError, ValueError):
        avg_f = None
    if avg_f is not None and not math.isfinite(avg_f):
        avg_f = None
    return {
        "ts": ts,
        "underlying": str(item.get("underlying") or "").strip().upper(),
        "expiration": str(item.get("expiration") or "").strip()[:10],
        "option_type": str(item.get("option_type") or "").strip().upper(),
        "avg_iv_pct": round(avg_f, 4) if avg_f is not None else None,
        "points": points,
    }


def _maybe_truncate_jsonl(path: Path) -> None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return
    if len(lines) <= MAX_LINES:
        return
    keep = lines[-MAX_LINES:]
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(keep)
    except Exception:
        return


def _append_snapshots_locked(underlying: str, items: list[dict[str, Any]]) -> None:
    _ensure_dir()
    path = _jsonl_path(underlying)
    last_ts = _last_line_ts_in_file(path)
    if last_ts is not None:
        delta = (datetime.now(timezone.utc) - last_ts).total_seconds()
        if delta < MIN_APPEND_INTERVAL_SEC:
            return
    ts = _iso_utc_z()
    try:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            for it in items:
                if not isinstance(it, dict):
                    continue
                rec = _group_to_snapshot_record(it, ts)
                if not rec["underlying"] or not rec["expiration"] or rec["option_type"] not in ("CALL", "PUT"):
                    continue
                if not rec["points"]:
                    continue
                f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        return
    _maybe_truncate_jsonl(path)


def _write_snapshots_bg(underlying: str, items: list[dict[str, Any]]) -> None:
    try:
        u = (underlying or "").strip().upper()
        if not u or not items:
            return
        with _underlying_lock(u):
            _append_snapshots_locked(u, items)
    except Exception:
        return


def schedule_iv_history_snapshots(underlying: str, items: list[dict[str, Any]]) -> None:
    """Encola escritura JSONL sin bloquear el request."""
    u = (underlying or "").strip().upper()
    if not u or not items:
        return
    try:
        t = threading.Thread(target=_write_snapshots_bg, args=(u, items), daemon=True)
        t.start()
    except Exception:
        return
