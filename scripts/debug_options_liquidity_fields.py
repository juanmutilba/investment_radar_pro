"""
Auditoría de campos operativos (bid/ask/last/volumen/OI) en OptionContract.

Uso:
    python scripts/debug_options_liquidity_fields.py --underlying GGAL --source both
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.options.chain_builder import build_master_chain  # noqa: E402
from services.options.models import OptionContract  # noqa: E402
from services.options.normalizer import normalize_option_type  # noqa: E402
from services.options.providers.allaria import fetch_allaria_option_contracts  # noqa: E402
from services.options.providers.rava import fetch_rava_option_contracts  # noqa: E402


def _f(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _is_zero_field(v: float | None) -> bool:
    return v is not None and v == 0.0


def _sort_key(c: OptionContract) -> tuple:
    ot = normalize_option_type(c.option_type) or (c.option_type or "")
    return (c.expiry or "", ot, c.strike if c.strike is not None else -1.0, c.symbol or "")


def _summarize(contracts: list[OptionContract]) -> dict[str, int]:
    n = len(contracts)
    out: dict[str, int] = {"total_contracts": n}
    if n == 0:
        out.update(
            {
                "con_bid": 0,
                "con_ask": 0,
                "con_last": 0,
                "con_volume": 0,
                "con_open_interest": 0,
                "bid_zero": 0,
                "ask_zero": 0,
                "last_zero": 0,
                "volume_zero": 0,
            }
        )
        return out

    def nnon(attr: str) -> int:
        return sum(1 for c in contracts if getattr(c, attr) is not None)

    def nzero(attr: str) -> int:
        return sum(1 for c in contracts if _is_zero_field(_f(getattr(c, attr))))

    out["con_bid"] = nnon("bid")
    out["con_ask"] = nnon("ask")
    out["con_last"] = nnon("last")
    out["con_volume"] = nnon("volume")
    out["con_open_interest"] = nnon("open_interest")
    out["bid_zero"] = nzero("bid")
    out["ask_zero"] = nzero("ask")
    out["last_zero"] = nzero("last")
    out["volume_zero"] = nzero("volume")
    return out


def _print_summary(label: str, s: dict[str, int]) -> None:
    print(f"\n[{label}] resumen campos operativos")
    for k in (
        "total_contracts",
        "con_bid",
        "con_ask",
        "con_last",
        "con_volume",
        "con_open_interest",
        "bid_zero",
        "ask_zero",
        "last_zero",
        "volume_zero",
    ):
        print(f"  {k}: {s.get(k, 0)}")


def _print_table(contracts: list[OptionContract], limit: int) -> None:
    rows = sorted(contracts, key=_sort_key)[:limit]
    hdr = "source\tsymbol\texpiry\ttype\tstrike\tbid\task\tlast\tvolume\topen_interest"
    print(f"\nTabla (primeras {len(rows)} de limite {limit}, orden expiry/type/strike/symbol)")
    print(hdr)
    for c in rows:
        ot = normalize_option_type(c.option_type) or (c.option_type or "")
        print(
            f"{c.source or ''}\t{c.symbol or ''}\t{c.expiry or ''}\t{ot}\t{c.strike}\t{c.bid}\t{c.ask}\t{c.last}\t{c.volume}\t{c.open_interest}"
        )


def _first_n(filter_fn, contracts: list[OptionContract], n: int) -> list[OptionContract]:
    out: list[OptionContract] = []
    for c in sorted(contracts, key=_sort_key):
        if filter_fn(c):
            out.append(c)
            if len(out) >= n:
                break
    return out


def _print_missing_section(contracts: list[OptionContract]) -> None:
    print("\n[missing_by_field]")
    no_last = _first_n(lambda c: c.last is None, contracts, 20)
    print(f"  sin last (primeros {len(no_last)}):")
    for c in no_last:
        print(f"    {c.source}\t{c.symbol}\texp={c.expiry!r}\t{c.option_type}\tk={c.strike}")

    no_vol = _first_n(lambda c: c.volume is None, contracts, 20)
    print(f"  sin volume (primeros {len(no_vol)}):")
    for c in no_vol:
        print(f"    {c.source}\t{c.symbol}\texp={c.expiry!r}\t{c.option_type}\tk={c.strike}")

    no_ba = _first_n(lambda c: c.bid is None and c.ask is None, contracts, 20)
    print(f"  sin bid ni ask (primeros {len(no_ba)}):")
    for c in no_ba:
        print(f"    {c.source}\t{c.symbol}\texp={c.expiry!r}\t{c.option_type}\tk={c.strike}")


def _raw_truncate(v: Any, max_len: int = 100) -> str:
    try:
        s = json.dumps(v, ensure_ascii=False, default=str)
    except TypeError:
        s = repr(v)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _raw_relevant_keys(raw: dict[str, Any]) -> list[tuple[str, str]]:
    """Claves que suelen mapear a precio/volumen/OI con otro nombre."""
    if not raw:
        return []
    hints = (
        "ultimo",
        "vol",
        "bid",
        "ask",
        "compra",
        "venta",
        "precio",
        "oper",
        "lote",
        "nominal",
        "open",
        "oi",
        "interes",
        "datetime",
        "hora",
        "fecha",
        "allaria",
        "rava",
    )
    picked: list[tuple[str, str]] = []
    for k in sorted(raw.keys(), key=lambda x: str(x).lower()):
        kl = str(k).lower()
        if any(h in kl for h in hints) or str(k).startswith("_"):
            picked.append((str(k), _raw_truncate(raw[k], 120)))
    return picked


def _print_raw_sample(contracts: list[OptionContract]) -> None:
    print("\n[raw_sample] primeros 3 contratos (claves relevantes + listado de keys)")
    for i, c in enumerate(sorted(contracts, key=_sort_key)[:3]):
        print(f"\n  --- #{i + 1} {c.source} {c.symbol} exp={c.expiry!r} ---")
        raw = c.raw if isinstance(c.raw, dict) else None
        if not raw:
            print("    (sin raw)")
            continue
        keys_line = ", ".join(sorted(map(str, raw.keys())))
        if len(keys_line) > 400:
            keys_line = keys_line[:397] + "..."
        print(f"    keys: {keys_line}")
        rel = _raw_relevant_keys(raw)
        print("    relevantes:")
        for k, v in rel[:40]:
            print(f"      {k}: {v}")
        if len(rel) > 40:
            print(f"      ... ({len(rel) - 40} mas en relevantes)")
        print(f"    total_keys: {len(raw)}")


def _run_source(underlying: str, source: str, limit: int) -> None:
    print(f"\n{'=' * 60}\nFUENTE: {source.upper()}\n{'=' * 60}")
    if source == "allaria":
        raw_list = fetch_allaria_option_contracts(underlying)
    else:
        raw_list = fetch_rava_option_contracts(underlying)
    chain = build_master_chain(underlying, raw_list)
    contracts = chain.contracts
    s = _summarize(contracts)
    _print_summary(source, s)
    _print_table(contracts, limit)
    _print_missing_section(contracts)
    _print_raw_sample(contracts)


def main() -> int:
    warnings.simplefilter("default", UserWarning)
    ap = argparse.ArgumentParser(description="Auditoría bid/ask/last/volumen en opciones.")
    ap.add_argument("--underlying", default="GGAL")
    ap.add_argument("--source", choices=("allaria", "rava", "both"), default="both")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    print(f"[LIQUIDITY] underlying={args.underlying!r} source={args.source!r} limit={args.limit}", flush=True)

    if args.source == "both":
        _run_source(args.underlying, "allaria", args.limit)
        _run_source(args.underlying, "rava", args.limit)
    else:
        _run_source(args.underlying, args.source, args.limit)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
