"""Mapeo explícito: subyacente en espacio opciones / alias → ticker BYMA y Yahoo (.BA)."""

from __future__ import annotations

# Prefijos de opción (Rava/BYMA), alias cortos o tickers ya BYMA → ticker acción BYMA para spot.
_OPTION_OR_ALIAS_TO_BYMA_SPOT: dict[str, str] = {
    # GGAL
    "GFG": "GGAL",
    "GGAL": "GGAL",
    # YPF / YPFD
    "YPF": "YPFD",
    "YPFD": "YPFD",
    # ALUA
    "ALU": "ALUA",
    "ALUA": "ALUA",
    # Otros pedidos / habituales
    "BMA": "BMA",
    "PAMP": "PAMP",
    "PAM": "PAMP",  # prefijo opciones Rava (PAMP)
    "TXA": "TXAR",
    "TXAR": "TXAR",
    "TRA": "TRAN",
    "TRAN": "TRAN",
    "COM": "COME",
    "COME": "COME",
    "BYM": "BYMA",
    "BYMA": "BYMA",
}


def option_underlying_to_spot_symbol(underlying: str | None) -> str:
    """
    Ticker de la acción en BYMA (sin sufijo Yahoo) para el subyacente de opciones.
    No usa strike ni contratos; solo normaliza el nombre recibido (p. ej. GFG → GGAL).
    """
    if underlying is None:
        return ""
    s = str(underlying).strip().upper()
    if not s:
        return ""
    return _OPTION_OR_ALIAS_TO_BYMA_SPOT.get(s, s)


def option_underlying_to_yahoo_symbol(underlying: str | None) -> str:
    """
    Símbolo Yahoo Finance para cotización local BYMA: siempre sufijo .BA sobre el spot BYMA.
    """
    spot = option_underlying_to_spot_symbol(underlying)
    if not spot:
        return ""
    if spot.endswith(".BA"):
        return spot
    return f"{spot}.BA"
