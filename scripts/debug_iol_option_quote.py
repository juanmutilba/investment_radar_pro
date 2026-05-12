"""
Auditoría bid/ask IOL para una especie de opción concreta.

Uso (raíz del repo):
    python scripts/debug_iol_option_quote.py --underlying GGAL --symbol GFGC66553J

Requiere IOL_USERNAME / IOL_PASSWORD (o credenciales ya configuradas en memoria).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services.market_data.providers.iol import (
    IOL_API_BASE,
    IOL_COTIZACION_URL,
    IolOptionsRawError,
    ensure_iol_credentials_from_env,
    get_iol_options_raw,
    get_iol_quote,
    get_iol_token,
    is_iol_enabled,
)
from services.options.providers.iol import (
    _bid_ask_from_row,
    _flatten_row,
    _row_to_contract,
    _unwrap_options_list,
)
from services.options.spot_mapping import option_underlying_to_spot_symbol

IOL_COTIZACION_V2_URL = f"{IOL_API_BASE}/api/v2/bCBA/Titulos/{{ticker}}/Cotizacion"

_TOP_FIELDS = (
    "ultimoPrecio",
    "precioCompra",
    "precioVenta",
    "volumenNominal",
    "montoOperado",
    "interesesAbiertos",
    "cantidadOperaciones",
    "fechaHora",
)


def _norm_sym(s: str) -> str:
    return (s or "").strip().upper().replace(" ", "")


def _symbol_from_chain_row(row: dict[str, Any]) -> str | None:
    flat = _flatten_row(row)
    for k in ("simbolo", "Simbolo", "ticker", "Ticker", "symbol", "Symbol", "codneg", "CodNeg"):
        v = flat.get(k)
        if v is not None and str(v).strip():
            return str(v).strip().upper().replace(" ", "")
    return None


def _find_chain_row(rows: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    t = _norm_sym(target)
    for row in rows:
        if _symbol_from_chain_row(row) == t:
            return row
    return None


def _nested_cotizacion(row: dict[str, Any]) -> dict[str, Any] | None:
    for k in ("cotizacion", "Cotizacion"):
        v = row.get(k)
        if isinstance(v, dict):
            return v
    return None


def _puntas_full(row: dict[str, Any]) -> Any:
    c = _nested_cotizacion(row)
    if not isinstance(c, dict):
        return None
    return c.get("puntas")


def _dump_top_fields(label: str, obj: Any) -> None:
    print(f"\n--- {label} (campos top-level pedidos) ---")
    if not isinstance(obj, dict):
        print(f"  (no es dict: {type(obj).__name__})")
        return
    for k in _TOP_FIELDS:
        if k in obj:
            print(f"  {k} = {obj[k]!r}")


def _http_cotizacion(token: str, symbol: str, version: str) -> tuple[int, Any]:
    sym = _norm_sym(symbol)
    if version == "v2":
        url = IOL_COTIZACION_V2_URL.format(ticker=sym)
    else:
        url = IOL_COTIZACION_URL.format(ticker=sym)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        code = r.status_code
        try:
            body: Any = r.json()
        except Exception:
            body = (r.text or "")[:2000]
        return code, body
    except requests.RequestException as e:
        return -1, f"{type(e).__name__}: {e}"


def main() -> int:
    p = argparse.ArgumentParser(description="Auditoría cotización/puntas IOL para una especie de opción.")
    p.add_argument("--symbol", required=True, help="Especie exacta IOL, ej. GFGC66553J")
    p.add_argument("--underlying", default="GGAL", help="Subyacente cadena opciones (default: GGAL)")
    args = p.parse_args()

    sym = _norm_sym(args.symbol)
    und = (args.underlying or "").strip() or "GGAL"

    ensure_iol_credentials_from_env()
    if not is_iol_enabled():
        print("[DEBUG_IOL_OPTION_QUOTE] IOL deshabilitado: faltan credenciales (IOL_USERNAME / IOL_PASSWORD).")
        return 1

    spot = option_underlying_to_spot_symbol(und)
    if not spot:
        print(f"[DEBUG_IOL_OPTION_QUOTE] underlying inválido: {und!r}")
        return 1

    print(f"[DEBUG_IOL_OPTION_QUOTE] underlying={und!r} spot={spot!r} symbol={sym!r}")

    # --- A) Cadena opciones ---
    chain_row: dict[str, Any] | None = None
    raw_chain: Any = None
    try:
        raw_chain = get_iol_options_raw(spot)
    except IolOptionsRawError as e:
        print(f"[DEBUG_IOL_OPTION_QUOTE] cadena error http={e.status_code} detail={e.detail!r}")
    except Exception as ex:
        print(f"[DEBUG_IOL_OPTION_QUOTE] cadena error ex={type(ex).__name__}: {ex}")

    rows: list[dict[str, Any]] = []
    if raw_chain is not None:
        rows = _unwrap_options_list(raw_chain)
        chain_row = _find_chain_row(rows, sym)

    print(f"\n=== A) Cadena IOL === rows_in_chain={len(rows)} found_in_chain={chain_row is not None}")
    if chain_row is not None:
        print("\n--- raw item completo (cadena, esta especie) ---")
        print(json.dumps(chain_row, ensure_ascii=False, indent=2, default=str))

        cot = _nested_cotizacion(chain_row)
        print("\n--- cotizacion anidada completa (desde cadena) ---")
        print(json.dumps(cot, ensure_ascii=False, indent=2, default=str) if cot else "null")

        puntas = _puntas_full(chain_row)
        print("\n--- puntas completo (desde cadena) ---")
        print(json.dumps(puntas, ensure_ascii=False, indent=2, default=str))

        flat = _flatten_row(chain_row)
        _dump_top_fields("flat merge (sin copiar puntas)", flat)
        bid, ask, plen = _bid_ask_from_row(chain_row, flat)
        print(
            f"\n[OPTIONS_IOL_QUOTE] symbol={sym} raw_bid={flat.get('precioCompra')!r} raw_ask={flat.get('precioVenta')!r} "
            f"parsed_bid={bid!r} parsed_ask={ask!r} puntas_len={plen}"
        )
        c = _row_to_contract(und, chain_row)
        if c:
            print(
                "\n--- OptionContract parseado (cadena) ---\n"
                f"  bid={c.bid!r} ask={c.ask!r} last={c.last!r} volume={c.volume!r} open_interest={c.open_interest!r}"
            )
    else:
        print("(No hay fila en la cadena para esta especie; revisar símbolo o plan IOL Opciones.)")

    # --- B) Cotización individual v1 / v2 + get_iol_quote ---
    tok = get_iol_token()
    if not tok:
        print("\n[DEBUG_IOL_OPTION_QUOTE] sin token; no se consulta Cotizacion individual.")
        return 0 if chain_row else 1

    for ver in ("v1", "v2"):
        code, body = _http_cotizacion(tok, sym, ver)
        print(f"\n=== B) GET Cotizacion {ver} status={code} ===")
        if isinstance(body, dict):
            print(json.dumps(body, ensure_ascii=False, indent=2, default=str))
            _dump_top_fields(f"respuesta {ver}", body)
            for nest in ("cotizacion", "Cotizacion"):
                sub = body.get(nest)
                if isinstance(sub, dict):
                    print(f"\n--- anidado {ver}.{nest} ---")
                    print(json.dumps(sub, ensure_ascii=False, indent=2, default=str))
                    _dump_top_fields(f"{ver}.{nest}", sub)
                    pt = sub.get("puntas")
                    if pt is not None:
                        print(f"\n--- {ver}.{nest}.puntas ---")
                        print(json.dumps(pt, ensure_ascii=False, indent=2, default=str))
        else:
            print(repr(body)[:3000])

    iq = get_iol_quote(sym)
    print("\n=== get_iol_quote(symbol) ===")
    print(repr(iq))

    # Si la cadena no tuvo fila pero v1 devolvió dict, intentar parse como row synthetic
    if chain_row is None and isinstance(raw_chain, (list, dict)):
        code1, body1 = _http_cotizacion(tok, sym, "v1")
        if isinstance(body1, dict):
            synthetic: dict[str, Any] = {"simbolo": sym, "cotizacion": body1.get("cotizacion") or body1}
            flat_s = _flatten_row(synthetic)
            b2, a2, pl2 = _bid_ask_from_row(synthetic, flat_s)
            print(
                f"\n--- parse sintético solo desde cotizacion v1 --- bid={b2!r} ask={a2!r} puntas_len={pl2} "
                f"(útil si la especie no está en cadena pero sí en Titulos/Cotizacion)"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
