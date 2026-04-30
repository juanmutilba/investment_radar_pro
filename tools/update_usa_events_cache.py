from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from data.universe_usa import TICKERS_USA  # noqa: E402


OUT_PATH = ROOT / "data" / "events_cache_usa.json"
DEAD_TICKERS_PATH = ROOT / "data" / "dead_tickers_usa.json"

SKIP_EVENTS_TICKERS = {"SPY", "QQQ", "DIA", "IWM", "EEM", "XLF", "XLE", "XLK", "ARKK", "IVV"}


def _now_iso() -> str:
    # ISO UTC sin warning de utcnow() (y con sufijo Z).
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_dead_tickers(path: Path) -> dict[str, int]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in obj.items():
        if not isinstance(k, str):
            continue
        key = k.strip().upper()
        if not key:
            continue
        try:
            n = int(v)
        except Exception:
            continue
        out[key] = n
    return out


def _safe_float(x) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return None
    if v != v:
        return None
    return v


def _safe_int(x) -> int | None:
    if x is None:
        return None
    try:
        return int(float(x))
    except Exception:
        return None


def _get_price_estimate(asset: yf.Ticker, info: dict) -> float | None:
    # 1) fast_info (suele ser más liviano que info completo)
    try:
        fi = getattr(asset, "fast_info", None)
        if isinstance(fi, dict):
            for k in ("last_price", "lastPrice", "regularMarketPrice"):
                v = _safe_float(fi.get(k))
                if v and v > 0:
                    return v
    except Exception:
        pass

    # 2) info (ya disponible en algunos entornos)
    if isinstance(info, dict):
        for k in ("currentPrice", "regularMarketPrice", "previousClose"):
            v = _safe_float(info.get(k))
            if v and v > 0:
                return v

    # 3) fallback: último close de un history corto (1 llamada extra)
    try:
        h = asset.history(period="5d", auto_adjust=False, actions=False, repair=False)
        if h is not None and not getattr(h, "empty", True):
            col = "Close" if "Close" in h.columns else None
            if col:
                s = pd.to_numeric(h[col], errors="coerce").dropna()
                if not s.empty:
                    v = float(s.iloc[-1])
                    if v > 0:
                        return v
    except Exception:
        pass
    return None


def _extract_calendar_earnings_date(asset: yf.Ticker) -> date | None:
    try:
        cal = getattr(asset, "calendar", None)
        if cal is None:
            return None
        raw = None
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date")
        elif hasattr(cal, "loc"):
            try:
                raw = cal.loc["Earnings Date"][0]  # type: ignore[index]
            except Exception:
                raw = None
        today = date.today()
        candidates = list(raw) if isinstance(raw, (list, tuple)) else [raw]
        parsed: list[date] = []
        for v in candidates:
            ts = pd.to_datetime(v, errors="coerce")
            if ts is pd.NaT or ts is None:
                continue
            try:
                d = ts.date()
            except Exception:
                continue
            if d >= today:
                parsed.append(d)
        return min(parsed) if parsed else None
    except Exception:
        return None


def _infer_dividend_frequency(avg_days: int | None) -> tuple[str | None, int | None]:
    if avg_days is None or avg_days <= 0:
        return None, None
    # buckets amplios para tolerar variación
    if avg_days <= 45:
        return "monthly", 12
    if avg_days <= 120:
        return "quarterly", 4
    if avg_days <= 250:
        return "semiannual", 2
    if avg_days <= 420:
        return "annual", 1
    return "irregular", None


def _compute_dividend_stats(asset: yf.Ticker, info: dict) -> dict:
    out: dict = {
        "fecha_ultimo_dividendo": None,
        "ultimo_dividendo": None,
        "dividend_yield_pago_pct": None,
        "dividend_yield_anual_estimado_pct": None,
        "frecuencia_dividendos": None,
        "dias_promedio_entre_dividendos": None,
        "fecha_proximo_dividendo_estimado": None,
        "dias_hasta_proximo_dividendo": None,
        "dividendos_estimados_12m": None,
        "flujo_dividendos_12m_por_accion": None,
    }

    div = None
    try:
        div = getattr(asset, "dividends", None)
    except Exception:
        div = None
    if div is None:
        return out
    try:
        if len(div) <= 0:
            return out
    except Exception:
        return out

    try:
        s = div.dropna()
        if s.empty:
            return out
        # asegurar orden por fecha
        try:
            s = s.sort_index()
        except Exception:
            pass

        last = s.tail(1)
        last_dt = pd.to_datetime(last.index[0], errors="coerce")
        if last_dt is not pd.NaT and last_dt is not None:
            out["fecha_ultimo_dividendo"] = last_dt.date().isoformat()
        out["ultimo_dividendo"] = _safe_float(last.iloc[0])
    except Exception:
        return out

    price = _get_price_estimate(asset, info if isinstance(info, dict) else {})
    ultimo = _safe_float(out.get("ultimo_dividendo"))
    if price and ultimo and price > 0:
        out["dividend_yield_pago_pct"] = round((ultimo / price) * 100.0, 4)

    # estimar frecuencia y próximos pagos desde intervalos históricos recientes
    avg_days: int | None = None
    try:
        # usar hasta 12 pagos recientes para suavizar
        recent = s.tail(12)
        idx = pd.to_datetime(recent.index, errors="coerce")
        idx = idx[~idx.isna()]
        if len(idx) >= 4:
            diffs = idx.to_series().diff().dropna().dt.days
            diffs = diffs[(diffs > 0) & (diffs < 600)]
            if not diffs.empty:
                avg_days = int(round(float(diffs.mean())))
                if avg_days > 0:
                    out["dias_promedio_entre_dividendos"] = avg_days
    except Exception:
        avg_days = None

    freq_label, freq_n = _infer_dividend_frequency(avg_days)
    out["frecuencia_dividendos"] = freq_label
    out["dividendos_estimados_12m"] = freq_n

    flujo_12m = None
    if ultimo is not None and freq_n is not None:
        flujo_12m = ultimo * float(freq_n)
        out["flujo_dividendos_12m_por_accion"] = round(flujo_12m, 6)
        if price and price > 0:
            out["dividend_yield_anual_estimado_pct"] = round((flujo_12m / price) * 100.0, 4)

    # fecha próximo dividendo estimada: última fecha + avg_days, ajustando a futuro
    try:
        if out.get("fecha_ultimo_dividendo") and avg_days and avg_days > 0:
            last_d = date.fromisoformat(str(out["fecha_ultimo_dividendo"]))
            next_d = last_d + timedelta(days=int(avg_days))
            today = date.today()
            while next_d < today and avg_days > 0:
                next_d = next_d + timedelta(days=int(avg_days))
            out["fecha_proximo_dividendo_estimado"] = next_d.isoformat()
            out["dias_hasta_proximo_dividendo"] = int((next_d - today).days)
    except Exception:
        pass

    return out


def _compute_earnings_stats(asset: yf.Ticker) -> dict:
    out: dict = {
        "fecha_proximo_earnings": None,
        "dias_hasta_earnings": None,
        "earnings_en_7d": None,
        "earnings_en_30d": None,
    }
    d = _extract_calendar_earnings_date(asset)
    if d is None:
        return out
    out["fecha_proximo_earnings"] = d.isoformat()
    try:
        dias = int((d - date.today()).days)
        out["dias_hasta_earnings"] = dias
        out["earnings_en_7d"] = bool(0 <= dias <= 7)
        out["earnings_en_30d"] = bool(0 <= dias <= 30)
    except Exception:
        out["dias_hasta_earnings"] = None
        out["earnings_en_7d"] = None
        out["earnings_en_30d"] = None
    return out


def main() -> int:
    t0 = time.perf_counter()
    out: dict[str, dict] = {}
    skipped = 0
    errors = 0

    dead = _load_dead_tickers(DEAD_TICKERS_PATH)

    items = list(TICKERS_USA)
    print(f"[USA_EVENTS_CACHE] tickers={len(items)} out={OUT_PATH}")

    for i, ticker in enumerate(items):
        t = (ticker or "").strip().upper()
        if not t:
            continue
        if t in SKIP_EVENTS_TICKERS or int(dead.get(t, 0)) >= 3:
            skipped += 1
            out[t] = {"skipped": True, "reason": "dead_or_etf", "updated_at": _now_iso()}
            if (i + 1) % 25 == 0:
                time.sleep(1)
            continue
        try:
            asset = yf.Ticker(t)
            info = {}
            try:
                # info puede ser caro pero en script de mantenimiento es aceptable
                info = asset.info if isinstance(asset.info, dict) else {}
            except Exception:
                info = {}

            div_stats = _compute_dividend_stats(asset, info)
            earn_stats = _compute_earnings_stats(asset)

            row = {}
            row.update(div_stats)
            row.update(earn_stats)
            row["updated_at"] = _now_iso()
            out[t] = row
        except Exception as e:
            errors += 1
            out[t] = {
                "error": {"type": type(e).__name__, "msg": str(e)},
                "updated_at": _now_iso(),
            }
        if (i + 1) % 50 == 0:
            print(f"[USA_EVENTS_CACHE] progress {i+1}/{len(items)}")
        if (i + 1) % 25 == 0:
            time.sleep(1)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elapsed = time.perf_counter() - t0
    print(f"[USA_EVENTS_CACHE] done tickers={len(out)} skipped={skipped} errors={errors} elapsed_s={elapsed:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

