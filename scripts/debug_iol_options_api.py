"""
Prueba varios endpoints IOL (cotización / opciones v1 y v2) con el mismo Bearer que el resto del repo.

Uso (raíz del repo, credenciales en .env o entorno IOL_USERNAME / IOL_PASSWORD):
    python scripts/debug_iol_options_api.py --underlying GGAL
    python scripts/debug_iol_options_api.py --symbols "GGAL,GFG,YPFD,ALUA"

No imprime usuario, clave ni token completo.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from services.cedear_service import _normalize_iol_ticker  # noqa: E402
from services.market_data.providers.iol import (  # noqa: E402
    IOL_API_BASE,
    configure_iol_credentials,
    get_iol_token,
    is_iol_enabled,
)


def _url_templates(sym: str) -> list[tuple[str, str]]:
    """(label, full_url)"""
    t = _normalize_iol_ticker(sym)
    base = IOL_API_BASE.rstrip("/")
    return [
        ("opciones_v2", f"{base}/api/v2/bCBA/Titulos/{t}/Opciones"),
        ("opciones_v1", f"{base}/api/bCBA/Titulos/{t}/Opciones"),
        ("cotizacion_v1", f"{base}/api/bCBA/Titulos/{t}/Cotizacion"),
        ("cotizacion_v2", f"{base}/api/v2/bCBA/Titulos/{t}/Cotizacion"),
    ]


def _json_top_keys(obj: Any) -> str:
    if isinstance(obj, dict):
        keys = list(obj.keys())
        return f"dict keys({len(keys)})={keys[:30]!r}{'…' if len(keys) > 30 else ''}"
    if isinstance(obj, list):
        return f"list len={len(obj)}"
    return f"type={type(obj).__name__}"


def _unwrap_list(obj: Any) -> tuple[list[Any], str]:
    if isinstance(obj, list):
        return obj, "root_list"
    if isinstance(obj, dict):
        for k in ("items", "titulos", "opciones", "data", "result", "Results"):
            v = obj.get(k)
            if isinstance(v, list):
                return v, f"dict[{k!r}]"
    return [], "none"


def _sample_items(items: list[Any], n: int = 3) -> list[Any]:
    out: list[Any] = []
    for it in items[:n]:
        if isinstance(it, dict):
            out.append({k: it[k] for k in list(it.keys())[:25]})
        else:
            out.append(it)
    return out


def _probe_one_url(label: str, url: str, headers: dict[str, str], timeout: int = 20) -> None:
    print(f"  [{label}]", flush=True)
    print(f"    URL={url}", flush=True)
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        print(f"    status=error type={type(e).__name__} msg={str(e)[:200]!r}", flush=True)
        return
    st = r.status_code
    print(f"    status_code={st}", flush=True)
    body = (r.text or "")[:400]
    if st != 200:
        print(f"    body_prefix={body!r}", flush=True)
        return
    try:
        data: Any = r.json()
    except ValueError:
        print(f"    json=invalid body_prefix={body!r}", flush=True)
        return
    print(f"    {_json_top_keys(data)}", flush=True)
    inner, where = _unwrap_list(data)
    if inner:
        print(f"    unwrapped={where} count={len(inner)}", flush=True)
        for i, s in enumerate(_sample_items(inner)):
            try:
                sjson = json.dumps(s, ensure_ascii=False, default=str)[:500]
            except TypeError:
                sjson = str(s)[:500]
            print(f"    sample[{i}]={sjson}", flush=True)
    elif isinstance(data, dict):
        # cotización suele ser un solo dict
        try:
            short = json.dumps(data, ensure_ascii=False, default=str)[:600]
        except TypeError:
            short = str(data)[:600]
        print(f"    body_short={short}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnóstico HTTP endpoints IOL opciones/cotización.")
    ap.add_argument("--underlying", default="GGAL", help="Ticker a probar si no se pasa --symbols (default: GGAL).")
    ap.add_argument(
        "--symbols",
        default="",
        help='Lista CSV (ej. "GGAL,GFG,YPFD,ALUA"). Vacío = solo --underlying.',
    )
    args = ap.parse_args()

    if args.symbols.strip():
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = [args.underlying.strip() or "GGAL"]

    u = (os.environ.get("IOL_USERNAME") or "").strip()
    pw = (os.environ.get("IOL_PASSWORD") or "").strip()
    print(f"[IOL_OPTIONS_API] creds_present={bool(u and pw)} symbols={symbols!r}", flush=True)

    configure_iol_credentials(u, pw)
    if not is_iol_enabled():
        print("[IOL_OPTIONS_API] IOL deshabilitado: defina IOL_USERNAME e IOL_PASSWORD.", flush=True)
        return 1

    tok = get_iol_token()
    if not tok:
        print("[IOL_OPTIONS_API] No se pudo obtener token.", flush=True)
        return 1
    print(f"[IOL_OPTIONS_API] token_ok=True prefix={tok[:8]!r}…", flush=True)

    headers = {"Authorization": f"Bearer {tok}"}

    for raw_sym in symbols:
        norm = _normalize_iol_ticker(raw_sym)
        print("", flush=True)
        print(f"[IOL_OPTIONS_API] symbol_raw={raw_sym!r} normalized={norm!r}", flush=True)
        for label, url in _url_templates(raw_sym):
            _probe_one_url(label, url, headers)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
