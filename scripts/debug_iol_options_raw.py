"""
Diagnóstico puntual: token + GET cotización vs GET opciones IOL (sin Swagger).

Uso (desde la raíz del repo):
    python scripts/debug_iol_options_raw.py
    python scripts/debug_iol_options_raw.py GGAL

Requiere IOL_USERNAME / IOL_PASSWORD en .env o entorno (no imprime valores).

Conclusión comprobada con el mismo Bearer token:
    - Cotización (api/bCBA/.../Cotizacion): suele responder 200.
    - Opciones v2 (api/v2/bCBA/.../Opciones): puede responder 401
      "Authorization has been denied for this request."
      Eso indica que token/header son válidos para cotización, pero el recurso
      Opciones está restringido por plan/cuenta, no publicado, o no es el path
      correcto para esta integración. No es un fallo de armado del header en el backend.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services.market_data.providers.iol import (
    IOL_COTIZACION_URL,
    IOL_OPCIONES_V2_URL,
    configure_iol_credentials,
    get_iol_token,
)


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip()
    if not s:
        return ""
    if s.startswith("$"):
        s = s[1:].strip()
    su = s.upper()
    if su.endswith(".BA"):
        s = s[: -len(".BA")].strip()
    return s.strip().upper()


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnóstico IOL cotización vs opciones (raw HTTP).")
    p.add_argument("symbol", nargs="?", default="GGAL", help="Ticker (default: GGAL)")
    args = p.parse_args()

    raw_sym = (args.symbol or "").strip()
    norm = _normalize_symbol(raw_sym)

    u = (os.environ.get("IOL_USERNAME") or "").strip()
    pw = (os.environ.get("IOL_PASSWORD") or "").strip()
    creds_present = bool(u and pw)
    print(f"[DEBUG_IOL_OPTIONS] creds_present={creds_present}")

    configure_iol_credentials(u, pw)

    tok = get_iol_token()
    token_ok = bool(tok)
    print(f"[DEBUG_IOL_OPTIONS] token_ok={token_ok}")
    print(f"[DEBUG_IOL_OPTIONS] token_prefix={(tok[:10] if tok else '')!r}")

    quote_url = IOL_COTIZACION_URL.format(ticker=norm)
    options_url = IOL_OPCIONES_V2_URL.format(ticker=norm)

    print(f"[DEBUG_IOL_OPTIONS] quote_url={quote_url}")

    if not tok:
        print("[DEBUG_IOL_OPTIONS] quote_status=no_token")
        print("[DEBUG_IOL_OPTIONS] quote_body_prefix=")
        print(f"[DEBUG_IOL_OPTIONS] options_url={options_url}")
        print("[DEBUG_IOL_OPTIONS] options_status=no_token")
        print("[DEBUG_IOL_OPTIONS] options_body_prefix=")
        return 1

    headers = {"Authorization": f"Bearer {tok}"}

    try:
        rq = requests.get(quote_url, headers=headers, timeout=15)
        qs = str(rq.status_code)
        qb = (rq.text or "")[:500]
    except requests.RequestException as e:
        qs = f"error:{type(e).__name__}"
        qb = str(e)[:500]

    print(f"[DEBUG_IOL_OPTIONS] quote_status={qs}")
    print(f"[DEBUG_IOL_OPTIONS] quote_body_prefix={qb!r}")

    print(f"[DEBUG_IOL_OPTIONS] options_url={options_url}")

    try:
        ro = requests.get(options_url, headers=headers, timeout=15)
        os_ = str(ro.status_code)
        ob = (ro.text or "")[:500]
    except requests.RequestException as e:
        os_ = f"error:{type(e).__name__}"
        ob = str(e)[:500]

    print(f"[DEBUG_IOL_OPTIONS] options_status={os_}")
    print(f"[DEBUG_IOL_OPTIONS] options_body_prefix={ob!r}")

    return 0 if token_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
