import sys
import os

from engines.usa_engine import _get_earnings_date


sys.path.append(os.path.dirname(os.path.dirname(__file__)))
print("DEBUG EARNINGS TEST")

test_tickers = ["AAPL", "MSFT", "NVDA", "KO", "PFE"]

earnings_cache = {}
earnings_stats = {}

for t in test_tickers:
    d = _get_earnings_date(
        ticker=t,
        cache=earnings_cache,
        stats=earnings_stats,
        max_calendar_calls=20,
    )
    print(f"{t} -> {d}")

print("stats:", earnings_stats)