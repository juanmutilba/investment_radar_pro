"""
Diagnóstico: cómo Rava expone tickers de subyacentes (feed prices/arg), sin ruido de substring.

Fuente:
    https://mercado.rava.com/api/prices/arg

Uso:
    python scripts/debug_rava_underlying_lookup.py
"""
from __future__ import annotations

import json
import sys
from typing import Any

import requests

URL = "https://mercado.rava.com/api/prices/arg"

EXACT_TICKERS = ("GGAL", "GFG", "ALUA", "COME", "BYMA")


def _safe_print(s: str, *, stream=None) -> None:
    st = stream or sys.stdout
    try:
        print(s, file=st, flush=True)
    except UnicodeEncodeError:
        enc = getattr(st, "encoding", None) or "utf-8"
        b = (s or "").encode(enc, errors="replace")
        (st.buffer if hasattr(st, "buffer") else sys.stdout.buffer).write(b + b"\n")
        st.flush()


def _as_str(x: Any) -> str:
    if x is None:
        return ""
    try:
        return str(x)
    except Exception:
        return ""


def _matches_ticker(item: dict[str, Any], ticker: str) -> bool:
    t = ticker.strip().upper()
    esp = _as_str(item.get("especie")).strip().upper()
    sym = _as_str(item.get("simbolo")).strip().upper()
    if sym == t or esp == t:
        return True
    prefix = f"{t}-"
    if esp.startswith(prefix):
        return True
    return False


def _summarize(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "especie": item.get("especie"),
        "simbolo": item.get("simbolo"),
        "securitytype": item.get("securitytype"),
        "moneda": item.get("moneda"),
        "plazo": item.get("plazo"),
        "ultimo": item.get("ultimo"),
        "datetime": item.get("datetime"),
    }


def main() -> int:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        )
    }
    try:
        r = requests.get(URL, headers=headers, timeout=30)
    except requests.RequestException as e:
        _safe_print(f"[RAVA_UNDERLYING_LOOKUP] error={type(e).__name__}: {e}", stream=sys.stderr)
        return 1

    try:
        obj: Any = r.json()
    except ValueError as e:
        _safe_print(f"[RAVA_UNDERLYING_LOOKUP] json_error={e}", stream=sys.stderr)
        return 1

    datos = obj.get("datos") if isinstance(obj, dict) else None
    if not isinstance(datos, list):
        _safe_print("[RAVA_UNDERLYING_LOOKUP] total_items=0 non_opt_items=0 (no datos)")
        return 0

    non_opt: list[dict[str, Any]] = []
    for it in datos:
        if not isinstance(it, dict):
            continue
        if str(it.get("securitytype") or "").strip().upper() == "OPT":
            continue
        non_opt.append(it)

    _safe_print(f"[RAVA_UNDERLYING_LOOKUP] total_items={len(datos)}")
    _safe_print(f"[RAVA_UNDERLYING_LOOKUP] non_opt_items={len(non_opt)}")

    for ticker in EXACT_TICKERS:
        found = [it for it in non_opt if _matches_ticker(it, ticker)]
        payload = [_summarize(it) for it in found]
        _safe_print(
            f"[RAVA_UNDERLYING_EXACT] ticker={ticker} matches="
            + json.dumps(payload, ensure_ascii=False, default=str)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
