"""
Resolución de spot del módulo opciones:
IOL (ticker BYMA) → Yahoo .BA → fallbacks (export → IOL → Yahoo BYMA).

Uso:
    python scripts/debug_options_spot_resolution.py --underlying GGAL
    python scripts/debug_options_spot_resolution.py
    (sin --underlying: prueba GGAL, YPFD, ALUA, PAMP)
"""

from __future__ import annotations

import argparse
import os
import time
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from services.market_data.facade import get_argentina_price  # noqa: E402
from services.market_data.providers.iol import (  # noqa: E402
    configure_iol_credentials,
    get_iol_quote,
    is_iol_enabled,
)
from services.market_data.providers.yahoo_spot import yahoo_last_price  # noqa: E402
from services.options.options_service import resolve_option_chain_spot  # noqa: E402
from services.options.spot_mapping import (  # noqa: E402
    option_underlying_to_spot_symbol,
    option_underlying_to_yahoo_symbol,
)


def _row(underlying: str) -> None:
    spot_sym = option_underlying_to_spot_symbol(underlying)
    yahoo_sym = option_underlying_to_yahoo_symbol(underlying)
    iol_val = None
    iol_quote_ms = 0.0
    if spot_sym and is_iol_enabled():
        t_i = time.perf_counter()
        iq = get_iol_quote(spot_sym)
        iol_quote_ms = (time.perf_counter() - t_i) * 1000.0
        iol_val = iq.value if iq is not None else None

    yahoo_val = None
    yahoo_quote_ms = 0.0
    if yahoo_sym:
        t_y = time.perf_counter()
        yq = yahoo_last_price(yahoo_sym, "ARS")
        yahoo_quote_ms = (time.perf_counter() - t_y) * 1000.0
        yahoo_val = yq.value

    # Fallbacks clásicos (sin Yahoo .BA prioritario)
    q = get_argentina_price(spot_sym, prefer_export=True, options_spot_yahoo_symbol=None)
    t_r = time.perf_counter()
    spot, src, sym_used, meta = resolve_option_chain_spot(underlying)
    total_ms = (time.perf_counter() - t_r) * 1000.0
    print(f"underlying={underlying!r}", flush=True)
    print(f"  spot_symbol (BYMA)     = {spot_sym!r}", flush=True)
    print(f"  yahoo_symbol           = {yahoo_sym!r}", flush=True)
    print(f"  iol_attempt.value      = {iol_val!r}", flush=True)
    print(f"  yahoo_fallback.value   = {yahoo_val!r}", flush=True)
    print(f"  classic_fallback.source= {q.source!r}", flush=True)
    print(f"  classic_fallback.value = {q.value!r}", flush=True)
    print(f"  classic_fallback.symbol_used = {q.symbol_used!r}", flush=True)
    print(
        f"  resolve_option_chain_spot    = spot={spot!r} spot_source={src!r} spot_symbol={sym_used!r} meta={meta!r}",
        flush=True,
    )
    print(f"  iol_quote_ms={iol_quote_ms:.1f} yahoo_quote_ms={yahoo_quote_ms:.1f} total_ms={total_ms:.1f}", flush=True)
    print("", flush=True)


def main() -> int:
    warnings.simplefilter("default", UserWarning)
    # Reutiliza credenciales IOL como el resto de scripts (sin hardcode).
    configure_iol_credentials(os.environ.get("IOL_USERNAME", ""), os.environ.get("IOL_PASSWORD", ""))
    ap = argparse.ArgumentParser(description="Debug resolución spot opciones (IOL → Yahoo.BA → fallbacks).")
    ap.add_argument(
        "--underlying",
        action="append",
        dest="underlyings",
        metavar="SYM",
        help="Subyacente (repetible). Si se omite: GGAL, YPFD, ALUA, PAMP.",
    )
    args = ap.parse_args()
    tickers = args.underlyings if args.underlyings else ["GGAL", "YPFD", "ALUA", "PAMP"]
    print(f"[DEBUG_OPTIONS_SPOT] tickers={tickers!r}", flush=True)
    for u in tickers:
        _row(u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
