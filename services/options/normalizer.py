from __future__ import annotations

import re
from typing import Any

from services.options.models import OptionContract

# Subyacente acción BYMA → prefijo habitual en símbolos de opción (cadena maestra en espacio de opciones).
_UNDERLYING_TO_OPTION_PREFIX: dict[str, str] = {
    "GGAL": "GFG",
}


def normalize_underlying(value: str | None) -> str | None:
    """
    Normaliza subyacente para la cadena maestra de opciones (uppercase).
    GGAL → GFG (prefijo de opciones GGAL en BYMA).
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    return _UNDERLYING_TO_OPTION_PREFIX.get(s, s)


def normalize_option_type(value: str | None) -> str | None:
    """CALL / PUT o None si no se puede clasificar sin inventar."""
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if s in ("C", "CALL", "COMPRA"):
        return "CALL"
    if s in ("V", "P", "PUT", "VENTA"):
        return "PUT"
    return None


def normalize_strike(value: object) -> float | None:
    """Acepta int/float/str con coma o punto; no inventa."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        x = float(value)
        return x if x == x else None
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s or s in ("-", ".", ","):
        return None
    # Formato AR: miles con punto y decimal con coma
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return None
    if x != x:
        return None
    return x


def normalize_symbol(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper().replace(" ", "")
    return s or None


def make_contract_key(contract: OptionContract) -> tuple[Any, ...]:
    """Clave estable para deduplicar: (underlying, expiry, strike, option_type)."""
    u = normalize_underlying(contract.underlying) or ""
    exp = contract.expiry
    if exp is not None:
        exp = str(exp).strip() or None
    strike = contract.strike
    ot = normalize_option_type(contract.option_type)
    return (u, exp, strike, ot)
