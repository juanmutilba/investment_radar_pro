#!/usr/bin/env python3
"""
Auditoría diaria del bot Testnet Auto a partir de data/crypto_testnet_auto_cycles.jsonl.

Uso:
  python scripts/audit_testnet_auto_daily.py
  python scripts/audit_testnet_auto_daily.py --date 2026-06-02
  python scripts/audit_testnet_auto_daily.py --date 2026-06-02 --out data/audit_testnet_auto_2026-06-02.md

Filtra por fecha UTC del campo `timestamp` de cada ciclo.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_CYCLES = ROOT / "data" / "crypto_testnet_auto_cycles.jsonl"


def _parse_day(s: str) -> date:
    return date.fromisoformat(s.strip())


def _cycle_day_utc(ts: str | None) -> date | None:
    if not ts or not isinstance(ts, str):
        return None
    raw = ts.strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date()
    except ValueError:
        return None


def _sf(x: Any) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def load_cycles_for_day(target: date) -> list[dict[str, Any]]:
    if not _CYCLES.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = _CYCLES.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        d = _cycle_day_utc(str(obj.get("timestamp") or ""))
        if d == target:
            out.append(obj)
    return out


def build_report(target: date, cycles: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    w = lines.append

    w(f"# Auditoría Testnet Auto — {target.isoformat()} (UTC)")
    w("")
    w("Fuente: `data/crypto_testnet_auto_cycles.jsonl` · Filtro: campo `timestamp` del ciclo (UTC).")
    w("")

    if not cycles:
        w("**No hay ciclos** para esa fecha en el JSONL (revisá la fecha o que el auto haya corrido ese día).")
        return "\n".join(lines)

    cycles.sort(key=lambda c: str(c.get("timestamp") or ""))
    t0, t1 = cycles[0].get("timestamp"), cycles[-1].get("timestamp")
    w(f"- **Ciclos del día:** {len(cycles)}")
    w(f"- **Primera marca:** {t0}")
    w(f"- **Última marca:** {t1}")
    w("")

    status_c = Counter(str(c.get("status") or "") for c in cycles)
    w("## Resumen de ciclos (status)")
    w("")
    w("| status | ciclos |")
    w("|--------|--------|")
    for k, n in status_c.most_common():
        w(f"| `{k}` | {n} |")
    w("")

    act_c: Counter[str] = Counter()
    buys_ok = buys_fail = 0
    sells_ok = sells_fail = 0
    no_entry_reasons: Counter[str] = Counter()
    entry_skip_reasons: Counter[str] = Counter()

    for c in cycles:
        for a in c.get("actions_taken") or []:
            if not isinstance(a, dict):
                continue
            t = str(a.get("type") or "")
            act_c[t] += 1
            if t == "buy_market":
                if a.get("ok"):
                    buys_ok += 1
                else:
                    buys_fail += 1
            if t == "sell_market":
                if a.get("ok"):
                    sells_ok += 1
                else:
                    sells_fail += 1
            if t == "no_entry":
                no_entry_reasons[str(a.get("primary_reason") or "—")] += 1
            if t == "entry_skip":
                entry_skip_reasons[str(a.get("reason") or "—")] += 1

    w("## Acciones agregadas (todos los ciclos)")
    w("")
    w("| type | veces |")
    w("|------|-------|")
    for k, n in act_c.most_common():
        w(f"| `{k}` | {n} |")
    w("")
    w(f"- **buy_market OK / falló:** {buys_ok} / {buys_fail}")
    w(f"- **sell_market OK / falló:** {sells_ok} / {sells_fail}")
    w("")

    w("### Motivos `no_entry` (primary_reason)")
    w("")
    w("| motivo | ciclos |")
    w("|--------|--------|")
    for k, n in no_entry_reasons.most_common(25):
        w(f"| {k} | {n} |")
    if not no_entry_reasons:
        w("| — | 0 |")
    w("")

    w("### Motivos `entry_skip`")
    w("")
    w("| motivo | veces |")
    w("|--------|-------|")
    for k, n in entry_skip_reasons.most_common(25):
        w(f"| {k} | {n} |")
    if not entry_skip_reasons:
        w("| — | 0 |")
    w("")

    # Exits summary from cycle counters
    ex_att = sum(int(c.get("exit_execution_attempted_count") or 0) for c in cycles)
    ex_ok = sum(int(c.get("exit_execution_success_count") or 0) for c in cycles)
    ex_err = sum(int(c.get("exit_execution_error_count") or 0) for c in cycles)
    ex_prop = sum(int(c.get("exit_proposals_count") or 0) for c in cycles)
    w("## Salidas (agregado por contadores de ciclo)")
    w("")
    w("| métrica | total día |")
    w("|---------|-----------|")
    w(f"| propuestas salida (`exit_proposals_count`) | {ex_prop} |")
    w(f"| ejecuciones intentadas | {ex_att} |")
    w(f"| ejecuciones OK | {ex_ok} |")
    w(f"| ejecuciones error | {ex_err} |")
    w("")

    exit_reasons: Counter[str] = Counter()
    exit_status: Counter[str] = Counter()
    for c in cycles:
        for ev in c.get("exit_position_evaluations") or []:
            if not isinstance(ev, dict):
                continue
            r = str(ev.get("exit_reason") or ev.get("reason") or "").strip() or "—"
            exit_reasons[r] += 1
            exit_status[str(ev.get("status") or "—")] += 1

    if exit_reasons:
        w("### Evaluaciones de posición (exit_position_evaluations) — motivos")
        w("")
        w("| motivo / razón | filas |")
        w("|------------------|-------|")
        for k, n in exit_reasons.most_common(30):
            w(f"| {k} | {n} |")
        w("")
    if exit_status:
        w("### Evaluaciones — status")
        w("")
        w("| status | filas |")
        w("|--------|-------|")
        for k, n in exit_status.most_common():
            w(f"| `{k}` | {n} |")
        w("")

    # Scan digest: assets "mirados" en muestra (hasta 64 filas por ciclo)
    sym_scores: dict[str, list[float]] = defaultdict(list)
    sym_signals: dict[str, Counter[str]] = defaultdict(Counter)
    sym_setup: dict[str, Counter[str]] = defaultdict(Counter)
    digest_rows = 0
    for c in cycles:
        ep = c.get("entry_pipeline_audit")
        if not isinstance(ep, dict):
            continue
        for row in ep.get("scan_rows_digest") or []:
            if not isinstance(row, dict):
                continue
            digest_rows += 1
            sym = str(row.get("symbol") or "").strip()
            if not sym:
                continue
            sc = _sf(row.get("score"))
            if sc is not None:
                sym_scores[sym].append(sc)
            sig = str(row.get("signal") or "").strip() or "—"
            sym_signals[sym][sig] += 1
            st = str(row.get("setup_type") or "").strip() or "—"
            sym_setup[sym][st] += 1

    w("## Activos en muestra `scan_rows_digest` (no es la watchlist completa; máx. ~64 filas/ciclo)")
    w("")
    w(f"- **Filas digest totales (suma ciclos):** {digest_rows}")
    w(f"- **Símbolos distintos:** {len(sym_scores)}")
    w("")
    w("| símbolo | scores (min–max) | señales (top) | setups (top) |")
    w("|---------|------------------|---------------|--------------|")
    for sym in sorted(sym_scores.keys()):
        scores = sym_scores[sym]
        lo, hi = min(scores), max(scores)
        top_sig = sym_signals[sym].most_common(1)
        sig_s = top_sig[0][0] if top_sig else "—"
        top_st = sym_setup[sym].most_common(1)
        st_s = top_st[0][0] if top_st else "—"
        w(f"| {sym} | {lo:.0f} – {hi:.0f} | {sig_s} | {st_s} |")
    if not sym_scores:
        w("| — | — | — | — |")
    w("")

    # Evaluated pipeline (candidatos evaluados con motivo)
    rej_by_reason: Counter[str] = Counter()
    rej_rows: list[tuple[str, str, float | None, str]] = []  # sym, reason, score, cycle_ts
    for c in cycles:
        ts = str(c.get("timestamp") or "")
        ep = c.get("entry_pipeline_audit")
        if not isinstance(ep, dict):
            continue
        for row in ep.get("evaluated_slim") or []:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            reason = str(row.get("reason") or "").strip() or "—"
            st = str(row.get("status") or "")
            sc = _sf(row.get("score"))
            if st == "rejected":
                rej_by_reason[reason] += 1
                rej_rows.append((sym, reason, sc, ts))

    w("## Candidatos evaluados (`evaluated_slim`, status=rejected)")
    w("")
    if rej_rows:
        w("| ciclo (UTC) | símbolo | score | motivo |")
        w("|-------------|---------|-------|--------|")
        for sym, reason, sc, ts in sorted(rej_rows, key=lambda x: x[3])[-80:]:
            scs = "—" if sc is None else f"{sc:.2f}"
            w(f"| {ts[:19]} | {sym} | {scs} | `{reason}` |")
        w("")
        w("### Conteo por motivo de rechazo")
        w("")
        w("| motivo | veces |")
        w("|--------|-------|")
        for k, n in rej_by_reason.most_common():
            w(f"| `{k}` | {n} |")
        w("")
    else:
        w("*No hay filas `evaluated_slim` con status=rejected en este día (muchas veces 0 candidatos o solo `no_entry`).*")
        w("")
        summ_reasons: Counter[str] = Counter()
        for c in cycles:
            ep = c.get("entry_pipeline_audit")
            if not isinstance(ep, dict):
                continue
            summ = ep.get("evaluated_summary") or {}
            if isinstance(summ, dict):
                for rk, rv in (summ.get("reasons") or {}).items():
                    try:
                        summ_reasons[str(rk)] += int(rv)
                    except (TypeError, ValueError):
                        summ_reasons[str(rk)] += 1
        if summ_reasons:
            w("### Resumen `evaluated_summary.reasons` (agregado)")
            w("")
            w("| motivo | veces |")
            w("|--------|-------|")
            for k, n in summ_reasons.most_common():
                w(f"| `{k}` | {n} |")
            w("")

    # Params snapshot (último ciclo)
    last = cycles[-1]
    ps = last.get("params_snapshot")
    w("## Parámetros (último ciclo del día)")
    w("")
    if isinstance(ps, dict) and ps:
        w("| parámetro | valor |")
        w("|-----------|-------|")
        for k in sorted(ps.keys()):
            w(f"| `{k}` | {ps[k]} |")
    else:
        w("_Sin `params_snapshot`._")
    w("")

    errs = [e for c in cycles for e in (c.get("errors") or []) if e]
    if errs:
        w("## Errores registrados en ciclos (muestra hasta 30)")
        w("")
        for e in errs[:30]:
            w(f"- {e}")
        w("")

    w("---")
    w("*Auditoría generada por `scripts/audit_testnet_auto_daily.py`*")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--date",
        type=str,
        default=None,
        help="Fecha UTC YYYY-MM-DD (default: hoy UTC)",
    )
    ap.add_argument("--out", type=str, default=None, help="Ruta opcional para guardar Markdown")
    args = ap.parse_args()
    if args.date:
        target = _parse_day(args.date)
    else:
        target = datetime.now(timezone.utc).date()
    cycles = load_cycles_for_day(target)
    text = build_report(target, cycles)
    print(text)
    if args.out:
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(text, encoding="utf-8")
        print(f"\n[OK] Escrito: {outp}")


if __name__ == "__main__":
    main()
