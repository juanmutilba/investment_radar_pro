"""
Diagnóstico temporal: cruza data/cedear_mappings.json con cotizaciones IOL
(misma URL/token que producción vía get_iol_quote).

Uso (desde la raíz del repo):
    python scripts/debug_iol_cedear_symbols.py
        → informe: todos los CEDEAR activos, resumen + MISS_CCL (sonda HTTP si aplica).

    python scripts/debug_iol_cedear_symbols.py --pipe-csv-sample
        → CSV con separador |; primeras 40 filas (legado).

Requiere en el entorno o en .env (sin imprimir valores):
    IOL_USERNAME, IOL_PASSWORD
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services.cedear_service import _normalize_iol_ticker
from services.market_data.providers.iol import (
    IOL_COTIZACION_URL,
    configure_iol_credentials,
    get_iol_quote,
    get_iol_token,
    is_iol_enabled,
)

CEDEAR_SAMPLE = 40


def _price_cell(q) -> str:
    if q is None:
        return ""
    v = getattr(q, "value", None)
    cur = getattr(q, "currency", "") or ""
    if v is None:
        return ""
    return f"{v:g} {cur}".strip()


def _row_status(ars_ok: bool, ccl_ok: bool, ars_skip: bool, ccl_skip: bool) -> str:
    if ars_skip or ccl_skip:
        parts = []
        if ars_skip:
            parts.append("sin_ars_map")
        if ccl_skip:
            parts.append("sin_ccl_map")
        return "|".join(parts) if parts else "skip"
    if ars_ok and ccl_ok:
        return "OK"
    if not ars_ok and not ccl_ok:
        return "MISS_BOTH"
    if not ars_ok:
        return "MISS_ARS"
    return "MISS_CCL"


def _probe_ccl_http_status(iol_ccl: str, token: str) -> int | None:
    """GET directo (sin caché IOL del módulo) para registrar http_status en diagnóstico."""
    t = (iol_ccl or "").strip().upper()
    if not t:
        return None
    try:
        url = IOL_COTIZACION_URL.format(ticker=t)
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=3)
        return int(r.status_code)
    except Exception:
        return None


def run_pipe_csv_sample() -> int:
    user = (os.environ.get("IOL_USERNAME") or "").strip()
    pwd = (os.environ.get("IOL_PASSWORD") or "").strip()
    configure_iol_credentials(user, pwd)

    path = ROOT / "data" / "cedear_mappings.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    active: list[dict] = [r for r in rows if r.get("activo") is True][:CEDEAR_SAMPLE]

    if not is_iol_enabled():
        print("IOL no configurado (faltan IOL_USERNAME / IOL_PASSWORD en entorno o .env).", file=sys.stderr)
        token_ok = False
    else:
        token_ok = get_iol_token() is not None
        if not token_ok:
            print("No se pudo obtener token IOL (revisar credenciales sin exponerlas).", file=sys.stderr)

    out = io.StringIO()
    w = csv.writer(out, delimiter="|", lineterminator="\n")
    w.writerow(
        [
            "ticker_usa",
            "ars_map",
            "ccl_map",
            "iol_ars",
            "iol_ccl",
            "ars_ok",
            "ccl_ok",
            "ars_price",
            "ccl_price",
            "status",
        ]
    )

    for r in active:
        usa = str(r.get("ticker_usa") or "")
        ars_map = (r.get("ticker_cedear_ars") or "") or ""
        ccl_map = (r.get("ticker_cedear_ccl") or "") or ""
        ars_skip = not str(ars_map).strip()
        ccl_skip = not str(ccl_map).strip()
        iol_ars = _normalize_iol_ticker(ars_map) if not ars_skip else ""
        iol_ccl = _normalize_iol_ticker(ccl_map) if not ccl_skip else ""

        q_ars = None
        q_ccl = None
        if token_ok and not ars_skip and iol_ars:
            q_ars = get_iol_quote(iol_ars)
        if token_ok and not ccl_skip and iol_ccl:
            q_ccl = get_iol_quote(iol_ccl)

        ars_ok = q_ars is not None
        ccl_ok = q_ccl is not None
        status = _row_status(ars_ok, ccl_ok, ars_skip, ccl_skip)
        if not token_ok:
            status = "TOKEN_OR_AUTH" if is_iol_enabled() else "IOL_DISABLED"

        w.writerow(
            [
                usa,
                ars_map,
                ccl_map,
                iol_ars,
                iol_ccl,
                "Y" if ars_ok else "N",
                "Y" if ccl_ok else "N",
                _price_cell(q_ars),
                _price_cell(q_ccl),
                status,
            ]
        )

    sys.stdout.write(out.getvalue())
    return 0


def run_report() -> int:
    user = (os.environ.get("IOL_USERNAME") or "").strip()
    pwd = (os.environ.get("IOL_PASSWORD") or "").strip()
    configure_iol_credentials(user, pwd)

    path = ROOT / "data" / "cedear_mappings.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    active: list[dict] = [r for r in rows if r.get("activo") is True]

    token: str | None = None
    if not is_iol_enabled():
        print("IOL no configurado (faltan IOL_USERNAME / IOL_PASSWORD en entorno o .env).", file=sys.stderr)
    else:
        token = get_iol_token()
        if not token:
            print("No se pudo obtener token IOL (revisar credenciales sin exponerlas).", file=sys.stderr)

    token_ok = bool(token)

    total = len(active)
    ok_ars = 0
    ok_ccl = 0
    miss_ccl_rows: list[dict[str, str | int | None]] = []

    for r in active:
        usa = str(r.get("ticker_usa") or "")
        ars_map = (r.get("ticker_cedear_ars") or "") or ""
        ccl_map = (r.get("ticker_cedear_ccl") or "") or ""
        ars_skip = not str(ars_map).strip()
        ccl_skip = not str(ccl_map).strip()
        iol_ars = _normalize_iol_ticker(ars_map) if not ars_skip else ""
        iol_ccl = _normalize_iol_ticker(ccl_map) if not ccl_skip else ""

        q_ars = None
        q_ccl = None
        if token_ok and not ars_skip and iol_ars:
            q_ars = get_iol_quote(iol_ars)
        if token_ok and not ccl_skip and iol_ccl:
            q_ccl = get_iol_quote(iol_ccl)

        ars_ok = q_ars is not None
        ccl_ok = q_ccl is not None
        if ars_ok:
            ok_ars += 1
        if ccl_ok:
            ok_ccl += 1

        is_miss_ccl = (not ccl_skip) and bool(iol_ccl) and (not ccl_ok)
        if is_miss_ccl:
            http_ccl: int | None = None
            if token_ok and token is not None:
                http_ccl = _probe_ccl_http_status(iol_ccl, token)
            st = "MISS_CCL"
            if http_ccl == 404:
                st = "MISS_CCL|http_404"
            elif http_ccl is not None and http_ccl != 200:
                st = f"MISS_CCL|http_{http_ccl}"
            miss_ccl_rows.append(
                {
                    "ticker_usa": usa,
                    "ticker_cedear_ars": ars_map,
                    "ticker_cedear_ccl": ccl_map,
                    "iol_ars": iol_ars,
                    "iol_ccl": iol_ccl,
                    "ars_price": _price_cell(q_ars),
                    "http_ccl": http_ccl,
                    "status": st,
                }
            )

    print("=== CEDEAR IOL - resumen ===")
    print(f"total_activos: {total}")
    print(f"total_OK_ARS: {ok_ars}")
    print(f"total_OK_CCL: {ok_ccl}")
    print(f"total_MISS_CCL: {len(miss_ccl_rows)}")
    if not token_ok:
        print("(IOL deshabilitado o sin token: conteos pueden reflejar solo faltas de auth.)")
    print()
    print("=== MISS_CCL (detalle) ===")
    if not miss_ccl_rows:
        print("(ninguno)")
        return 0

    cols = [
        "ticker_usa",
        "ticker_cedear_ars",
        "ticker_cedear_ccl",
        "iol_ars",
        "iol_ccl",
        "ars_price",
        "http_ccl",
        "status",
    ]
    print("|".join(cols))
    for row in miss_ccl_rows:
        http = row["http_ccl"]
        http_s = "" if http is None else str(http)
        print(
            "|".join(
                [
                    str(row["ticker_usa"]),
                    str(row["ticker_cedear_ars"]),
                    str(row["ticker_cedear_ccl"]),
                    str(row["iol_ars"]),
                    str(row["iol_ccl"]),
                    str(row["ars_price"]),
                    http_s,
                    str(row["status"]),
                ]
            )
        )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnóstico IOL vs cedear_mappings.json")
    p.add_argument(
        "--pipe-csv-sample",
        action="store_true",
        help="Salida CSV con | (solo %d primeros activos)." % CEDEAR_SAMPLE,
    )
    args = p.parse_args()
    if args.pipe_csv_sample:
        return run_pipe_csv_sample()
    return run_report()


if __name__ == "__main__":
    raise SystemExit(main())
