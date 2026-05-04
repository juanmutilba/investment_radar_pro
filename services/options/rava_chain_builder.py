from __future__ import annotations

import json
import re
from typing import Any


def _as_str(x: Any) -> str:
    if x is None:
        return ""
    try:
        return str(x)
    except Exception:
        return ""


def _pick_symbol(item: dict[str, Any]) -> str:
    for k in ("especie", "simbolo"):
        v = item.get(k)
        s = _as_str(v).strip()
        if s:
            return s
    return ""


_TRAILING_EXP_RE = re.compile(r"^(?P<strike>.*?)(?P<exp>\.*[A-Z]+)$", re.IGNORECASE)


def _parse_option_symbol(raw_symbol: str) -> dict[str, str] | None:
    """
    Misma heurística que scripts/debug_rava_options_parse.py (copiada para uso interno).
    """
    s = (raw_symbol or "").strip().upper()
    if not s:
        return None

    idx = -1
    opt_type = ""
    for i, ch in enumerate(s[:-1]):
        if ch in ("C", "V") and s[i + 1].isdigit():
            idx = i
            opt_type = ch
            break
    if idx <= 0:
        return None

    underlying = s[:idx]
    rest = s[idx + 1 :]
    if not underlying or not rest:
        return None

    expiry_raw = ""
    m = _TRAILING_EXP_RE.match(rest)
    if m:
        expiry_raw = (m.group("exp") or "").replace(".", "").strip().upper()
        strike_part = (m.group("strike") or "").strip()
    else:
        strike_part = rest.strip()

    strike_part = strike_part.rstrip(".")
    m2 = re.match(r"^(?P<num>[0-9]+(?:\.[0-9]+)?)", strike_part)
    strike_raw = m2.group("num") if m2 else ""

    return {
        "underlying_guess": underlying,
        "option_type": opt_type,
        "strike_raw": strike_raw,
        "expiry_code_raw": expiry_raw,
    }


def _option_row(item: dict[str, Any]) -> dict[str, Any]:
    sym = _pick_symbol(item)
    return {
        "simbolo": sym,
        "ultimo": item.get("ultimo"),
        "bid": item.get("preciocompra"),
        "ask": item.get("precioventa"),
        "volumen": item.get("volnominal"),
        "operaciones": item.get("operaciones"),
        "fecha": item.get("fecha"),
        "hora": item.get("hora"),
        "datetime": item.get("datetime"),
    }


def _sort_strikes(side: dict[float, dict[str, Any]]) -> dict[float, dict[str, Any]]:
    return {k: side[k] for k in sorted(side.keys())}


def build_rava_option_chain(options: list[Any]) -> dict[str, Any]:
    """
    Construye cadena anidada desde items Rava (p. ej. salida de /options/rava/raw).

    chain[underlying][expiry]["calls"|"puts"][strike] = option_obj
    """
    chain: dict[str, dict[str, dict[str, dict[float, dict[str, Any]]]]] = {}

    for raw in options:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("securitytype") or "").strip().upper() != "OPT":
            continue

        sym = _pick_symbol(raw)
        parsed = _parse_option_symbol(sym)
        if parsed is None:
            continue

        strike_raw = (parsed.get("strike_raw") or "").strip()
        if not strike_raw:
            continue
        try:
            strike = float(strike_raw)
        except ValueError:
            continue

        und = parsed["underlying_guess"]
        exp = parsed["expiry_code_raw"] or "_"
        opt_type = parsed["option_type"]

        if und not in chain:
            chain[und] = {}
        if exp not in chain[und]:
            chain[und][exp] = {"calls": {}, "puts": {}}

        row = _option_row(raw)
        if opt_type == "C":
            chain[und][exp]["calls"][strike] = row
        elif opt_type == "V":
            chain[und][exp]["puts"][strike] = row

    # Ordenar strikes por subyacente / vencimiento
    for und, expiries in chain.items():
        for exp, sides in expiries.items():
            sides["calls"] = _sort_strikes(sides["calls"])
            sides["puts"] = _sort_strikes(sides["puts"])

    underlyings_count = len(chain)
    expiries_count_total = sum(len(expiries) for expiries in chain.values())

    first_u = sorted(chain.keys())[0] if chain else None
    sample_chain: dict[str, Any] = {}
    if first_u is not None:
        sample_chain = {first_u: chain[first_u]}

    print(f"[RAVA_CHAIN] underlyings_count={underlyings_count}", flush=True)
    print(f"[RAVA_CHAIN] expiries_count_total={expiries_count_total}", flush=True)
    print(
        "[RAVA_CHAIN] sample_chain=" + json.dumps(sample_chain, ensure_ascii=False, default=str)[:8000],
        flush=True,
    )

    return chain
