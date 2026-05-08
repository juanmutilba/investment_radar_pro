"""Utilidades de opciones (cadena, fuentes externas)."""

from services.options.chain_builder import build_master_chain, deduplicate_contracts, summarize_chain
from services.options.market_merge import build_merged_market_chain, merge_option_market_data
from services.options.models import OptionChain, OptionContract
from services.options.options_service import get_options_chain
from services.options.normalizer import (
    make_contract_key,
    normalize_option_type,
    normalize_strike,
    normalize_symbol,
    normalize_underlying,
)

__all__ = [
    "OptionContract",
    "OptionChain",
    "normalize_underlying",
    "normalize_option_type",
    "normalize_strike",
    "normalize_symbol",
    "make_contract_key",
    "get_options_chain",
    "build_master_chain",
    "build_merged_market_chain",
    "deduplicate_contracts",
    "merge_option_market_data",
    "summarize_chain",
]
