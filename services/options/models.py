from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OptionContract:
    underlying: str
    expiry: str | None
    strike: float | None
    option_type: str | None  # "CALL" / "PUT"
    symbol: str
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    source: str = ""
    raw: dict | None = None


@dataclass
class OptionChain:
    underlying: str
    contracts: list[OptionContract] = field(default_factory=list)
