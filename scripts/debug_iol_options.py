from __future__ import annotations

"""
Diagnóstico: ¿IOL puede ser fuente principal de opciones argentinas?

Estrategia:
- Verificar que el token funciona para cotización (ya probado en debug_iol_options_raw.py).
- Probar el recurso "Opciones" de IOL para varios subyacentes.
- Reportar:
  - status HTTP
  - si devuelve lista
  - keys disponibles
  - conteos (si hay datos)

Nota:
En esta base de código ya existe `services.market_data.providers.iol.get_iol_options_raw()`
que llama a: /api/v2/bCBA/Titulos/{ticker}/Opciones.
En entornos reales suele responder 401 aunque cotización responda 200 (restricción de recurso/plan).
"""

import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from services.market_data.providers.iol import IolOptionsRawError, configure_iol_credentials, get_iol_options_raw  # noqa: E402


SYMBOLS = ["GGAL", "ALUA", "TXAR", "TRAN", "PAMP", "YPFD"]


def _safe_keys(x: Any) -> list[str]:
    if isinstance(x, dict):
        return list(x.keys())
    return []


def main() -> int:
    u = (os.environ.get("IOL_USERNAME") or "").strip()
    pw = (os.environ.get("IOL_PASSWORD") or "").strip()
    creds_present = bool(u and pw)
    print(f"[IOL_OPTIONS_DIAG] creds_present={creds_present}")
    configure_iol_credentials(u, pw)

    for sym in SYMBOLS:
        print()
        print(f"{sym}:")
        try:
            data = get_iol_options_raw(sym)
            if isinstance(data, list):
                print(f"  status=ok items={len(data)}")
                if data and isinstance(data[0], dict):
                    print(f"  first_keys={list(data[0].keys())}")
            else:
                print(f"  status=ok type={type(data).__name__}")
                if isinstance(data, dict):
                    print(f"  keys={list(data.keys())[:40]}")
        except IolOptionsRawError as e:
            print(f"  status=error http_status={e.status_code} iol_resource_401={getattr(e, 'iol_resource_401', False)}")
            if e.detail:
                print(f"  detail={e.detail[:300]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

