"""
Tests mínimos para parsing de símbolo de opción (Rava):
- Normalización de strike para sufijos de 1 letra.

Uso:
    python scripts/test_rava_option_symbol_parse.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.options.rava_chain_builder import _normalize_rava_strike_with_spot, _parse_option_symbol  # noqa: E402


def main() -> int:
    spot = 8000.0

    # Caso bug confirmado: 67487J -> 6748.7 (con spot)
    p = _parse_option_symbol("GFGC67487J")
    assert p is not None and p["expiry_code_raw"] == "J"
    strike, scale = _normalize_rava_strike_with_spot(p["strike_raw"], p["expiry_code_raw"], spot)
    print("[STRIKE] GFGC67487J", "strike_raw=", p["strike_raw"], "strike_final=", strike, "scale=", scale)
    assert strike is not None
    assert abs(strike - 6748.7) < 1e-6
    assert scale == "div10"

    # Casos que NO deben escalar: 10524J / 10924J / 11324J (con spot)
    for sym, expected in [("GFGC10524J", 10524.0), ("GFGC10924J", 10924.0), ("GFGC11324J", 11324.0)]:
        px = _parse_option_symbol(sym)
        assert px is not None and px["expiry_code_raw"] == "J"
        strike2, scale2 = _normalize_rava_strike_with_spot(px["strike_raw"], px["expiry_code_raw"], spot)
        print("[STRIKE]", sym, "strike_raw=", px["strike_raw"], "strike_final=", strike2, "scale=", scale2)
        assert strike2 is not None
        assert abs(strike2 - expected) < 1e-6
        assert scale2 == "raw"

    # Caso existente 2 letras debe quedar igual.
    p2 = _parse_option_symbol("GFGC4774JU")
    assert p2 is not None
    print("[PARSE] GFGC4774JU ->", p2)
    assert p2["expiry_code_raw"] == "JU"
    assert p2["strike_raw"] == "4774"

    # Inspección: 1 letra A (no validamos el strike exacto, solo que no crashea)
    p3 = _parse_option_symbol("GFGC10126A")
    assert p3 is not None
    print("[PARSE] GFGC10126A ->", p3)

    print("[OK] symbol parse tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

