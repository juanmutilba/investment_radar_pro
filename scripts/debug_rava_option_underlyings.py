"""
Diagnóstico: underlyings reales de opciones en el feed de Rava.

Objetivo:
- Descargar https://mercado.rava.com/api/prices/arg (raíz JSON: datos)
- Filtrar instrumentos OPT (si existe securitytype) y/o parsear símbolos de opciones
- Agrupar por underlying parseado y mostrar:
  - total, calls, puts
  - vencimientos detectados (expiry_code_raw)
  - ejemplos de símbolos
- Búsqueda flexible por texto (matches aunque no se pueda parsear)

Uso:
    python scripts/debug_rava_option_underlyings.py

Opcional:
    python scripts/debug_rava_option_underlyings.py --grep TRA TRAN PAM PAMP TXA TXAR YPF
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.options.rava_chain_builder import _parse_option_symbol  # noqa: E402


URL = "https://mercado.rava.com/api/prices/arg"


def _as_str(x: Any) -> str:
    if x is None:
        return ""
    try:
        return str(x)
    except Exception:
        return ""


def _pick_symbol(item: dict[str, Any]) -> str:
    for k in ("especie", "simbolo"):
        s = _as_str(item.get(k)).strip()
        if s:
            return s
    return ""


def _fetch_rava_prices_datos() -> list[dict[str, Any]]:
    req = Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    raw = urlopen(req, timeout=30).read()
    obj = json.loads(raw.decode("utf-8"))
    datos = obj.get("datos") if isinstance(obj, dict) else None
    if not isinstance(datos, list):
        return []
    return [it for it in datos if isinstance(it, dict)]


@dataclass(frozen=True)
class Group:
    total: int
    calls: int
    puts: int
    expiry_codes: list[tuple[str, int]]
    examples: list[str]


def _summarize_symbols(symbols: list[tuple[str, dict[str, str]]], *, examples_limit: int = 10) -> Group:
    total = len(symbols)
    calls = sum(1 for _, p in symbols if p.get("option_type") == "C")
    puts = sum(1 for _, p in symbols if p.get("option_type") == "V")
    expiry = Counter((p.get("expiry_code_raw") or "∅") for _, p in symbols)
    expiry_codes = sorted(expiry.items(), key=lambda kv: (-kv[1], kv[0]))
    examples = [sym for sym, _ in symbols[:examples_limit]]
    return Group(total=total, calls=calls, puts=puts, expiry_codes=expiry_codes, examples=examples)


def main(argv: list[str]) -> int:
    grep_terms: list[str] = []
    if "--grep" in argv:
        i = argv.index("--grep")
        grep_terms = [t.strip().upper() for t in argv[i + 1 :] if t.strip()]

    datos = _fetch_rava_prices_datos()
    opt_items = [it for it in datos if _as_str(it.get("securitytype")).strip().upper() == "OPT"]

    parsed_by_underlying: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
    parsed_total = 0
    parsed_from_opt = 0

    # Parsear símbolos desde todos los OPT; si faltara securitytype, el script se puede extender luego.
    for it in opt_items:
        sym = _pick_symbol(it).strip().upper()
        if not sym:
            continue
        p = _parse_option_symbol(sym)
        if p is None:
            continue
        parsed_total += 1
        parsed_from_opt += 1
        und = (p.get("underlying_guess") or "").strip().upper() or "∅"
        parsed_by_underlying[und].append((sym, p))

    # Orden estable: por total desc, luego nombre
    underlyings_sorted = sorted(parsed_by_underlying.keys(), key=lambda u: (-len(parsed_by_underlying[u]), u))

    print(f"[RAVA_OPT_UNDERLYINGS] url={URL}")
    print(f"[RAVA_OPT_UNDERLYINGS] total_items={len(datos)} opt_items={len(opt_items)} parsed_from_opt={parsed_from_opt}")

    for und in underlyings_sorted:
        group = _summarize_symbols(sorted(parsed_by_underlying[und], key=lambda x: x[0]))
        print(f"\n{und}:")
        print(f"  total={group.total} calls={group.calls} puts={group.puts}")
        print(f"  expiry_codes={group.expiry_codes[:12]}")
        print(f"  examples={group.examples}")

    if grep_terms:
        print("\n[RAVA_OPT_UNDERLYINGS] grep:")
        matches: list[str] = []
        for it in datos:
            sym = _pick_symbol(it).strip().upper()
            if not sym:
                continue
            if any(t in sym for t in grep_terms):
                matches.append(sym)
        matches = sorted(set(matches))
        for t in grep_terms:
            sub = [m for m in matches if t in m]
            print(f"  term={t!r} matches={len(sub)} samples={sub[:25]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

