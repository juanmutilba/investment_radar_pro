from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from services.alert_event_log import read_alert_events


def _norm_ticker(t: Any) -> str:
    return str(t or "").strip().upper()


def _parse_date_only(s: Any) -> date | None:
    if s is None:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    # Acepta "YYYY-MM-DD" o ISO "YYYY-MM-DDTHH:MM:SS..."
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _parse_dt(s: Any) -> datetime | None:
    if s is None:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    # datetime.fromisoformat acepta offsets "+00:00" (como en alert_events.jsonl)
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None


def _event_label(ev: dict[str, Any]) -> str | None:
    lab = ev.get("tipo_alerta_label")
    if isinstance(lab, str) and lab.strip():
        return lab.strip()
    key = ev.get("tipo_alerta")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return None


def _event_key(ev: dict[str, Any]) -> str:
    v = ev.get("tipo_alerta")
    return str(v or "").strip().lower()


def _event_dt(ev: dict[str, Any]) -> datetime | None:
    return _parse_dt(ev.get("scan_at"))


@dataclass(frozen=True)
class MatchedAlert:
    label: str
    scan_at: str | None = None
    tipo: str | None = None


def _type_bonus(kind: str, ev: dict[str, Any]) -> int:
    """
    Bonus (más alto = mejor) para resolver empates.
    kind=buy: preferir compras; kind=sell: preferir ventas / stop / toma ganancia.
    """
    k = _event_key(ev)
    lab = str(ev.get("tipo_alerta_label") or "").lower()
    s = f"{k} {lab}"
    if kind == "buy":
        if "compra" in s or "buy" in s:
            return 5
        if "alerta" in s:
            return 1
        return 0
    # sell
    if "venta" in s or "sell" in s:
        return 5
    if "stop" in s or "stop_loss" in s:
        return 4
    if "toma" in s or "take_profit" in s or "ganancia" in s:
        return 3
    return 0


def match_alert_label_for_date(
    *,
    ticker: str,
    target_date: str | None,
    kind: str,
    window_days: int = 1,
    events_limit: int = 50_000,
) -> MatchedAlert | None:
    """
    Devuelve la alerta "más cercana" para ticker + fecha:
    - match ticker exacto
    - match fecha exacta; si no, ventana ±window_days
    - si hay varias: prioriza menor diferencia de días y luego bonus por tipo (buy/sell) y luego cercanía temporal.
    """
    t = _norm_ticker(ticker)
    td = _parse_date_only(target_date)
    if not t or td is None:
        return None

    events = read_alert_events(limit=events_limit)
    if not events:
        return None

    best: tuple[int, int, float, dict[str, Any]] | None = None
    # Orden: (abs_day_diff, -bonus, abs_seconds_diff)
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if _norm_ticker(ev.get("ticker")) != t:
            continue
        dt = _event_dt(ev)
        if dt is None:
            continue
        dd = dt.date()
        day_diff = (dd - td).days
        abs_day = abs(day_diff)
        if abs_day > window_days:
            continue
        bonus = _type_bonus(kind, ev)
        # Abs seconds to midday avoids penalizing timezone offsets too hard
        secs = abs((datetime.combine(dd, datetime.min.time()) - datetime.combine(td, datetime.min.time())).total_seconds())
        key = (abs_day, -bonus, secs, ev)
        if best is None or key[:3] < best[:3]:
            best = key

    if best is None:
        return None
    ev = best[3]
    label = _event_label(ev)
    if not label:
        return None
    return MatchedAlert(label=label, scan_at=str(ev.get("scan_at") or ""), tipo=str(ev.get("tipo_alerta") or "") or None)


def buy_alert_label_or_default(*, ticker: str, buy_date: str | None) -> str:
    m = match_alert_label_for_date(ticker=ticker, target_date=buy_date, kind="buy")
    return m.label if m else "sin alerta"


def sell_alert_label_or_default(*, ticker: str, sell_date: str | None) -> str:
    m = match_alert_label_for_date(ticker=ticker, target_date=sell_date, kind="sell")
    return m.label if m else "sin alerta"

