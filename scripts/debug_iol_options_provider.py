"""
Ejecuta el provider aislado `fetch_iol_option_contracts` (sin merge con Allaria/Rava).

Uso (credenciales IOL en .env):
    python scripts/debug_iol_options_provider.py --underlying GGAL
    python scripts/debug_iol_options_provider.py --underlying YPFD
    python scripts/debug_iol_options_provider.py --underlying ALUA
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import os  # noqa: E402

from services.market_data.providers.iol import configure_iol_credentials  # noqa: E402
from services.options.providers.iol import fetch_iol_option_contracts  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Debug fetch_iol_option_contracts.")
    ap.add_argument("--underlying", default="GGAL")
    args = ap.parse_args()

    u = (os.environ.get("IOL_USERNAME") or "").strip()
    pw = (os.environ.get("IOL_PASSWORD") or "").strip()
    print(f"[DEBUG_IOL_PROVIDER] creds_present={bool(u and pw)} underlying={args.underlying!r}", flush=True)
    configure_iol_credentials(u, pw)

    contracts = fetch_iol_option_contracts(args.underlying)
    print(f"[DEBUG_IOL_PROVIDER] count={len(contracts)}", flush=True)

    by_exp_ot: dict[tuple[str, str], int] = defaultdict(int)
    for c in contracts:
        exp = (c.expiry or "").strip() or "?"
        ot = (c.option_type or "?").strip().upper()
        by_exp_ot[(exp, ot)] += 1

    print("[DEBUG_IOL_PROVIDER] resumen expiry|tipo -> n", flush=True)
    for (exp, ot), n in sorted(by_exp_ot.items(), key=lambda x: (x[0][0], x[0][1])):
        print(f"  {exp} | {ot} -> {n}", flush=True)

    print("", flush=True)
    print("symbol\texpiry\ttype\tstrike\tbid\task\tlast\tvolume", flush=True)
    for c in contracts[:30]:
        print(
            f"{c.symbol}\t{c.expiry or ''}\t{c.option_type or ''}\t{c.strike}\t{c.bid}\t{c.ask}\t{c.last}\t{c.volume}",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
