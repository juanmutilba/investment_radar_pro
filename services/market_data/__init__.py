from __future__ import annotations

from services.market_data.facade import get_argentina_price, get_usa_price
from services.market_data.types import PriceQuote

__all__ = [
    "PriceQuote",
    "get_argentina_price",
    "get_usa_price",
]
