"""
Smoke tests mínimos para parsing de vencimientos Rava.

Objetivo:
- Mantener funcionando códigos de 2 letras (p.ej. JU).
- Soportar sufijos de 1 letra SOLO si están confirmados (sin inventar A-L).

Uso:
    python scripts/test_rava_expiry_codes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.options.expiry_utils import resolve_expiry_date
from services.options.rava_chain_builder import _parse_option_symbol
import services.options.expiry_utils as expiry_utils


def main() -> int:
    # Caso conocido (2 letras): JU = junio
    p1 = _parse_option_symbol("GFGC4774JU")
    assert p1 is not None and p1["expiry_code_raw"] == "JU"
    d1 = resolve_expiry_date(p1["expiry_code_raw"])
    assert d1 is not None

    # Caso confirmado (1 letra): A → abril 2027 (Allaria)
    p2 = _parse_option_symbol("GFGC10126A")
    assert p2 is not None and p2["expiry_code_raw"] == "A"
    d2 = resolve_expiry_date(p2["expiry_code_raw"])
    assert d2 is not None

    # Caso confirmado (1 letra): J → junio 2026 (Allaria)
    p3 = _parse_option_symbol("GFGC73747J")
    assert p3 is not None and p3["expiry_code_raw"] == "J"
    d3 = resolve_expiry_date(p3["expiry_code_raw"])
    assert d3 is not None

    def diag(code: str, dt) -> None:
        month = expiry_utils._MONTH_BY_CODE.get(code)  # diagnóstico (map interno)
        source = "parser" if month is not None else ("single_letter_map" if code in expiry_utils._SINGLE_LETTER_EXPIRY else "none")
        print(
            "[DIAG]",
            f"expiry_code_raw={code!r}",
            f"month={month!r}",
            f"expiry_date={(dt.isoformat() if dt else None)!r}",
            f"source={source!r}",
        )

    diag(p1["expiry_code_raw"], d1)
    diag(p2["expiry_code_raw"], d2)
    diag(p3["expiry_code_raw"], d3)

    assert d1.isoformat() == "2026-06-19"
    assert d2.isoformat() == "2027-04-16"
    assert d3.isoformat() == "2026-06-19"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

