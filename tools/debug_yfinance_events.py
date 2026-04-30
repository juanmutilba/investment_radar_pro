from __future__ import annotations

import sys
import traceback
from pathlib import Path

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TICKERS = ["AAPL", "KO", "PFE", "MSFT", "NVDA"]


def _safe_print(label: str, fn) -> None:
    print(f"\n--- {label} ---")
    try:
        out = fn()
        if isinstance(out, pd.DataFrame):
            print(out)
        elif isinstance(out, pd.Series):
            print(out)
        else:
            print(repr(out))
    except Exception as e:
        print(f"ERROR {type(e).__name__}: {e}")
        tb = traceback.format_exc()
        print(tb)


def _tail_repr(obj, n: int):
    try:
        if obj is None:
            return None
        # pandas Series/DataFrame
        if hasattr(obj, "tail"):
            return obj.tail(n)
        return obj
    except Exception as e:
        return f"ERROR {type(e).__name__}: {e}"


def main() -> int:
    print("yfinance events diagnostic")
    print(f"python={sys.version.split()[0]}")
    try:
        import yfinance as _yf

        print(f"yfinance_version={getattr(_yf, '__version__', 'unknown')}")
    except Exception:
        print("yfinance_version=unknown")

    for sym in TICKERS:
        print("\n" + "=" * 80)
        print(f"TICKER: {sym}")
        print("=" * 80)

        t = None
        try:
            t = yf.Ticker(sym)
        except Exception as e:
            print(f"ERROR creating Ticker({sym}): {type(e).__name__}: {e}")
            continue

        _safe_print('1) ticker.info.get("earningsDate")', lambda: (t.info or {}).get("earningsDate"))
        _safe_print("2) ticker.calendar", lambda: getattr(t, "calendar", None))

        def _earnings_dates():
            if hasattr(t, "get_earnings_dates"):
                return t.get_earnings_dates(limit=8)
            return "MISSING_METHOD get_earnings_dates"

        _safe_print("3) ticker.get_earnings_dates(limit=8)", _earnings_dates)
        _safe_print("4) ticker.dividends.tail(8)", lambda: _tail_repr(getattr(t, "dividends", None), 8))
        _safe_print("5) ticker.actions.tail(12)", lambda: _tail_repr(getattr(t, "actions", None), 12))

        _safe_print('6) ticker.info.get("dividendYield")', lambda: (t.info or {}).get("dividendYield"))
        _safe_print('7) ticker.info.get("exDividendDate")', lambda: (t.info or {}).get("exDividendDate"))
        _safe_print('8) ticker.info.get("lastDividendValue")', lambda: (t.info or {}).get("lastDividendValue"))
        _safe_print('9) ticker.info.get("lastDividendDate")', lambda: (t.info or {}).get("lastDividendDate"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

