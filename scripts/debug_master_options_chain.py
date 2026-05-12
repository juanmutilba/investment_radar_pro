"""
Prueba mínima de OptionContract + normalización + cadena maestra.

Uso (desde la raíz del repo):
    python scripts/debug_master_options_chain.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.options.chain_builder import build_master_chain, summarize_chain  # noqa: E402
from services.options.models import OptionContract  # noqa: E402


def main() -> int:
    # Duplicados mismo (underlying lógico, expiry, strike, tipo): Allaria + Rava
    contracts: list[OptionContract] = [
        OptionContract(
            underlying="GGAL",
            expiry="2026-06-19",
            strike=6655.3,
            option_type="Call",
            symbol="GFGC66553J",
            bid=240.0,
            ask=250.0,
            last=None,
            volume=1000.0,
            source="allaria",
            raw={"note": "allaria row"},
        ),
        OptionContract(
            underlying="GFG",
            expiry="2026-06-19",
            strike=6655.3,
            option_type="C",
            symbol="GFGC66553J",
            bid=None,
            ask=None,
            last=245.0,
            volume=None,
            source="rava",
            raw={"note": "rava row"},
        ),
        # Otro strike PUT
        OptionContract(
            underlying="GGAL",
            expiry="2026-06-19",
            strike=6255.3,
            option_type="Put",
            symbol="GFGV62553J",
            bid=220.0,
            ask=228.0,
            source="allaria",
        ),
        # Duplicado exacto mismo source (debería colapsar a uno)
        OptionContract(
            underlying="GFG",
            expiry="2026-06-19",
            strike=6255.3,
            option_type="PUT",
            symbol="GFGV62553J",
            bid=220.0,
            ask=228.0,
            source="allaria",
        ),
    ]

    chain = build_master_chain("GGAL", contracts)
    summary = summarize_chain(chain)

    print("[OPTIONS_CHAIN] --- Resumen ---")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("[OPTIONS_CHAIN] --- Contratos finales ---")
    for c in chain.contracts:
        print(
            f"  {c.symbol} | {c.underlying} | {c.expiry} | {c.option_type} | strike={c.strike} | "
            f"bid={c.bid} ask={c.ask} last={c.last} vol={c.volume} | src={c.source}"
        )

    assert len(chain.contracts) == 2, f"esperaba 2 contratos únicos, hay {len(chain.contracts)}"
    gfg_call = next(x for x in chain.contracts if x.symbol == "GFGC66553J")
    assert gfg_call.bid == 240.0 and gfg_call.last == 245.0, "merge Allaria+Rava falló"

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
