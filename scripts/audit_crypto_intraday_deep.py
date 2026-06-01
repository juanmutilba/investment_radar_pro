#!/usr/bin/env python3
"""
Auditoría profunda del pipeline Daily intradía (scanner -> candidatos -> filtros testnet).

Lee data/crypto_testnet_auto_cycles.jsonl (y opcionalmente hace un scan en vivo).

Uso:
  python scripts/audit_crypto_intraday_deep.py --date 2026-06-01
  python scripts/audit_crypto_intraday_deep.py --live-scan

Salida: data/crypto_intraday_deep_audit_<date>.md
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
AUTO_JSONL = DATA / "crypto_testnet_auto_cycles.jsonl"
MONITOR_JSONL = DATA / "crypto_testnet_monitor_cycles.jsonl"


def _day_from_ts(ts: str | None) -> str | None:
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    return s[:10] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else None


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict):
            out.append(o)
    return out


def _score_bucket(x: float) -> str:
    if x >= 85:
        return ">=85"
    if x >= 80:
        return "80-84"
    if x >= 75:
        return "75-79"
    if x >= 70:
        return "70-74"
    if x >= 65:
        return "65-69"
    return "<65"


def _rsi_bucket(x: float | None) -> str | None:
    if x is None:
        return None
    if x < 30:
        return "<30"
    if x < 40:
        return "30-40"
    if x <= 60:
        return "40-60"
    return ">60"


def _histogram(scores: list[float]) -> Counter[str]:
    c: Counter[str] = Counter()
    for s in scores:
        c[_score_bucket(s)] += 1
    return c


def _mean_breakdown(rows: list[dict[str, Any]]) -> dict[str, float]:
    keys = ("adx_score", "volume_score", "trigger_score", "rsi_score", "macd_score", "ema_score", "btc_trend_score", "risk_penalty")
    acc: dict[str, list[float]] = {k: [] for k in keys}
    for r in rows:
        bd = r.get("score_breakdown") if isinstance(r, dict) else None
        if not isinstance(bd, dict):
            continue
        for k in keys:
            v = bd.get(k)
            if isinstance(v, (int, float)) and v == v:
                acc[k].append(float(v))
    return {k: (statistics.mean(acc[k]) if acc[k] else 0.0) for k in keys}


def _live_scan_payload(tf: str, limit: int, mode: str) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from services.crypto.bot_runner import evaluate_entry_candidates
    from services.crypto.strategy_modes import is_entry_candidate_row, normalize_strategy_mode
    from services.crypto.watchlist import get_crypto_watchlist, scan_crypto_watchlist

    wl = get_crypto_watchlist()
    rows = scan_crypto_watchlist(timeframe=tf, limit=limit, strategy_mode=mode)
    mode_n = normalize_strategy_mode(mode)
    ok = [r for r in rows if isinstance(r, dict) and not r.get("error")]
    bad = [r for r in rows if isinstance(r, dict) and r.get("error")]
    sig_c = Counter(str(r.get("signal") or "missing") for r in ok)
    scores: list[float] = []
    rsis: list[float] = []
    for r in ok:
        sc = r.get("score")
        if isinstance(sc, (int, float)) and sc == sc:
            scores.append(float(sc))
        rsi = r.get("rsi_14")
        if isinstance(rsi, (int, float)) and rsi == rsi:
            rsis.append(float(rsi))
    cand = [r for r in rows if isinstance(r, dict) and is_entry_candidate_row(r, mode_n)]
    digest = []
    for r in ok[:64]:
        digest.append(
            {
                "symbol": r.get("symbol"),
                "signal": r.get("signal"),
                "score": r.get("score"),
                "setup_type": r.get("setup_type"),
                "entry_eligible": r.get("entry_eligible"),
                "rsi_14": r.get("rsi_14"),
                "score_breakdown": r.get("score_breakdown"),
            }
        )
    rsi_h = Counter()
    for rv in rsis:
        b = _rsi_bucket(rv)
        if b:
            rsi_h[b] += 1
    top_scores = sorted(scores, reverse=True)[:10]
    return {
        "watchlist_count": len(wl),
        "scanned_total": len(rows),
        "scan_ok": len(ok),
        "scan_errors": len(bad),
        "signal_counts": dict(sig_c),
        "candidates_evaluate_entry": len(cand),
        "scores": scores,
        "score_max": max(scores) if scores else None,
        "score_mean": statistics.mean(scores) if scores else None,
        "top10_scores": top_scores,
        "histogram": dict(_histogram(scores)),
        "rsi_histogram": dict(rsi_h),
        "mean_breakdown_ok_rows": _mean_breakdown(digest),
        "scan_rows_digest": digest,
        "error_samples": [str(r.get("error"))[:120] for r in bad[:5]],
    }


def _pick_latest_audit(cycles: list[dict[str, Any]]) -> dict[str, Any] | None:
    for r in reversed(cycles):
        a = r.get("entry_pipeline_audit")
        if isinstance(a, dict) and (a.get("scan_rows_digest") or a.get("evaluated_summary")):
            return a
    return None


def _aggregate_day(cycles: list[dict[str, Any]]) -> tuple[Counter[str], list[float]]:
    pr: Counter[str] = Counter()
    mins: list[float] = []
    for c in cycles:
        ps = c.get("params_snapshot")
        if isinstance(ps, dict) and ps.get("min_entry_score") is not None:
            try:
                mins.append(float(ps["min_entry_score"]))
            except (TypeError, ValueError):
                pass
        for a in c.get("actions_taken") or []:
            if isinstance(a, dict) and a.get("type") == "no_entry":
                pr[str(a.get("primary_reason") or "unknown")] += 1
    return pr, mins


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="Día UTC YYYY-MM-DD (default hoy UTC)")
    ap.add_argument("--live-scan", action="store_true", help="Ejecutar scan real (requiere red, ccxt)")
    ap.add_argument("--timeframe", default="30m")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--strategy-mode", default="daily_intraday")
    args = ap.parse_args()
    day = (args.date or "").strip() or _utc_today()

    lines_out: list[str] = []
    W = lines_out.append

    W(f"# Auditoría pipeline crypto intradía ({day} UTC)\n")
    W("## Resumen ejecutivo\n")
    W(
        "Este informe combina: (1) agregación de `crypto_testnet_auto_cycles.jsonl` del día, "
        "(2) el **último** ciclo del día con campo `entry_pipeline_audit` (disponible tras desplegar "
        "la versión que persiste digest + evaluated), (3) verificación en código del monitor vs auto.\n"
    )

    cycles = [c for c in _iter_jsonl(AUTO_JSONL) if _day_from_ts(c.get("timestamp")) == day]
    W(f"- Ciclos auto testnet ese día: **{len(cycles)}**\n")
    pr, min_scores = _aggregate_day(cycles)
    W("### Motivos `no_entry` (conteo en actions_taken)\n")
    total_no = sum(pr.values())
    for k, v in pr.most_common():
        pct = (100.0 * v / total_no) if total_no else 0.0
        W(f"- `{k}`: **{v}** ({pct:.1f}% de no_entry)\n")
    if min_scores:
        W(f"\n- `min_entry_score` en params_snapshot: min={min(min_scores):g} max={max(min_scores):g} (muestras={len(min_scores)})\n")

    audit = _pick_latest_audit(cycles)
    if audit:
        W("\n## A–F desde `entry_pipeline_audit` (último ciclo con datos)\n")
        W("### A. Universo\n")
        W(f"- watchlist_count: **{audit.get('watchlist_count')}**\n")
        W(f"- scanned_count: **{audit.get('scanned_count')}**\n")
        ss = audit.get("scan_subset") or {}
        W(f"- scan_diagnosis: `{ss.get('scan_diagnosis')}`\n")
        W(f"- scan_scenario: `{ss.get('scan_scenario')}`\n")
        W("\n### B. Señales (subset scan_debug)\n")
        W(f"- rows_signal_compra_potencial: **{ss.get('rows_signal_compra_potencial')}**\n")
        W(f"- rows_signal_other: **{ss.get('rows_signal_other')}**\n")
        W(f"- rows_missing_signal: **{ss.get('rows_missing_signal')}**\n")
        W(f"- rows_high_score_not_compra: **{ss.get('rows_high_score_not_compra')}**\n")
        sc = ss.get("signal_counts")
        if isinstance(sc, dict):
            W("- signal_counts:\n")
            for kk, vv in sorted(
                sc.items(),
                key=lambda x: (-(float(x[1]) if isinstance(x[1], (int, float)) else 0), str(x[0])),
            ):
                W(f"  - `{kk}`: {vv}\n")
        W("\n### C. Scoring (digest del scan, filas OK)\n")
        digest = audit.get("scan_rows_digest") or []
        scores: list[float] = []
        rsis: list[float] = []
        for row in digest:
            if not isinstance(row, dict):
                continue
            s = row.get("score")
            if isinstance(s, (int, float)) and s == s:
                scores.append(float(s))
            rsi = row.get("rsi_14")
            if isinstance(rsi, (int, float)) and rsi == rsi:
                rsis.append(float(rsi))
        if scores:
            W(f"- score máximo: **{max(scores):.2f}**\n")
            W(f"- score promedio: **{statistics.mean(scores):.2f}**\n")
            W(f"- top 10: **{sorted(scores, reverse=True)[:10]}**\n")
            W("- histograma scores:\n")
            for k, v in sorted(_histogram(scores).items(), key=lambda x: -x[1]):
                W(f"  - {k}: {v}\n")
        else:
            W("- (sin scores en digest)\n")
        W("\n### D. Desglose score (promedio por componente en filas con score_breakdown)\n")
        mb = _mean_breakdown(digest)
        for k in sorted(mb.keys()):
            W(f"- **{k}**: {mb[k]:.3f}\n")
        W("\n### E. Filtros post-candidato (evaluated_summary)\n")
        es = audit.get("evaluated_summary") or {}
        W(f"- evaluated_count: **{es.get('evaluated_count')}**\n")
        reasons = es.get("reasons") or {}
        if isinstance(reasons, dict):
            for k, v in sorted(reasons.items(), key=lambda x: -int(x[1]) if isinstance(x[1], int) else 0):
                W(f"  - `{k}`: {v}\n")
        W(f"- min_entry_score param ese ciclo: **{audit.get('min_entry_score_param')}**\n")
        W("\n### F. RSI (digest scan)\n")
        rh: Counter[str] = Counter()
        for rv in rsis:
            b = _rsi_bucket(rv)
            if b:
                rh[b] += 1
        for k, v in rh.most_common():
            W(f"- {k}: **{v}**\n")

        W("\n### H. Whitelist (casos en este ciclo)\n")
        wl = audit.get("whitelist_rejects") or []
        if wl:
            for item in wl:
                W(f"- **{item.get('symbol')}** score={item.get('score')} signal={item.get('signal')} setup={item.get('setup_type')}\n")
                W(f"  - motivo: {item.get('rejection_reason')}\n")
        else:
            W("- Sin rechazos whitelist en este snapshot.\n")
    else:
        W(
            "\n> No hay `entry_pipeline_audit` en ningún ciclo de esta fecha: el JSONL se generó **antes** "
            "de que el auto runner guardara este bloque (desplegar esta versión y esperar nuevos ciclos), "
            "o usá `--live-scan` para un snapshot actual con red.\n"
        )

    W("\n## G. Monitor (`crypto_testnet_monitor_cycles.jsonl`) vs Auto\n")
    mon = [c for c in _iter_jsonl(MONITOR_JSONL) if _day_from_ts(c.get("timestamp")) == day]
    W(f"- Líneas monitor día **{day}**: **{len(mon)}**\n")
    W(f"- Líneas auto día **{day}**: **{len(cycles)}**\n")
    W(
        "- **Causa (código)**: `crypto_testnet_monitor_cycles.jsonl` sólo se escribe en "
        "`services/crypto/testnet_monitor.py` cuando el **monitor asistido** está activo "
        "(POST `/crypto/testnet/monitor/start`) y el worker completa un ciclo. "
        "`crypto_testnet_auto_cycles.jsonl` lo escribe **auto testnet** (`auto_testnet_runner.py`) "
        "con el hilo del auto runner. Son **dos subsistemas independientes**: si sólo corrés auto, "
        "el monitor puede estar detenido y el JSONL del monitor quedará vacío ese día. "
        "No implica fallo de persistencia ni cambio de ruta (`data/` es la misma).\n"
    )

    if args.live_scan:
        W("\n## Live scan (ahora, red requerida)\n")
        try:
            live = _live_scan_payload(args.timeframe, args.limit, args.strategy_mode)
            W(f"- watchlist: **{live['watchlist_count']}** símbolos\n")
            W(f"- filas scan: **{live['scanned_total']}** (OK **{live['scan_ok']}**, error **{live['scan_errors']}**)\n")
            W(f"- candidatos `evaluate_entry_candidates`: **{live['candidates_evaluate_entry']}**\n")
            W(f"- señales: `{live['signal_counts']}`\n")
            if live.get("score_max") is not None:
                W(f"- score max/mean: **{live['score_max']}** / **{live['score_mean']:.2f}**\n")
                W(f"- histograma: `{live['histogram']}`\n")
            W(f"- RSI buckets: `{live['rsi_histogram']}`\n")
            W(f"- mean breakdown (filas con breakdown): `{live['mean_breakdown_ok_rows']}`\n")
        except Exception as e:
            W(f"- Error live scan: `{type(e).__name__}: {e}`\n")

    W("\n## Conclusiones y recomendaciones (basadas en datos arriba)\n")
    if total_no:
        top = pr.most_common(1)[0][0]
        W(f"1. El motivo `no_entry` más frecuente es **`{top}`** ({100 * pr[top] / total_no:.1f}% de los no_entry).\n")
        if top == "no_opportunity":
            W(
                "2. Con **`no_opportunity`**, el cuello está **antes** de `min_entry_score`: "
                "`is_entry_candidate_row` no marca filas (intradía: `compra_potencial` o setup "
                "en `DAILY_SETUP_TYPES` + `entry_eligible`). Revisar señales/score en digest vs "
                "`rows_signal_compra_potencial`.\n"
            )
        if "score_below_min" in pr:
            W(
                "3. **`score_below_min`**: el umbral configurado recorta candidatos que sí pasaron el scanner; "
                "comparar histograma con `min_entry_score` del día.\n"
            )
    W(
        "4. **Intradía 30m**: si la mayoría de scores queda <70 tras el nuevo ponderado, la estrategia "
        "puede ser coherente con mercado choppy; ajustar `min_entry_score` o relajar una banda "
        "(p. ej. volumen/ADX) sólo si el digest muestra penalización dominante en un solo componente.\n"
    )

    out_path = DATA / f"crypto_intraday_deep_audit_{day}.md"
    DATA.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines_out), encoding="utf-8")
    print(f"Informe escrito: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
