"""
Diagnóstico RAW: inspección del endpoint interno de Rava para mercado argentino.

Fuente:
    https://mercado.rava.com/api/prices/arg

Objetivo:
    Ver si dentro de `datos` aparecen instrumentos que parezcan opciones argentinas.

Uso (desde la raíz del repo):
    python scripts/debug_rava_prices_arg.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from typing import Any

import requests


URL = "https://mercado.rava.com/api/prices/arg"


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


def _pick_symbol(item: dict[str, Any]) -> str:
    for k in ("especie", "simbolo", "symbol", "ticker", "codigo", "code"):
        v = item.get(k)
        s = _as_str(v).strip()
        if s:
            return s
    return ""


def _pick_securitytype(item: dict[str, Any]) -> str:
    for k in ("securitytype", "securityType", "tipo", "type", "instrumentType", "instrumenttype"):
        v = item.get(k)
        s = _as_str(v).strip()
        if s:
            return s
    return ""


# Heurística: opciones ByMA suelen codificarse como BASE + (C/V) + strike (números).
_OPT_LIKE_RE = re.compile(r"^[A-Z]{3,6}[CV][0-9]{1,6}", re.IGNORECASE)
_OPT_PREFIXES = ("GFGC", "GFGV", "GGAC", "GGAV", "YPFC", "YPFV", "PAMC", "PAMV", "TXAC", "TXAV", "COME")


def _looks_like_option_symbol(sym: str) -> bool:
    s = (sym or "").strip().upper()
    if not s:
        return False
    if any(p in s for p in _OPT_PREFIXES):
        return True
    return bool(_OPT_LIKE_RE.match(s))


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
        _safe_print(
            f"[RAVA_PRICES_ARG] status_code=error error={type(e).__name__}: {e}",
            stream=sys.stderr,
        )
        return 1

    content_type = str(r.headers.get("content-type") or "")
    _safe_print(f"[RAVA_PRICES_ARG] status_code={r.status_code}")
    _safe_print(f"[RAVA_PRICES_ARG] content_type={content_type!r}")

    try:
        obj: Any = r.json()
    except ValueError as e:
        body_prefix = (r.text or "")[:2000]
        _safe_print(f"[RAVA_PRICES_ARG] json_ok=False error={e}", stream=sys.stderr)
        _safe_print(f"[RAVA_PRICES_ARG] body_prefix={body_prefix!r}", stream=sys.stderr)
        return 1

    datos = obj.get("datos") if isinstance(obj, dict) else None
    if not isinstance(datos, list):
        _safe_print(f"[RAVA_PRICES_ARG] total_items=0 (datos_missing_or_not_list)")
        _safe_print(
            f"[RAVA_PRICES_ARG] root_type={type(obj).__name__} root_keys={(list(obj.keys()) if isinstance(obj, dict) else 'n/a')}"
        )
        return 0

    total = len(datos)
    _safe_print(f"[RAVA_PRICES_ARG] total_items={total}")

    first = datos[0] if datos else None
    first_keys = list(first.keys()) if isinstance(first, dict) else []
    _safe_print(f"[RAVA_PRICES_ARG] first_keys={first_keys}")

    st_counter: Counter[str] = Counter()
    st_samples: set[str] = set()
    opt_candidates: list[dict[str, Any]] = []

    for it in datos:
        if not isinstance(it, dict):
            continue
        st = _pick_securitytype(it)
        if st:
            st_counter[st] += 1
            if len(st_samples) < 20:
                st_samples.add(st)
        sym = _pick_symbol(it)
        if _looks_like_option_symbol(sym):
            opt_candidates.append(it)

    _safe_print(f"[RAVA_PRICES_ARG] securitytype_counts={dict(st_counter)}")
    _safe_print(f"[RAVA_PRICES_ARG] sample_securitytypes={sorted(st_samples)}")
    _safe_print(f"[RAVA_PRICES_ARG] symbols_like_options_count={len(opt_candidates)}")

    for i, cand in enumerate(opt_candidates[:20], 1):
        _safe_print(f"[RAVA_PRICES_ARG] option_candidate_{i}={json.dumps(cand, ensure_ascii=False)[:4000]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

