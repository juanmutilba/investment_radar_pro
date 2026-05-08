from __future__ import annotations

import contextlib
import io
import statistics
import warnings
from collections import defaultdict
from typing import Any

import requests

from services.options.models import OptionContract
from services.options.normalizer import (
    normalize_option_type,
    normalize_strike,
    normalize_symbol,
    normalize_underlying,
)
from services.options.rava_chain_builder import (
    _pick_symbol,
    _parse_option_symbol,
    build_rava_option_chain,
)

RAVA_URL = "https://mercado.rava.com/api/prices/arg"

# Parámetro CLI / filtro → prefijo de opciones en cadena Rava (clave en chain).
_PARAM_TO_RAVA_OPTION_PREFIX: dict[str, str] = {
    "GGAL": "GFG",
    "GFG": "GFG",
    "ALUA": "ALU",
    "ALU": "ALU",
    "TXAR": "TXA",
    "TXA": "TXA",
    "TRAN": "TRA",
    "TRA": "TRA",
    "PAMP": "PAM",
    "PAM": "PAM",
    "YPFD": "YPF",
    "YPF": "YPF",
    "COME": "COM",
    "COM": "COM",
    "BYMA": "BYM",
    "BYM": "BYM",
}

# Si el prefijo pedido no está en chain, intentar estos prefijos (p. ej. TRAN → TRA).
_FALLBACK_PREFIXES: dict[str, list[str]] = {
    "TRAN": ["TRA"],
}


def _log(msg: str) -> None:
    print(f"[OPTIONS_RAVA] {msg}", flush=True)


def _underlying_scale_key(underlying_param: str) -> str:
    """Clave maestra para reglas de escala (GGAL→GFG, YPFD, ALUA, …)."""
    return normalize_underlying(underlying_param) or (underlying_param or "").strip().upper()


def _infer_bucket_strike_factor(u_key: str, median: float | None, n_valid: int) -> float:
    if n_valid == 0 or median is None:
        return 1.0
    if u_key == "GFG":
        # Escala Matriz/Rava (4255.3, …): sin factor adicional por bucket.
        return 1.0
    if u_key == "YPFD":
        return 0.01 if median > 1000.0 else 1.0
    if u_key == "ALUA":
        return 1.0
    return 1.0


def _apply_rava_strike_scale_buckets(contracts: list[OptionContract], underlying_param: str) -> None:
    """
    Tras armar contratos con strike de cadena (sin escala por subyacente), agrupa por
    (subyacente normalizado del fetch, expiry, tipo) y aplica factor según mediana del bucket.
    """
    u_key = _underlying_scale_key(underlying_param)
    groups: dict[tuple[str, str | None, str | None], list[OptionContract]] = defaultdict(list)
    for c in contracts:
        ot = normalize_option_type(c.option_type) or c.option_type
        groups[(u_key, c.expiry, ot)].append(c)

    for (uk, exp, ot) in sorted(groups.keys(), key=lambda k: (k[0], k[1] or "", k[2] or "")):
        group = groups[(uk, exp, ot)]
        strikes = []
        for c in group:
            if c.strike is None:
                continue
            try:
                x = float(c.strike)
            except (TypeError, ValueError):
                continue
            if x == x:
                strikes.append(x)
        n = len(strikes)
        median: float | None = statistics.median(strikes) if strikes else None
        factor = _infer_bucket_strike_factor(uk, median, n)
        bucket_label = f"{uk}|{exp or ''}|{ot or ''}"

        _log(
            f"strike_scale_bucket underlying={uk!r} expiry={exp!r} option_type={ot!r} "
            f"factor={factor} median={median!r} n={n}"
        )

        for c in group:
            if c.raw is None:
                c.raw = {}
            c.raw["rava_strike_bucket"] = bucket_label
            c.raw["rava_strike_factor"] = factor
            if c.strike is None:
                continue
            try:
                orig = float(c.strike)
            except (TypeError, ValueError):
                continue
            if orig != orig:
                continue
            c.raw["rava_strike_original"] = round(orig, 4)
            c.strike = round(orig * factor, 4)


def _rava_option_prefix_for_param(underlying: str) -> str:
    u = (underlying or "").strip().upper()
    if u in _PARAM_TO_RAVA_OPTION_PREFIX:
        return _PARAM_TO_RAVA_OPTION_PREFIX[u]
    return normalize_underlying(u) or u


def _fetch_rava_datos() -> list[Any]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        )
    }
    r = requests.get(RAVA_URL, headers=headers, timeout=30)
    r.raise_for_status()
    obj: Any = r.json()
    datos = obj.get("datos") if isinstance(obj, dict) else None
    if not isinstance(datos, list):
        return []
    return datos


def _rava_ultimo_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x <= 0:
        return None
    return x


def _build_underlying_prices(datos: list[Any]) -> dict[str, float]:
    """Replica lógica de api/app.py para spot (CS ARS plazo 2/1) y alias GGAL→GFG, TRAN→TRA."""
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

    for src, dst in (("GGAL", "GFG"), ("ALUA", "ALU"), ("COME", "COM"), ("BYMA", "BYM")):
        if src in underlying_prices:
            underlying_prices[dst] = underlying_prices[src]

    for main, aliases in (("TRAN", ["TRA"]),):
        if main in underlying_prices:
            for a in aliases:
                underlying_prices.setdefault(a, underlying_prices[main])

    return underlying_prices


def _collect_opt_items(datos: list[Any]) -> list[dict[str, Any]]:
    """OPT explícitos + ítems sin securitytype que parsean como opción (alineado a rava_chain_builder)."""
    out: list[dict[str, Any]] = []
    for it in datos:
        if not isinstance(it, dict):
            continue
        st = str(it.get("securitytype") or "").strip().upper()
        if st == "OPT":
            out.append(it)
            continue
        if not st:
            sym = _pick_symbol(it)
            if sym and _parse_option_symbol(sym) is not None:
                out.append(it)
    return out


def _index_raw_by_symbol(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for it in items:
        s = _pick_symbol(it).strip().upper()
        if s:
            if s in idx:
                warnings.warn(f"[OPTIONS_RAVA] símbolo duplicado en feed, último gana: {s!r}", UserWarning, stacklevel=2)
            idx[s] = it
    return idx


def _merge_expiry_buckets(parts: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for part in parts:
        if not isinstance(part, dict):
            continue
        for exp, bucket in part.items():
            if not isinstance(bucket, dict):
                continue
            cur = merged.get(exp)
            if not isinstance(cur, dict):
                cur = {"calls": {}, "puts": {}}
                merged[exp] = cur
            for side in ("calls", "puts"):
                m = bucket.get(side)
                if isinstance(m, dict):
                    cur.setdefault(side, {})
                    cur[side].update(m)
    return merged


def _bucket_for_prefix(chain: dict[str, Any], prefix: str, param: str) -> dict[str, Any]:
    if prefix in chain:
        return chain[prefix]
    fallbacks = _FALLBACK_PREFIXES.get((param or "").strip().upper(), [])
    parts = [chain[p] for p in fallbacks if p in chain]
    if not parts:
        return {}
    if len(parts) == 1:
        return parts[0]
    return _merge_expiry_buckets(parts)


def _row_to_contract(
    *,
    row: dict[str, Any],
    raw_item: dict[str, Any] | None,
    option_prefix: str,
    strike: float,
    side_label: str,
) -> OptionContract | None:
    sym = normalize_symbol(row.get("simbolo"))
    if not sym:
        return None

    expiry_iso = row.get("expiry_date")
    if expiry_iso is not None:
        expiry_iso = str(expiry_iso).strip() or None
        if expiry_iso:
            expiry_iso = expiry_iso[:10]

    ot = normalize_option_type("C" if side_label == "calls" else "V")
    if ot is None:
        warnings.warn(f"[OPTIONS_RAVA] tipo lateral no normalizable symbol={sym!r}", UserWarning, stacklevel=2)
        return None

    strike_n = normalize_strike(strike)
    if strike_n is None:
        warnings.warn(f"[OPTIONS_RAVA] strike no normalizable symbol={sym!r} strike={strike!r}", UserWarning, stacklevel=2)
        return None

    u_norm = normalize_underlying(option_prefix) or option_prefix

    bid = normalize_strike(row.get("bid"))
    ask = normalize_strike(row.get("ask"))
    last = normalize_strike(row.get("ultimo"))
    if last is None and row.get("option_price") is not None:
        last = normalize_strike(row.get("option_price"))
    vol = normalize_strike(row.get("volumen_float"))

    raw_out: dict[str, Any]
    if raw_item is not None:
        raw_out = dict(raw_item)
    else:
        raw_out = {"_rava_chain_row": dict(row), "_note": "sin item crudo en índice por símbolo"}

    return OptionContract(
        underlying=u_norm,
        expiry=expiry_iso,
        strike=float(strike_n),
        option_type=ot,
        symbol=sym,
        bid=bid,
        ask=ask,
        last=last,
        volume=vol,
        open_interest=None,
        source="rava",
        raw=raw_out,
    )


def _flatten_bucket_to_contracts(
    bucket: dict[str, Any],
    option_prefix: str,
    raw_by_symbol: dict[str, dict[str, Any]],
) -> list[OptionContract]:
    out: list[OptionContract] = []
    for _exp_key, sides in bucket.items():
        if not isinstance(sides, dict):
            continue
        for side_name in ("calls", "puts"):
            m = sides.get(side_name)
            if not isinstance(m, dict):
                continue
            for strike_f, row in m.items():
                if not isinstance(row, dict):
                    continue
                try:
                    strike = float(strike_f)
                except (TypeError, ValueError):
                    continue
                sym_key = _pick_symbol(row).strip().upper()
                raw_item = raw_by_symbol.get(sym_key)
                c = _row_to_contract(
                    row=row,
                    raw_item=raw_item,
                    option_prefix=option_prefix,
                    strike=strike,
                    side_label=side_name,
                )
                if c is not None:
                    out.append(c)
    return out


def fetch_rava_option_contracts(underlying: str) -> list[OptionContract]:
    """
    Descarga prices/arg, construye cadena con build_rava_option_chain y devuelve OptionContract
    para el prefijo de opciones asociado al parámetro (p. ej. GGAL → GFG).
    """
    prefix = _rava_option_prefix_for_param(underlying)
    _log(f"fetch start underlying_param={underlying!r} rava_prefix={prefix!r}")

    datos = _fetch_rava_datos()
    opt_items = _collect_opt_items(datos)
    raw_by_symbol = _index_raw_by_symbol(opt_items)
    prices = _build_underlying_prices(datos)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        chain = build_rava_option_chain(opt_items, prices)

    spilled = buf.getvalue().strip()
    if spilled:
        _log(f"build_rava_option_chain log (truncated)={spilled[:500]!r}...")

    bucket = _bucket_for_prefix(chain, prefix, underlying)
    if not bucket:
        warnings.warn(
            f"[OPTIONS_RAVA] sin bucket para prefix={prefix!r} param={underlying!r}",
            UserWarning,
            stacklevel=2,
        )

    contracts = _flatten_bucket_to_contracts(bucket, prefix, raw_by_symbol)
    _apply_rava_strike_scale_buckets(contracts, underlying)
    _log(f"contracts count={len(contracts)} (opt_items={len(opt_items)})")

    n_no_exp = sum(1 for c in contracts if not c.expiry)
    if n_no_exp:
        _log(f"WARN contratos sin expiry parseada: {n_no_exp}/{len(contracts)}")

    return contracts
