#!/usr/bin/env python3
"""
Distribución de volume_ratio + simulación de nueva escala volume_score (intradía).

Uso:
  python scripts/simulate_intraday_volume_score.py
  python scripts/simulate_intraday_volume_score.py --timeframe 30m --limit 200

Salida: data/crypto_volume_score_simulation_<ts>.md
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def volume_score_current(vr: float | None) -> float:
    if vr is None or not math.isfinite(float(vr)):
        return 0.0
    r = float(vr)
    if r >= 1.2:
        return 8.0
    if r >= 1.1:
        return 4.0
    if r < 0.9:
        return -10.0
    return 0.0


def volume_score_proposed(vr: float | None) -> float:
    if vr is None or not math.isfinite(float(vr)):
        return 0.0
    r = float(vr)
    if r >= 1.2:
        return 8.0
    if r >= 1.1:
        return 4.0
    if r >= 0.9:
        return 0.0
    if r >= 0.7:
        return -5.0
    return -10.0


def vr_bucket(vr: float | None) -> str:
    if vr is None or not math.isfinite(float(vr)):
        return "missing/non-finite"
    r = float(vr)
    if r >= 1.2:
        return ">=1.2"
    if r >= 1.1:
        return "1.1-1.2"
    if r >= 0.9:
        return "0.9-1.1"
    if r >= 0.7:
        return "0.7-0.9"
    return "<0.7"


def recompute_score(row: dict, replacement_volume_score: float) -> int:
    bd = row.get("score_breakdown")
    if not isinstance(bd, dict):
        return int(row.get("score") or 0)
    try:
        total = float(bd.get("total_before_clamp") or 0.0)
        vs_bd = float(bd.get("volume_score") or 0.0)
    except (TypeError, ValueError):
        return int(row.get("score") or 0)
    adj = total - vs_bd + replacement_volume_score
    return int(max(0, min(100, round(adj))))


def count_above(scores: list[int], thresholds: list[int]) -> dict[int, int]:
    return {t: sum(1 for s in scores if s >= t) for t in thresholds}


def score_histogram(scores: list[int]) -> Counter[str]:
    c: Counter[str] = Counter()
    for s in scores:
        if s >= 85:
            c["85+"] += 1
        elif s >= 75:
            c["75-84"] += 1
        elif s >= 70:
            c["70-74"] += 1
        elif s >= 65:
            c["65-69"] += 1
        elif s >= 60:
            c["60-64"] += 1
        elif s >= 50:
            c["50-59"] += 1
        else:
            c["<50"] += 1
    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="30m")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from services.crypto.watchlist import scan_crypto_watchlist

    rows = scan_crypto_watchlist(
        timeframe=args.timeframe,
        limit=int(args.limit),
        strategy_mode="daily_intraday",
    )
    ok = [r for r in rows if isinstance(r, dict) and not r.get("error")]

    vr_buckets = Counter()
    for r in ok:
        vr = r.get("volume_ratio")
        try:
            vf = float(vr) if vr is not None and vr == vr else None
        except (TypeError, ValueError):
            vf = None
        vr_buckets[vr_bucket(vf)] += 1

    thresholds = [60, 65, 70, 75, 85]
    old_scores: list[int] = []
    new_scores: list[int] = []
    table_rows: list[tuple[str, float | None, float, float, int, int, int, int]] = []

    for r in ok:
        sym = str(r.get("symbol") or "?")
        vr = r.get("volume_ratio")
        try:
            vf = float(vr) if vr is not None and vr == vr else None
        except (TypeError, ValueError):
            vf = None
        vcur = volume_score_current(vf)
        vnew = volume_score_proposed(vf)
        old_s = recompute_score(r, vcur)
        new_s = recompute_score(r, vnew)
        raw = int(r.get("score") or 0)
        old_scores.append(old_s)
        new_scores.append(new_s)
        table_rows.append((sym, vf, vcur, vnew, old_s, new_s, new_s - old_s, raw))

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    out = DATA / f"crypto_volume_score_simulation_{ts}.md"
    DATA.mkdir(parents=True, exist_ok=True)

    old_above = count_above(old_scores, thresholds)
    new_above = count_above(new_scores, thresholds)
    hist_old = score_histogram(old_scores)
    hist_new = score_histogram(new_scores)

    lines: list[str] = []
    W = lines.append
    W("# Simulación volume_score (intradía)\n")
    W(f"- UTC: `{ts}` | tf `{args.timeframe}` limit `{args.limit}` | filas OK: **{len(ok)}**\n")
    W("\n## 1. Escalas de `volume_score` (referencia)\n")
    W("### A) Legacy / `trend_swing` (sin cambios en código)\n")
    W("```python\n")
    W("if r >= 1.2: volume_score = 8\n")
    W("elif r >= 1.1: volume_score = 4\n")
    W("elif r < 0.9: volume_score = -10\n")
    W("# else: 0\n")
    W("```\n")
    W("\n### B) Intradía suavizada (`daily_intraday`, implementado en `signals.py`)\n")
    W("```python\n")
    W("if r >= 1.2: volume_score = 8\n")
    W("elif r >= 1.1: volume_score = 4\n")
    W("elif r >= 0.9: volume_score = 0\n")
    W("elif r >= 0.7: volume_score = -5\n")
    W("else: volume_score = -10\n")
    W("```\n")
    W("\n## 2. Distribución observada de `volume_ratio` (último scan)\n")
    order = [">=1.2", "1.1-1.2", "0.9-1.1", "0.7-0.9", "<0.7", "missing/non-finite"]
    W("| Rango | Activos |\n|---|---:|\n")
    for k in order:
        W(f"| {k} | {vr_buckets.get(k, 0)} |\n")

    W("\n## 3. Comparativa por símbolo (score total)\n")
    W("| symbol | volume_ratio | vol_score_old | vol_score_new | score_legacy | score_soft | delta | score_scan |\n")
    W("|---|---:|---:|---:|---:|---:|---:|---:|\n")
    for sym, vf, vcur, vnew, os_, ns, d, raw in sorted(table_rows, key=lambda x: x[0]):
        vr_s = f"{vf:.4f}" if vf is not None and vf == vf else "—"
        W(f"| {sym} | {vr_s} | {vcur:g} | {vnew:g} | {os_} | {ns} | {d:+d} | {raw} |\n")

    W("\n_Notas: `score_legacy` recalcula sustituyendo solo `volume_score` por la escala **dura** (trend_swing); ")
    W("`score_soft` usa la escala **suavizada**; `score_scan` es el `score` devuelto por el último scan (tras desplegar código, intradía ya usa escala suave en `volume_score`)._\n")

    W("\n## 4. Activos que superan umbrales (legacy vs escala suavizada)\n")
    W("| Umbral | Penalización dura (r<0.9 -> -10) | Suavizada (0.7–0.9 -> -5) |\n")
    W("|---:|---:|---:|\n")
    for t in thresholds:
        W(f"| >= {t} | {old_above[t]} | {new_above[t]} |\n")

    W("\n## 5. Histograma de scores (legacy / suavizada)\n")
    W("| Bucket | Legacy | Suavizada |\n")
    W("|---|---:|---:|\n")
    for b in ["85+", "75-84", "70-74", "65-69", "60-64", "50-59", "<50"]:
        W(f"| {b} | {hist_old.get(b, 0)} | {hist_new.get(b, 0)} |\n")

    body = "\n".join(lines)
    out.write_text(body, encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
