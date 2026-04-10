from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

HISTORY_FILE = DATA_DIR / "alert_history.json"


def _ensure_storage():

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not HISTORY_FILE.exists():

        HISTORY_FILE.write_text("{}", encoding="utf-8")


def load_history():

    _ensure_storage()

    try:

        content = HISTORY_FILE.read_text(
            encoding="utf-8"
        ).strip()

        if not content:

            return {}

        data = json.loads(content)

        if isinstance(data, dict):

            return data

        return {}

    except Exception:

        return {}


def save_history(history):

    _ensure_storage()

    HISTORY_FILE.write_text(

        json.dumps(
            history,
            ensure_ascii=False,
            indent=2
        ),

        encoding="utf-8"
    )


def get_last_state(ticker):

    history = load_history()

    return history.get(
        ticker.upper()
    )


def save_state(ticker, state):

    history = load_history()

    state["ticker"] = ticker.upper()

    history[ticker.upper()] = state

    save_history(history)


def clear_history():

    save_history({})


# ===== helpers usados por main =====


def _ticker_column_for_merge(df) -> str | None:
    if "Ticker" in df.columns:
        return "Ticker"
    if "ticker" in df.columns:
        return "ticker"
    return None


def find_previous_export(folder, exclude_path=None):

    try:

        folder_path = Path(folder)

        if not folder_path.exists():

            return None

        exclude_resolved = (
            Path(exclude_path).resolve() if exclude_path is not None else None
        )

        candidates = []

        for p in folder_path.glob("radar_*.xlsx"):

            try:

                if exclude_resolved is not None and p.resolve() == exclude_resolved:

                    continue

                mtime = p.stat().st_mtime

            except OSError:

                continue

            candidates.append((mtime, p))

        if not candidates:

            return None

        return max(candidates, key=lambda x: x[0])[1]

    except Exception:

        return None


def merge_history(current_df, previous_file, previous_sheet_name=None):

    if previous_file is None:
        if "score_anterior" not in current_df.columns:
            current_df["score_anterior"] = 0

        if "Evolucion" not in current_df.columns:
            if "TotalScore" in current_df.columns:
                current_df["Evolucion"] = current_df["TotalScore"]
            elif "score" in current_df.columns:
                current_df["Evolucion"] = current_df["score"]
            else:
                current_df["Evolucion"] = 0

        return current_df

    try:
        import pandas as pd

        previous_df = pd.read_excel(previous_file, sheet_name=previous_sheet_name)

        ticker_col_actual = _ticker_column_for_merge(current_df)
        ticker_col_prev = _ticker_column_for_merge(previous_df)

        score_col_actual = None
        if "TotalScore" in current_df.columns:
            score_col_actual = "TotalScore"
        elif "score" in current_df.columns:
            score_col_actual = "score"

        score_col_prev = None
        if "TotalScore" in previous_df.columns:
            score_col_prev = "TotalScore"
        elif "score" in previous_df.columns:
            score_col_prev = "score"

        if not ticker_col_actual or not ticker_col_prev or not score_col_actual or not score_col_prev:
            if "score_anterior" not in current_df.columns:
                current_df["score_anterior"] = 0
            if "Evolucion" not in current_df.columns:
                current_df["Evolucion"] = 0
            return current_df

        prev_scores = previous_df.set_index(ticker_col_prev)[score_col_prev].to_dict()

        current_df["score_anterior"] = current_df[ticker_col_actual].map(prev_scores).fillna(0)
        current_df["Evolucion"] = current_df[score_col_actual] - current_df["score_anterior"]

        return current_df

    except Exception as e:
        print(f"No se pudo mergear history: {e}")

        if "score_anterior" not in current_df.columns:
            current_df["score_anterior"] = 0

        if "Evolucion" not in current_df.columns:
            if "TotalScore" in current_df.columns:
                current_df["Evolucion"] = current_df["TotalScore"]
            elif "score" in current_df.columns:
                current_df["Evolucion"] = current_df["score"]
            else:
                current_df["Evolucion"] = 0

        return current_df