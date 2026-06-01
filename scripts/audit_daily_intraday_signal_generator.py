#!/usr/bin/env python3
"""
Auditoría del generador de `signal` en modo daily_intraday.

Ejecuta el mismo scan que el bot (watchlist + analyze_ohlcv) y documenta por qué
`signal` es neutral vs compra_potencial (umbral de etiqueta en `strategy_modes.py`).

Uso:
  python scripts/audit_daily_intraday_signal_generator.py
  python scripts/audit_daily_intraday_signal_generator.py --symbols DOGE/USDT UNI/USDT
  python scripts/audit_daily_intraday_signal_generator.py --timeframe 30m --limit 200

Salida: data/crypto_daily_intraday_signal_audit_<ts>.md
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="30m")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--strategy-mode", default="daily_intraday")
    ap.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Símbolos CCXT (ej. DOGE/USDT). Por defecto: toda la watchlist escaneada.",
    )
    args = ap.parse_args()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from services.crypto.daily_intraday_signal_explain import (
        daily_intraday_signal_rules_doc,
        explain_daily_intraday_row,
        format_explain_markdown_block,
    )
    from services.crypto.strategy_modes import (
        DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE,
        is_entry_candidate_row,
        normalize_strategy_mode,
    )
    from services.crypto.watchlist import get_crypto_watchlist, scan_crypto_watchlist

    mode = normalize_strategy_mode(args.strategy_mode)
    if mode != "daily_intraday":
        print("Este script está pensado para --strategy-mode daily_intraday", file=sys.stderr)
        return 2

    rows = scan_crypto_watchlist(timeframe=args.timeframe, limit=int(args.limit), strategy_mode=mode)
    want = {s.strip().upper() for s in (args.symbols or []) if s and str(s).strip()}
    ok_rows = [r for r in rows if isinstance(r, dict) and not r.get("error")]
    if want:
        ok_rows = [r for r in ok_rows if str(r.get("symbol") or "").strip().upper() in want]

    rows_for_candidates = (
        rows
        if not want
        else [r for r in rows if isinstance(r, dict) and str(r.get("symbol") or "").strip().upper() in want]
    )

    rules = daily_intraday_signal_rules_doc()

    n_alcista = sum(1 for r in ok_rows if str(r.get("trend") or "") == "alcista")
    n_pullback_setup = sum(1 for r in ok_rows if str(r.get("setup_type") or "") == "pullback")
    n_breakout_flag = sum(1 for r in ok_rows if r.get("breakout20") is True)
    n_eligible = sum(1 for r in ok_rows if bool(r.get("entry_eligible")))
    sig_c = Counter(str(r.get("signal") or "missing") for r in ok_rows)
    n_cp = sig_c.get("compra_potencial", 0)
    n_neutral = sig_c.get("neutral", 0)
    n_cuidado = sig_c.get("cuidado", 0)
    n_fuerte = sig_c.get("compra_fuerte", 0)

    n_candidates = sum(1 for r in rows_for_candidates if isinstance(r, dict) and is_entry_candidate_row(r, mode))

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    out_path = DATA / f"crypto_daily_intraday_signal_audit_{ts}.md"
    DATA.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    W = lines.append

    W("# Auditoría generador `signal` (daily_intraday)\n")
    W(f"- Generado UTC: `{ts}`\n")
    W(f"- timeframe: `{args.timeframe}` limit: `{args.limit}`\n")
    W(f"- Filas OK: **{len(ok_rows)}** (errores excluidos del análisis de señal)\n")
    W(f"- Watchlist símbolos: **{len(get_crypto_watchlist())}**\n")
    W("\n## 1. Función que asigna `signal`\n")
    W(f"- **Módulo:** `{rules['signal_field_generator']}`\n")
    W("\n## 2. Condiciones documentadas (código actual)\n")
    for k, v in rules.items():
        if k == "signal_field_generator":
            continue
        W(f"\n### `{k}`\n")
        W(f"{v}\n")

    W("\n## 3. Estadísticas live scan (filas OK)\n")
    W(f"| Métrica | Cantidad |\n|---|---:|\n")
    W(f"| Activos tendencia alcista (`trend==alcista`) | {n_alcista} |\n")
    W(f"| Activos `setup_type==pullback` | {n_pullback_setup} |\n")
    W(f"| Activos `breakout20==True` (flag; no es `setup_type`) | {n_breakout_flag} |\n")
    W(f"| Activos `entry_eligible==True` | {n_eligible} |\n")
    W(f"| `signal==compra_potencial` | {n_cp} |\n")
    W(f"| `signal==compra_fuerte` | {n_fuerte} |\n")
    W(f"| `signal==neutral` | {n_neutral} |\n")
    W(f"| `signal==cuidado` | {n_cuidado} |\n")
    W(f"| Filas que pasan `is_entry_candidate_row` (candidatos pipeline) | {n_candidates} |\n")
    W("\n**Conteo bruto por `signal`:**\n")
    for s, c in sorted(sig_c.items(), key=lambda x: (-x[1], x[0])):
        W(f"- `{s}`: **{c}**\n")

    W("\n## 4. Respuestas explícitas (según código)\n")
    W("1. **¿Cuello en score o en lógica de `signal`?** ")
    W("En `daily_intraday` el string `signal` es solo un **corte sobre el score entero** ")
    W("(ver `DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE` en `strategy_modes.py`); ")
    W("**no** es el mismo umbral que `min_entry_score` de la UI (entradas automáticas).\n")
    W(
        "2. **¿Hay una condición que elimine candidatos antes del filtro de score de entrada (`min_entry_score`)?** "
        "Para el **nombre de la señal**, solo el corte de etiqueta. "
        "Para **entrar al pipeline como candidato** intradía, `is_entry_candidate_row` permite "
        "`compra_potencial` **o** (`setup_type` en setups diarios **y** `entry_eligible`, con "
        "`entry_eligible` si score>=55 y setup válido). "
        "La **ejecución** filtra por `score >= min_entry_score` en `propose_testnet_entry_from_strategy` / paper.\n"
    )

    W("\n## 5. Combinaciones restrictivas (score, no `signal`)\n")
    W(
        "- **MACD + ADX:** si `mh > 0` y `adx < 20`, `macd_score` resta **6** puntos "
        "(`_weighted_entry_score_parts`).\n"
    )
    W("- **Volumen:** ver `_volume_entry_score` en `signals.py` (intradía con tramo 0.7–0.9 a -5).\n")
    W(
        "- **RSI en score:** banda neutral 50–60 da `rsi_score=0`; "
        "RSI 60–70 solo suma +6 si ADX>=25 **y** volume_ratio>=1.1; "
        "RSI>70 penaliza salvo breakout+ADX fuerte.\n"
    )
    W(
        f"- **Setup `pullback` vs `signal`:** el setup no fuerza `compra_potencial`; con score 55–"
        f"{DAILY_INTRADAY_SIGNAL_COMPRA_POTENCIAL_MIN_SCORE - 1} puede haber `signal=neutral` y aun así `entry_eligible`.\n"
    )

    W("\n## 6. Detalle por activo\n")
    if args.symbols:
        targets = [r for r in ok_rows if str(r.get("symbol") or "").strip().upper() in want]
    else:
        elig_neutral = [
            r
            for r in ok_rows
            if bool(r.get("entry_eligible")) and str(r.get("signal") or "") == "neutral"
        ]
        targets = elig_neutral[:25]
        if len(targets) < 8 and len(ok_rows) > len(targets):
            rest = [r for r in ok_rows if r not in targets]
            rest.sort(key=lambda x: float(x.get("score") or -1), reverse=True)
            targets.extend(rest[: (15 - len(targets))])
        W(
            f"_Sin `--symbols`: se listan hasta 25 filas **entry_eligible + neutral** "
            f"(hay **{len(elig_neutral)}**), rellenando con alto score si hace falta._\n"
        )

    for r in targets:
        ex = explain_daily_intraday_row(r)
        W("\n" + format_explain_markdown_block(ex))
        W("\n")

    body = "\n".join(lines)
    out_path.write_text(body, encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
