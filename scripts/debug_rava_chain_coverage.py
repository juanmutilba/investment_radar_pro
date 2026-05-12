from __future__ import annotations

"""
Auditoría de cobertura de cadena de opciones Rava por underlying.

Objetivo: identificar dónde se pierden opciones (feed crudo → parser → chain builder → endpoint /chain).
Reglas:
- Sin dependencias nuevas.
- No "arregla" datos; solo audita.
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests

# Permitir ejecución directa desde repo root o desde scripts/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.options.rava_chain_builder import (  # noqa: E402
    _parse_option_symbol,
    _pick_symbol,
    build_rava_option_chain,
)


UNDERLYINGS = ["GFG", "ALU", "BYM", "YPF", "PAM", "TXA", "TRA", "COM"]


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _rava_ultimo_float(v: Any) -> float | None:
    x = _as_float(v)
    if x is None or x <= 0:
        return None
    return x


def _fetch_rava_prices_datos() -> list[Any]:
    url = "https://mercado.rava.com/api/prices/arg"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        )
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    obj: Any = r.json()
    datos = obj.get("datos") if isinstance(obj, dict) else None
    if not isinstance(datos, list):
        raise RuntimeError("Respuesta Rava no contiene lista 'datos'")
    return datos


def _build_underlying_prices(datos: list[Any]) -> dict[str, float]:
    # Replica (lo esencial) de api/app.py: spot de CS en ARS, preferir plazo 2.
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

    # Mapeos “acción” → “prefijo opciones” existentes en app.py
    for src, dst in (("GGAL", "GFG"), ("ALUA", "ALU"), ("COME", "COM"), ("BYMA", "BYM")):
        if src in underlying_prices:
            underlying_prices[dst] = underlying_prices[src]

    # Nota: para esta auditoría usamos optionUnderlying real (TRA, TXA, etc).
    # Si alguien consulta TRAN en el endpoint, hay alias en el API; acá no lo necesitamos.
    if "TRAN" in underlying_prices and "TRA" not in underlying_prices:
        underlying_prices["TRA"] = underlying_prices["TRAN"]

    return underlying_prices


def _count_chain_bucket(bucket: dict[str, Any]) -> tuple[int, int, list[str]]:
    calls = 0
    puts = 0
    examples: list[str] = []
    for exp, sides in bucket.items():
        if not isinstance(sides, dict):
            continue
        m_calls = sides.get("calls")
        m_puts = sides.get("puts")
        if isinstance(m_calls, dict):
            calls += len(m_calls)
            for _, row in list(m_calls.items())[:2]:
                if isinstance(row, dict):
                    s = str(row.get("simbolo") or "").strip()
                    if s:
                        examples.append(s)
        if isinstance(m_puts, dict):
            puts += len(m_puts)
            for _, row in list(m_puts.items())[:2]:
                if isinstance(row, dict):
                    s = str(row.get("simbolo") or "").strip()
                    if s:
                        examples.append(s)
    return calls + puts, calls, examples[:10]


def main() -> int:
    datos = _fetch_rava_prices_datos()
    opt_items = [
        it for it in datos if isinstance(it, dict) and str(it.get("securitytype") or "").strip().upper() == "OPT"
    ]
    underlying_prices = _build_underlying_prices(datos)

    chain_all = build_rava_option_chain(opt_items, underlying_prices)

    print(f"[COVERAGE] total_items={len(datos)} opt_items={len(opt_items)} chain_underlyings={len(chain_all)}")
    print(f"[COVERAGE] sample_chain_underlyings={sorted(chain_all.keys())[:40]}")
    print()

    # Precomputar parse results por símbolo
    parsed_by_symbol: dict[str, dict[str, str] | None] = {}
    sym_to_item: dict[str, dict[str, Any]] = {}
    for it in opt_items:
        sym = _pick_symbol(it)
        if not sym:
            continue
        sym_u = sym.strip().upper()
        sym_to_item[sym_u] = it
        parsed_by_symbol[sym_u] = _parse_option_symbol(sym_u)

    # Auditoría por underlying
    summary_rows: list[tuple[str, int, int, int]] = []
    for u in UNDERLYINGS:
        u = u.strip().upper()

        # A) Feed crudo: OPT cuyo símbolo empieza con prefijo u
        raw_syms = sorted([s for s in parsed_by_symbol.keys() if s.startswith(u)])
        raw_prefix_count = len(raw_syms)
        raw_examples = raw_syms[:10]

        # B) Parser: parseados con underlying_guess == u
        parsed_syms = []
        parsed_calls = 0
        parsed_puts = 0
        expiry_codes = Counter()
        for s, p in parsed_by_symbol.items():
            if p is None:
                continue
            if (p.get("underlying_guess") or "").strip().upper() != u:
                continue
            parsed_syms.append(s)
            ot = (p.get("option_type") or "").strip().upper()
            if ot == "C":
                parsed_calls += 1
            elif ot == "V":
                parsed_puts += 1
            code = (p.get("expiry_code_raw") or "").strip().upper() or "_"
            expiry_codes[code] += 1

        parsed_count = len(parsed_syms)
        parsed_examples = sorted(parsed_syms)[:10]

        # C) Chain builder: conteo final por underlying
        bucket = chain_all.get(u) if isinstance(chain_all, dict) else None
        if not isinstance(bucket, dict):
            chain_count = 0
            chain_calls = 0
            chain_examples: list[str] = []
        else:
            chain_count, chain_calls, chain_examples = _count_chain_bucket(bucket)
            chain_puts = chain_count - chain_calls

        # D) Descartes: símbolos OPT que empiezan con u pero no aparecen en chain_all[u]
        chain_symbols_set: set[str] = set()
        if isinstance(bucket, dict):
            for _exp, sides in bucket.items():
                if not isinstance(sides, dict):
                    continue
                for side in ("calls", "puts"):
                    m = sides.get(side)
                    if not isinstance(m, dict):
                        continue
                    for _strike, row in m.items():
                        if isinstance(row, dict):
                            sym = str(row.get("simbolo") or "").strip().upper()
                            if sym:
                                chain_symbols_set.add(sym)

        missing = [s for s in raw_syms if s not in chain_symbols_set]
        missing_reasons = Counter()
        missing_samples_by_reason: dict[str, list[str]] = defaultdict(list)

        for s in missing:
            p = parsed_by_symbol.get(s)
            if p is None:
                reason = "parse_fail"
            else:
                strike_raw = (p.get("strike_raw") or "").strip()
                if not strike_raw:
                    reason = "strike_raw_empty"
                else:
                    und_guess = (p.get("underlying_guess") or "").strip().upper()
                    if und_guess != u:
                        reason = f"underlying_mismatch(parsed={und_guess})"
                    else:
                        # Si llega hasta acá, debería entrar al chain; si no está,
                        # casi seguro fue strike inválido o colisión/overwrite.
                        reason = "unknown_not_in_chain"
            missing_reasons[reason] += 1
            if len(missing_samples_by_reason[reason]) < 10:
                missing_samples_by_reason[reason].append(s)

        summary_rows.append((u, raw_prefix_count, parsed_count, chain_count))

        print(f"{u}:")
        print(f"  A) raw_prefix_count={raw_prefix_count} examples={raw_examples}")
        print(
            f"  B) parsed_count={parsed_count} calls={parsed_calls} puts={parsed_puts} "
            f"expiry_codes={expiry_codes.most_common(8)} examples={parsed_examples}"
        )
        if isinstance(bucket, dict):
            chain_puts = chain_count - chain_calls
            print(f"  C) chain_count={chain_count} calls={chain_calls} puts={chain_puts} examples={chain_examples}")
        else:
            print("  C) chain_count=0 calls=0 puts=0 examples=[]")
        if missing:
            print(f"  D) missing_from_chain={len(missing)} reasons={missing_reasons.most_common(8)}")
            for r, _cnt in missing_reasons.most_common(6):
                print(f"     - {r}: {missing_samples_by_reason.get(r, [])[:8]}")
        else:
            print("  D) missing_from_chain=0")
        print()

    print("[SUMMARY] underlying raw_prefix_count / parsed_count / chain_count")
    for u, a, b, c in summary_rows:
        print(f"  {u}: {a} / {b} / {c}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

