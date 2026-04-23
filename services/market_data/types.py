from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class PriceQuote:
    value: float | None
    currency: Literal["ARS", "USD"]
    source: Literal["export", "yahoo", "snapshot", "unknown"]
    as_of: datetime | None
    symbol_used: str
    notes: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.value is not None
