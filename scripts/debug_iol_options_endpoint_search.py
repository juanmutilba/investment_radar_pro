"""
Explora endpoints IOL (cadena de opciones vs cotización individual y variantes).

Uso (raíz del repo, IOL_USERNAME / IOL_PASSWORD en .env):
    python scripts/debug_iol_options_endpoint_search.py
    python scripts/debug_iol_options_endpoint_search.py --underlying GGAL --symbol GFGC66553J

No imprime credenciales ni el token completo (solo prefijo si hay token).
Cualquier 401/404/500 se reporta sin abortar el resto de probes.
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


def _norm(s: str) -> str:
    return _normalize_iol_ticker((s or "").strip())


def _unwrap_chain_items(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        for k in ("items", "titulos", "opciones", "data", "result", "Results"):
            v = obj.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def _row_symbol(row: dict[str, Any]) -> str | None:
    for k in ("simbolo", "Simbolo", "ticker", "Ticker", "symbol", "Symbol", "codneg", "CodNeg"):
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip().upper().replace(" ", "")
    sub = row.get("titulo") or row.get("Titulo")
    if isinstance(sub, dict):
        for k in ("simbolo", "Simbolo", "ticker", "Ticker"):
            v = sub.get(k)
            if v is not None and str(v).strip():
                return str(v).strip().upper().replace(" ", "")
    return None


def _puntas_from_obj(obj: dict[str, Any]) -> tuple[Any, str]:
    """Devuelve (puntas, ubicación) para un dict estilo cotización o fila de cadena."""
    if "puntas" in obj:
        return obj.get("puntas"), "top.puntas"
    for nest in ("cotizacion", "Cotizacion"):
        sub = obj.get(nest)
        if isinstance(sub, dict) and "puntas" in sub:
            return sub.get("puntas"), f"{nest}.puntas"
    return None, "absent"


def _describe_puntas(p: Any) -> str:
    if p is None:
        return "null"
    if isinstance(p, list):
        if len(p) == 0:
            return "[] (len=0)"
        first = p[0]
        if isinstance(first, dict):
            keys = list(first.keys())[:12]
            return f"list len={len(p)} first_keys={keys!r}"
        return f"list len={len(p)} first_type={type(first).__name__}"
    return f"type={type(p).__name__!r}"


def _find_chain_row_for_symbol(chain_json: Any, want_sym: str) -> dict[str, Any] | None:
    want = want_sym.strip().upper().replace(" ", "")
    for row in _unwrap_chain_items(chain_json):
        rs = _row_symbol(row)
        if rs == want:
            return row
    return None


def _probe_get(
    label: str,
    url: str,
    headers: dict[str, str],
    *,
    option_sym: str,
    timeout: int = 25,
) -> dict[str, Any]:
    out: dict[str, Any] = {"label": label, "url": url, "status": None, "error": None, "note": ""}
    is_chain = "/Opciones" in url
    is_quote = "/Cotizacion" in url

    try:
        r = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        out["status"] = "exc"
        out["error"] = f"{type(e).__name__}: {str(e)[:180]}"
        return out

    out["status"] = r.status_code
    if r.status_code != 200:
        out["body_prefix"] = (r.text or "")[:220]
        return out

    try:
        data: Any = r.json()
    except ValueError:
        out["note"] = "non_json_body"
        out["body_prefix"] = (r.text or "")[:220]
        return out

    out["json_kind"] = type(data).__name__
    if isinstance(data, dict):
        out["top_keys"] = list(data.keys())[:40]

    if is_chain and isinstance(data, (dict, list)):
        row = _find_chain_row_for_symbol(data, option_sym)
        if row is None:
            out["chain_row"] = "not_found"
        else:
            out["chain_row"] = "found"
            p, where = _puntas_from_obj(row)
            out["chain_puntas_where"] = where
            out["chain_puntas_desc"] = _describe_puntas(p)

    if is_quote and isinstance(data, dict):
        p, where = _puntas_from_obj(data)
        out["quote_puntas_where"] = where
        out["quote_puntas_desc"] = _describe_puntas(p)

    # GET título sin sufijo (a veces devuelve objeto con cotizacion anidada)
    if not is_chain and not is_quote and isinstance(data, dict):
        p, where = _puntas_from_obj(data)
        if p is not None or where != "absent":
            out["quote_puntas_where"] = where
            out["quote_puntas_desc"] = _describe_puntas(p)

    return out


def _print_result(row: dict[str, Any]) -> None:
    print(f"\n--- {row['label']} ---", flush=True)
    print(f"  URL: {row['url']}", flush=True)
    st = row.get("status")
    if st == "exc":
        print(f"  error: {row.get('error')}", flush=True)
        return
    print(f"  status_code: {st}", flush=True)
    if st != 200:
        bp = row.get("body_prefix")
        if bp:
            print(f"  body_prefix: {bp!r}", flush=True)
        return
    if row.get("note") == "non_json_body":
        print(f"  {row.get('note')}: {row.get('body_prefix')!r}", flush=True)
        return
    print(f"  json: {row.get('json_kind')}", flush=True)
    if "top_keys" in row:
        print(f"  top_keys: {row['top_keys']!r}", flush=True)
    for k in ("chain_row", "chain_puntas_where", "chain_puntas_desc", "quote_puntas_where", "quote_puntas_desc"):
        if k in row:
            print(f"  {k}: {row[k]}", flush=True)


def _build_urls(base: str, und: str, sym: str) -> list[tuple[str, str]]:
    b = base.rstrip("/")
    out: list[tuple[str, str]] = []

    # 1) Cadena conocida
    out.append(("chain_opciones_v1", f"{b}/api/bCBA/Titulos/{und}/Opciones"))
    out.append(("chain_opciones_v2", f"{b}/api/v2/bCBA/Titulos/{und}/Opciones"))

    # 2) Cotización individual
    out.append(("cotizacion_symbol_v1", f"{b}/api/bCBA/Titulos/{sym}/Cotizacion"))
    out.append(("cotizacion_symbol_v2", f"{b}/api/v2/bCBA/Titulos/{sym}/Cotizacion"))

    # 3) Variantes plazo + v2 trailing (pedido: …/Titulos/{symbol}/)
    for plazo in ("t0", "t1"):
        out.append((f"cotizacion_symbol_v1_plazo_{plazo}", f"{b}/api/bCBA/Titulos/{sym}/Cotizacion?plazo={plazo}"))
        out.append((f"cotizacion_symbol_v2_plazo_{plazo}", f"{b}/api/v2/bCBA/Titulos/{sym}/Cotizacion?plazo={plazo}"))

    out.append(("titulo_v2_trailing_slash", f"{b}/api/v2/bCBA/Titulos/{sym}/"))

    out.append(("titulo_v1_no_suffix", f"{b}/api/bCBA/Titulos/{sym}"))
    out.append(("titulo_v2_no_suffix", f"{b}/api/v2/bCBA/Titulos/{sym}"))

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Búsqueda de endpoints IOL con puntas en cadena vs cotización.")
    ap.add_argument("--underlying", default="GGAL", help="Subyacente para GET …/Opciones (default GGAL)")
    ap.add_argument("--symbol", default="GFGC66553J", help="Especie opción para cadena/cotización (default GFGC66553J)")
    args = ap.parse_args()

    und = _norm(args.underlying)
    sym = _norm(args.symbol)

    u = (os.environ.get("IOL_USERNAME") or "").strip()
    pw = (os.environ.get("IOL_PASSWORD") or "").strip()
    configure_iol_credentials(u, pw)

    print(f"[IOL_ENDPOINT_SEARCH] underlying_raw={args.underlying!r} underlying_norm={und!r}", flush=True)
    print(f"[IOL_ENDPOINT_SEARCH] symbol_raw={args.symbol!r} symbol_norm={sym!r}", flush=True)
    print(f"[IOL_ENDPOINT_SEARCH] creds_present={bool(u and pw)} enabled={is_iol_enabled()}", flush=True)

    tok = get_iol_token()
    if not tok:
        print("[IOL_ENDPOINT_SEARCH] no_token — no se pueden probar URLs.", flush=True)
        return 1

    print(f"[IOL_ENDPOINT_SEARCH] token_prefix={tok[:12]!r}…", flush=True)

    base = IOL_API_BASE
    urls = _build_urls(base, und, sym)
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}

    results: list[dict[str, Any]] = []
    for label, url in urls:
        r = _probe_get(label, url, headers, option_sym=sym)
        results.append(r)
        _print_result(r)

    # Resumen compacto
    print("\n=== RESUMEN ===", flush=True)
    print("label\tstatus\tchain_puntas\tquote_puntas", flush=True)
    for row in results:
        st = row.get("status")
        cp = row.get("chain_puntas_desc", "—")
        cq = row.get("quote_puntas_desc", "—")
        if "chain_puntas_desc" not in row:
            cp = "—"
        if "quote_puntas_desc" not in row:
            cq = "—"
        cr = row.get("chain_row", "")
        extra = f"\tchain_row={cr}" if cr else ""
        print(f"{row['label']}\t{st}\t{cp}\t{cq}{extra}", flush=True)

    # JSON corto de cotización v1 OK (referencia)
    for row in results:
        if row.get("label") == "cotizacion_symbol_v1" and row.get("status") == 200:
            print("\n=== Referencia: cotización v1 200 (re-fetch corto) ===", flush=True)
            try:
                r = requests.get(row["url"], headers=headers, timeout=20)
                if r.ok:
                    d = r.json()
                    if isinstance(d, dict):
                        short = {k: d.get(k) for k in ("simbolo", "Simbolo", "ultimoPrecio", "puntas") if k in d}
                        nest = d.get("cotizacion") or d.get("Cotizacion")
                        if isinstance(nest, dict):
                            short["cotizacion.puntas"] = nest.get("puntas")
                        print(json.dumps(short, ensure_ascii=False, indent=2, default=str)[:2500], flush=True)
            except requests.RequestException:
                pass
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
