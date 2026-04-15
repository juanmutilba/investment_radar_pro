from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config import FUNDAMENTALS_CACHE_TTL_HOURS


def _now_ts() -> float:
    return time.time()


def _cache_path() -> Path:
    # Guardar en data/ para convivir con otros archivos locales (alert_history.json, etc.).
    base = Path(__file__).resolve().parent.parent
    data_dir = base / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "fundamentals_cache.json"


def _atomic_write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


# Subconjunto de asset.info usado por engines USA/Argentina (radar/export). Mantener alineado con esos módulos.
_INFO_KEYS: tuple[str, ...] = (
    "longName",
    "shortName",
    "sector",
    "industry",
    "marketCap",
    "beta",
    "returnOnEquity",
    "trailingPE",
    "priceToBook",
    "ebitda",
    "netIncomeToCommon",
    "totalDebt",
    "debtToEquity",
    "targetMeanPrice",
    "exchange",
)


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    stores: int = 0
    errors: int = 0


class FundamentalsCache:
    """
    Cache simple en JSON por ticker con TTL.

    - Solo cachea subset de asset.info (lento y poco variable).
    - No cachea history/close/indicadores técnicos.
    """

    def __init__(self, ttl_hours: int | None = None) -> None:
        self.ttl_seconds = float((ttl_hours if ttl_hours is not None else FUNDAMENTALS_CACHE_TTL_HOURS) * 3600)
        self.path = _cache_path()
        self._data: dict[str, dict[str, Any]] = {}
        self.stats = CacheStats()
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if not self.path.exists():
                self._data = {}
                return
            raw = self.path.read_text(encoding="utf-8").strip()
            if not raw:
                self._data = {}
                return
            obj = json.loads(raw)
            self._data = obj if isinstance(obj, dict) else {}
        except Exception:
            # Cache corrupto no debe frenar el scan.
            self._data = {}
            self.stats.errors += 1

    def save(self) -> None:
        try:
            self.load()
            _atomic_write_json(self.path, self._data)
        except Exception:
            self.stats.errors += 1

    def get(self, ticker: str) -> dict[str, Any] | None:
        self.load()
        t = _normalize_ticker(ticker)
        entry = self._data.get(t)
        if not entry or not isinstance(entry, dict):
            self.stats.misses += 1
            return None
        fetched_at = entry.get("fetched_at")
        if not isinstance(fetched_at, (int, float)):
            self.stats.misses += 1
            return None
        if _now_ts() - float(fetched_at) > self.ttl_seconds:
            self.stats.misses += 1
            return None
        info = entry.get("info")
        if not isinstance(info, dict):
            self.stats.misses += 1
            return None
        self.stats.hits += 1
        return info

    def set(self, ticker: str, info: dict[str, Any]) -> None:
        self.load()
        t = _normalize_ticker(ticker)
        filtered = {k: info.get(k) for k in _INFO_KEYS}
        self._data[t] = {"fetched_at": _now_ts(), "info": filtered}
        self.stats.stores += 1

    def get_or_fetch_info(self, *, ticker: str, fetcher) -> dict[str, Any]:
        """Un hit o un miss+fetch por ticker; evita contar misses duplicados."""
        self.load()
        t = _normalize_ticker(ticker)
        entry = self._data.get(t)
        if isinstance(entry, dict):
            fetched_at = entry.get("fetched_at")
            info = entry.get("info")
            if isinstance(fetched_at, (int, float)) and isinstance(info, dict):
                if _now_ts() - float(fetched_at) <= self.ttl_seconds:
                    self.stats.hits += 1
                    return info
        self.stats.misses += 1
        info = fetcher()
        if isinstance(info, dict):
            self.set(ticker, info)
            return {k: info.get(k) for k in _INFO_KEYS}
        return {}

