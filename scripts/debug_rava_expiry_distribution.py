"""
Debug: distribución de vencimientos Rava (prices/arg) por subyacente.

Objetivo:
- Ver cuántas opciones traen expiry_code_raw y cuántas resuelven expiry_date.
- Distribución por expiry_code_raw y por expiry_date (tercer viernes).
- Ejemplos de símbolos por cada expiry_code_raw.

Uso:
    python scripts/debug_rava_expiry_distribution.py
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

from services.options.expiry_utils import resolve_expiry_date  # noqa: E402
from services.options.rava_chain_builder import _parse_option_symbol  # noqa: E402


URL = "https://mercado.rava.com/api/prices/arg"


@dataclass(frozen=True)
class Parsed:
    symbol: str
    underlying: str
    expiry_code_raw: str
    expiry_date_iso: str | None


def _fetch_prices_arg() -> list[dict[str, Any]]:
    req = Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    raw = urlopen(req, timeout=30).read()
    obj = json.loads(raw.decode("utf-8"))
    datos = obj.get("datos") if isinstance(obj, dict) else None
    if not isinstance(datos, list):
        return []
    out: list[dict[str, Any]] = []
    for it in datos:
        if isinstance(it, dict):
            out.append(it)
    return out


def _pick_symbol(item: dict[str, Any]) -> str:
    for k in ("especie", "simbolo"):
        v = item.get(k)
        s = "" if v is None else str(v).strip()
        if s:
            return s
    return ""


def _is_option(item: dict[str, Any]) -> bool:
    return str(item.get("securitytype") or "").strip().upper() == "OPT"


def _summarize(parsed: list[Parsed], *, limit_examples_per_code: int = 8) -> str:
    total = len(parsed)
    with_exp = sum(1 for p in parsed if p.expiry_date_iso is not None)
    without_exp = total - with_exp

    by_code = Counter(p.expiry_code_raw or "∅" for p in parsed)
    by_date = Counter(p.expiry_date_iso or "∅" for p in parsed)

    examples: dict[str, list[str]] = defaultdict(list)
    for p in parsed:
        code = p.expiry_code_raw or "∅"
        if len(examples[code]) < limit_examples_per_code:
            examples[code].append(p.symbol)

    lines: list[str] = []
    lines.append(f"  total={total}")
    lines.append(f"  with_expiry_date={with_exp}")
    lines.append(f"  without_expiry_date={without_exp}")

    lines.append("  codes:")
    for code, n in by_code.most_common():
        lines.append(f"    {code} -> {n} examples={examples.get(code, [])}")

    lines.append("  expiry_dates:")
    for d in sorted(by_date.keys()):
        lines.append(f"    {d} -> {by_date[d]}")

    return "\n".join(lines)


def main() -> int:
    datos = _fetch_prices_arg()
    opt_items = [it for it in datos if _is_option(it)]

    parsed_by_underlying: dict[str, list[Parsed]] = defaultdict(list)
    for it in opt_items:
        sym = _pick_symbol(it).strip().upper()
        if not sym:
            continue
        p = _parse_option_symbol(sym)
        if p is None:
            continue
        und = p["underlying_guess"]
        code = p["expiry_code_raw"]
        exp = resolve_expiry_date(code)
        parsed_by_underlying[und].append(
            Parsed(symbol=sym, underlying=und, expiry_code_raw=code, expiry_date_iso=(exp.isoformat() if exp else None))
        )

    targets = ["GFG", "COM", "ALU", "BYM", "GGAL", "COME", "ALUA", "BYMA"]
    print(f"[RAVA_EXPIRY_DIST] url={URL} options_total={len(opt_items)} underlyings={len(parsed_by_underlying)}")

    for und in targets:
        if und not in parsed_by_underlying:
            continue
        print(f"\n{und}:")
        print(_summarize(parsed_by_underlying[und]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

