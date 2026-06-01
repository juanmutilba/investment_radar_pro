#!/usr/bin/env python3
"""
Auditoría de ciclos crypto guardados en JSONL (monitor testnet + auto testnet).

Uso (desde la raíz del repo):
  python scripts/audit_crypto_cycles_today.py
  python scripts/audit_crypto_cycles_today.py --date 2026-05-20
  python scripts/audit_crypto_cycles_today.py --verbose

Fuentes:
  data/crypto_testnet_monitor_cycles.jsonl  — ciclos del monitor (scan, candidatos, no_entry_reason).
  data/crypto_testnet_auto_cycles.jsonl    — auto runner (actions_taken con no_entry).

Los ciclos del monitor escritos tras el cambio incluyen `evaluated_summary` con conteo de
motivos rejected/skipped por candidato. Los históricos sólo tienen `no_entry_reason` a nivel ciclo.

Para ver rechazos detallados de una corrida puntual sin JSONL:
  ejecutar paper/testnet y revisar `evaluated` en la respuesta, o usar la UI de diagnóstico de ciclo.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MONITOR_JSONL = DATA / "crypto_testnet_monitor_cycles.jsonl"
AUTO_JSONL = DATA / "crypto_testnet_auto_cycles.jsonl"


def _day_from_ts(ts: str | None) -> str | None:
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[audit] no se pudo leer {path}: {e}")
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _merge_counter(c: Counter, d: dict[str, Any] | None) -> None:
    if not isinstance(d, dict):
        return
    for k, v in d.items():
        try:
            c[str(k)] += int(v)
        except (TypeError, ValueError):
            c[str(k)] += 1


def _audit_monitor(rows: list[dict[str, Any]], *, verbose: bool) -> None:
    print("\n=== Monitor testnet (crypto_testnet_monitor_cycles.jsonl) ===\n")
    if not rows:
        print("Sin registros para esa fecha.")
        return
    print(f"Ciclos del día: {len(rows)}\n")
    no_entry = Counter()
    diagnosis = Counter()
    compra_rows = Counter()
    candidates_z = Counter()
    eval_reasons = Counter()
    eval_evaluated = 0
    proposals = 0
    errors_n = 0

    for r in rows:
        ner = r.get("no_entry_reason")
        if ner is not None:
            no_entry[str(ner)] += 1
        sd = r.get("scan_debug") if isinstance(r.get("scan_debug"), dict) else {}
        dig = sd.get("scan_diagnosis")
        if dig:
            diagnosis[str(dig)] += 1
        cr = sd.get("rows_signal_compra_potencial")
        if cr is not None:
            compra_rows[str(int(cr) if isinstance(cr, (int, float)) else cr)] += 1
        cc = r.get("candidates_count")
        if cc is not None:
            candidates_z[str(int(cc) if isinstance(cc, (int, float)) else cc)] += 1
        if r.get("entry_proposal_generated"):
            proposals += 1
        if r.get("errors"):
            errors_n += 1
        es = r.get("evaluated_summary")
        if isinstance(es, dict):
            evc = es.get("evaluated_count")
            if isinstance(evc, int):
                eval_evaluated += evc
            _merge_counter(eval_reasons, es.get("reasons"))

    print("no_entry_reason (por ciclo, cuando no hubo propuesta de entrada):")
    for k, v in no_entry.most_common():
        print(f"  {k!r}: {v}")
    print("\nscan_diagnosis (del scan_debug resumido):")
    for k, v in diagnosis.most_common():
        print(f"  {k!r}: {v}")
    print("\ncandidates_count (distinct por valor):")
    for k, v in sorted(candidates_z.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {k}: {v}")
    print("\nrows_signal_compra_potencial (si está en jsonl):")
    if compra_rows:
        for k, v in sorted(compra_rows.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {k}: {v}")
    else:
        print("  (no presente en registros viejos; los nuevos incluyen más claves en scan_debug)")
    print(f"\nCiclos con propuesta de entrada generada: {proposals}")
    print(f"Ciclos con campo errors: {errors_n}")
    if eval_reasons:
        print("\nMotivos en evaluated (rejected/skipped/otros), agregados del día:")
        for k, v in eval_reasons.most_common():
            print(f"  {k!r}: {v}")
        print(f"\nTotal filas evaluated (suma de evaluated_count por ciclo): {eval_evaluated}")
    else:
        print(
            "\n(No hay `evaluated_summary` en estos registros: son ciclos anteriores al guardado "
            "detallado, o no hubo candidatos evaluados.)"
        )

    if verbose:
        print("\n--- Detalle por ciclo (timestamp, candidates, no_entry, diagnosis) ---")
        for r in sorted(rows, key=lambda x: str(x.get("timestamp") or "")):
            sd = r.get("scan_debug") if isinstance(r.get("scan_debug"), dict) else {}
            print(
                f"  {r.get('timestamp')} | cand={r.get('candidates_count')} | "
                f"compra_rows={sd.get('rows_signal_compra_potencial')} | "
                f"no_entry={r.get('no_entry_reason')!r} | diag={sd.get('scan_diagnosis')!r} | "
                f"entry_prop={r.get('entry_proposal_generated')}"
            )


def _audit_auto(rows: list[dict[str, Any]], *, verbose: bool) -> None:
    print("\n=== Auto testnet (crypto_testnet_auto_cycles.jsonl) ===\n")
    if not rows:
        print("Sin registros para esa fecha.")
        return
    print(f"Ciclos del día: {len(rows)}\n")
    no_entry_reasons = Counter()
    action_types = Counter()
    errs = 0
    for r in rows:
        if r.get("errors"):
            errs += 1
        for a in r.get("actions_taken") or []:
            if not isinstance(a, dict):
                continue
            t = str(a.get("type") or "")
            action_types[t] += 1
            if t == "no_entry":
                pr = a.get("primary_reason")
                no_entry_reasons[str(pr or "unknown")] += 1
    print("actions_taken por type:")
    for k, v in action_types.most_common():
        print(f"  {k!r}: {v}")
    print("\nno_entry -> primary_reason:")
    for k, v in no_entry_reasons.most_common():
        print(f"  {k!r}: {v}")
    print(f"\nCiclos con errors no vacío: {errs}")
    if verbose:
        print("\n--- Primeros timestamps ---")
        for r in sorted(rows, key=lambda x: str(x.get("timestamp") or ""))[:40]:
            print(f"  {r.get('timestamp')} status={r.get('status')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Auditoría de ciclos crypto del día (JSONL).")
    ap.add_argument("--date", default=None, help="Día UTC YYYY-MM-DD (default: hoy UTC).")
    ap.add_argument("--verbose", action="store_true", help="Listar cada ciclo del monitor.")
    args = ap.parse_args()
    day = (args.date or "").strip() or _today_utc_date()

    print(f"[audit] Filtrando ciclos con fecha UTC (prefijo timestamp) == {day}\n")

    mon_rows = [r for r in _iter_jsonl(MONITOR_JSONL) if _day_from_ts(r.get("timestamp")) == day]
    auto_rows = [r for r in _iter_jsonl(AUTO_JSONL) if _day_from_ts(r.get("timestamp")) == day]

    print("Archivos:")
    print(f"  monitor: {MONITOR_JSONL} ({'existe' if MONITOR_JSONL.is_file() else 'no existe'})")
    print(f"  auto:    {AUTO_JSONL} ({'existe' if AUTO_JSONL.is_file() else 'no existe'})")

    _audit_monitor(mon_rows, verbose=bool(args.verbose))
    _audit_auto(auto_rows, verbose=bool(args.verbose))

    print(
        "\n--- Interpretación rápida ---\n"
        "- candidates_count=0 y no_entry_reason tipo `no_opportunity` / diagnosis `no_opportunity`: "
        "el scanner no encontró filas que pasen `evaluate_entry_candidates` (p. ej. ninguna "
        "`compra_potencial` en trend_swing, o sin setups elegibles en daily).\n"
        "- Si hay candidatos pero muchos `score_below_min`: el umbral min_entry_score está filtrando.\n"
        "- Si hay `btc_trend_filter`: el filtro BTC trend bull está activo y BTC no alcista.\n"
        "- Cero entradas con mercado lateral y scoring más estricto suele ser coherente; "
        "comparar `rows_signal_compra_potencial` vs `candidates_count` en ciclos nuevos.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
