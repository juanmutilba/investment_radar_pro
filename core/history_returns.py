from __future__ import annotations

from datetime import date

import pandas as pd


def _close_column_name(hist: pd.DataFrame) -> str | None:
    if hist is None or getattr(hist, "empty", True):
        return None
    if "Close" in hist.columns:
        return "Close"
    if "Adj Close" in hist.columns:
        return "Adj Close"
    return None


def _calc_return_pct_from_history(hist: pd.DataFrame, days_back: int) -> float | None:
    """Último cierre válido vs cierre `days_back` filas de negociación atrás. % redondeado a 2 decimales."""
    col = _close_column_name(hist)
    if col is None or days_back < 1:
        return None
    s = pd.to_numeric(hist[col], errors="coerce").dropna()
    if getattr(s.index, "is_monotonic_increasing", False) is False:
        try:
            s = s.sort_index()
        except Exception:
            return None
    if len(s) <= days_back:
        return None
    last = float(s.iloc[-1])
    prev = float(s.iloc[-1 - days_back])
    if last != last or prev != prev or prev <= 0:
        return None
    return round((last / prev - 1.0) * 100.0, 2)


def _calc_ytd_return_pct_from_history(hist: pd.DataFrame) -> float | None:
    """Primer cierre válido del año calendario actual vs último cierre válido en el historial."""
    col = _close_column_name(hist)
    if col is None:
        return None
    s = pd.to_numeric(hist[col], errors="coerce").dropna()
    if s.empty:
        return None
    if not isinstance(s.index, pd.DatetimeIndex):
        try:
            s = s.copy()
            s.index = pd.to_datetime(s.index, utc=False, errors="coerce")
            s = s[~s.index.isna()]
        except Exception:
            return None
    if s.empty:
        return None
    if not getattr(s.index, "is_monotonic_increasing", False):
        try:
            s = s.sort_index()
        except Exception:
            return None
    y0 = date.today().year
    try:
        s_y = s[s.index.year == y0]
    except Exception:
        return None
    if s_y.empty:
        return None
    first = float(s_y.iloc[0])
    last = float(s.iloc[-1])
    if first != first or last != last or first <= 0:
        return None
    return round((last / first - 1.0) * 100.0, 2)
