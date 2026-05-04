"""
Exploratorio: intentar parsear símbolos de opciones desde Rava (sin modelos definitivos).

Fuente (directo a Rava, misma que /options/rava/raw):
    https://mercado.rava.com/api/prices/arg   (raíz JSON: datos)

Uso:
    python scripts/debug_rava_options_parse.py

Salida:
    - Conteos parsed/unparsed
    - Samples (primeros 30) de cada grupo
"""

from __future__ import annotations

import json
import re
import sys
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
    for k in ("especie", "simbolo"):
        v = item.get(k)
        s = _as_str(v).strip()
        if s:
            return s
    return ""


_TRAILING_EXP_RE = re.compile(r"^(?P<strike>.*?)(?P<exp>\.*[A-Z]+)$", re.IGNORECASE)


def _parse_option_symbol(raw_symbol: str) -> dict[str, str] | None:
    """
    Reglas iniciales de parsing (heurísticas):
    - Buscar la primera C o V tal que el caracter siguiente sea dígito.
    - underlying_guess: texto antes de esa C/V
    - option_type: C/V
    - resto: después de C/V
    - Separar vencimiento como sufijo alfabético final (permitiendo punto), p.ej:
        ALUC1000JU
        ALUC600.AB
        COMC45.0JU
        GFGC10524J
        GFGV43487A
    - strike_raw: parte numérica/intermedia (puede incluir '.')
    - expiry_code_raw: letras finales (sin puntos)
    """
    s = (raw_symbol or "").strip().upper()
    if not s:
        return None

    # Encontrar primera C/V seguida por dígito (evita confundir letras dentro del subyacente).
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

    strike_raw = ""
    expiry_raw = ""

    # Separar expiración como sufijo alfabético final, permitiendo '.' antes.
    m = _TRAILING_EXP_RE.match(rest)
    if m:
        expiry_raw = (m.group("exp") or "").replace(".", "").strip().upper()
        strike_part = (m.group("strike") or "").strip()
    else:
        strike_part = rest.strip()

    strike_part = strike_part.rstrip(".")

    # strike_raw = parte numérica / decimal al inicio del strike_part (si existe).
    # Permitimos cosas como "45.0" o "600".
    m2 = re.match(r"^(?P<num>[0-9]+(?:\.[0-9]+)?)", strike_part)
    if m2:
        strike_raw = m2.group("num")
    else:
        # Si no encontramos número, aún devolvemos para inspección (strike_raw vacío).
        strike_raw = ""

    return {
        "underlying_guess": underlying,
        "option_type": opt_type,
        "strike_raw": strike_raw,
        "expiry_code_raw": expiry_raw,
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
        _safe_print(f"[RAVA_OPTIONS_PARSE] status=error error={type(e).__name__}: {e}", stream=sys.stderr)
        return 1

    try:
        obj: Any = r.json()
    except ValueError as e:
        body_prefix = (r.text or "")[:2000]
        _safe_print(f"[RAVA_OPTIONS_PARSE] json_ok=False error={e}", stream=sys.stderr)
        _safe_print(f"[RAVA_OPTIONS_PARSE] body_prefix={body_prefix!r}", stream=sys.stderr)
        return 1

    datos = obj.get("datos") if isinstance(obj, dict) else None
    if not isinstance(datos, list):
        _safe_print("[RAVA_OPTIONS_PARSE] total_options=0 (datos_missing_or_not_list)")
        return 0

    opt_items: list[dict[str, Any]] = []
    for it in datos:
        if not isinstance(it, dict):
            continue
        if str(it.get("securitytype") or "").strip().upper() == "OPT":
            opt_items.append(it)

    parsed: list[dict[str, Any]] = []
    unparsed: list[dict[str, Any]] = []

    for it in opt_items:
        sym = _pick_symbol(it)
        res = _parse_option_symbol(sym)
        if res is None:
            unparsed.append({"symbol": sym, "raw_item": it})
        else:
            parsed.append({"symbol": sym, **res})

    _safe_print(f"[RAVA_OPTIONS_PARSE] total_options={len(opt_items)}")
    _safe_print(f"[RAVA_OPTIONS_PARSE] parsed_count={len(parsed)}")
    _safe_print(f"[RAVA_OPTIONS_PARSE] unparsed_count={len(unparsed)}")

    _safe_print("[RAVA_OPTIONS_PARSE] parsed_samples=" + json.dumps(parsed[:30], ensure_ascii=False)[:4000])
    _safe_print("[RAVA_OPTIONS_PARSE] unparsed_samples=" + json.dumps(unparsed[:30], ensure_ascii=False)[:4000])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

