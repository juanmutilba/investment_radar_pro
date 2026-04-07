from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
HISTORY_FILE = DATA_DIR / "alert_history.json"


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not HISTORY_FILE.exists():
        HISTORY_FILE.write_text("{}", encoding="utf-8")


def load_history() -> dict[str, dict[str, Any]]:
    _ensure_storage()

    try:
        content = HISTORY_FILE.read_text(encoding="utf-8").strip()
        if not content:
            return {}

        data = json.loads(content)
        if isinstance(data, dict):
            return data

        return {}
    except Exception:
        return {}


def save_history(history: dict[str, dict[str, Any]]) -> None:
    _ensure_storage()
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_last_state(ticker: str) -> dict[str, Any] | None:
    history = load_history()
    return history.get(ticker.upper())


def save_state(ticker: str, state: dict[str, Any]) -> None:
    history = load_history()
    history[ticker.upper()] = state
    save_history(history)


def clear_history() -> None:
    save_history({})