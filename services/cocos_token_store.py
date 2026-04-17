"""Token JWT de Cocos (Apikey / Bearer) solo en memoria del proceso API."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_token: str | None = None


def get_cocos_api_token() -> str | None:
    with _lock:
        if not _token or not str(_token).strip():
            return None
        return str(_token).strip()


def set_cocos_api_token(token: str) -> None:
    t = (token or "").strip()
    with _lock:
        global _token
        _token = t or None


def clear_cocos_api_token() -> None:
    with _lock:
        global _token
        _token = None
