"""
Segunda generación de auditoría de trades del bot (paper + testnet).
Sólo análisis y exportación; no modifica ejecución ni bot_runner.
"""
from __future__ import annotations

import csv
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable

from services.crypto.bot_trade_audit import (
    _load_testnet_closed_trades,
    _parse_iso_dt,
    _safe_float,
)
from services.crypto.btc_trend_backtest import (
    _build_indicator_matrix,
    timeframe_to_ms,
)

_LOG_PREFIX = "[BOT_TRADE_ANALYZER_V2]"

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_OUTPUT_DIR = _DATA_DIR / "trade_analysis"
_PAPER_JSON = _DATA_DIR / "crypto_paper_portfolio.json"


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", flush=True)


def _ccxt_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper().replace(" ", "")
    if "/" in s:
        return s
    if s.endswith("USDT") and len(s) > 4:
        return f"{s[:-4]}/USDT"
    return s


_DAY_MS = 86_400_000


def _ohlcv_cache_key(
    symbol: str,
    timeframe: str,
    pad_days: int,
    start_ms: int,
    end_ms: int,
) -> tuple[str, str, int, int, int]:
    """Clave estable por símbolo + TF + pad + rango [día UTC inicio, día UTC fin]."""
    d0 = int(start_ms // _DAY_MS)
    d1 = int(end_ms // _DAY_MS)
    return (symbol, timeframe, pad_days, d0, d1)


def _short_exc_message(exc: BaseException, *, max_len: int = 96) -> str:
    msg = str(exc).replace("\n", " ").replace("\r", " ").strip()
    if len(msg) > max_len:
        msg = msg[: max_len - 3] + "..."
    return msg


def _format_fetch_failed_error(exc: BaseException) -> str:
    name = type(exc).__name__
    tail = _short_exc_message(exc)
    if tail:
        return f"fetch_failed:{name}:{tail}"
    return f"fetch_failed:{name}"


def _fetch_ohlcv_page_with_retry(
    exchange: Any,
    sym: str,
    tf: str,
    since: int,
    limit: int,
    *,
    timeout_ms: int,
    max_retries: int,
) -> list[list[float]]:
    last: BaseException | None = None
    for attempt in range(max(1, max_retries)):
        try:
            exchange.timeout = int(timeout_ms)
            return exchange.fetch_ohlcv(sym, timeframe=tf, since=int(since), limit=int(limit))
        except Exception as e:
            last = e
            if attempt + 1 >= max(1, max_retries):
                raise
            time.sleep(min(2.0, 0.35 * (2**attempt)))
    assert last is not None
    raise last


def fetch_ohlcv_for_analysis_window(
    *,
    symbol: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
    limit_per_request: int = 1000,
    max_pages: int = 400,
    timeout_ms: int = 30_000,
    max_retries: int = 3,
) -> list[list[float]]:
    """
    Igual que fetch_ohlcv_for_window pero con más páginas por defecto.
    El límite de 80 páginas en btc_trend_backtest truncaba series 1m/5m largas
    y dejaba velas incompletas → indicadores vacíos y CSV sin filas.
    Usa timeout y reintentos por página en ccxt.
    """
    try:
        import ccxt  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError("ccxt no instalado") from e

    sym = _ccxt_symbol(symbol)
    tf = (timeframe or "30m").strip() or "30m"
    lim = max(1, min(int(limit_per_request), 1000))
    pad = timeframe_to_ms(tf) * 3
    since = max(0, int(start_ms) - pad)
    until = int(end_ms) + pad

    ex = ccxt.binance(
        {
            "enableRateLimit": True,
            "timeout": int(timeout_ms),
            "options": {"defaultType": "spot"},
        }
    )
    all_rows: list[list[float]] = []
    cursor = since
    pages = 0
    while cursor < until:
        pages += 1
        batch = _fetch_ohlcv_page_with_retry(
            ex, sym, tf, cursor, lim, timeout_ms=timeout_ms, max_retries=max_retries
        )
        if not batch:
            break
        if all_rows and batch[0][0] <= all_rows[-1][0]:
            batch = [r for r in batch if r[0] > all_rows[-1][0]]
            if not batch:
                break
        all_rows.extend(batch)
        cursor = int(batch[-1][0]) + 1
        if len(batch) < lim:
            break
        if pages >= max_pages:
            break
    out = [r for r in all_rows if since <= int(r[0]) <= until]
    out.sort(key=lambda r: r[0])
    return out


def _iso_to_ms(value: str | None) -> int | None:
    dt = _parse_iso_dt(value)
    if dt is None:
        return None
    return int(dt.timestamp() * 1000)


def _load_paper_closed_trades_v2() -> list[dict[str, Any]]:
    if not _PAPER_JSON.is_file():
        return []
    try:
        raw = json.loads(_PAPER_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    out: list[dict[str, Any]] = []
    for t in raw.get("trades") or []:
        if not isinstance(t, dict):
            continue
        pnl = _safe_float(t.get("pnl_usdt"))
        if pnl is None:
            continue
        out.append(
            {
                "source_kind": "paper",
                "symbol": str(t.get("symbol") or "").strip(),
                "entry_time": t.get("entry_time"),
                "exit_time": t.get("exit_time"),
                "entry_price": _safe_float(t.get("entry_price")),
                "exit_price": _safe_float(t.get("exit_price")),
                "exit_reason": str(t.get("exit_reason") or "unknown").strip() or "unknown",
                "pnl_usdt": pnl,
                "pnl_pct": _safe_float(t.get("pnl_pct")),
                "order_source_entry": "paper",
                "order_source_exit": "paper",
                "strategy_mode": str(t.get("strategy_mode") or "").strip() or None,
                "setup_type": str(t.get("setup_type") or "").strip() or None,
                "entry_score": _safe_float(t.get("entry_score")),
                "timeframe": str(t.get("timeframe") or "").strip() or None,
            }
        )
    return out


def load_merged_trades(*, sources: Iterable[str] | None = None) -> list[dict[str, Any]]:
    want = {s.strip().lower() for s in (sources or ["testnet", "paper"])}
    trades: list[dict[str, Any]] = []
    if "testnet" in want:
        trades.extend(_load_testnet_closed_trades())
    if "paper" in want:
        trades.extend(_load_paper_closed_trades_v2())
    trades.sort(
        key=lambda r: (_parse_iso_dt(str(r.get("exit_time") or "")) or datetime.min.replace(tzinfo=timezone.utc),)
    )
    return trades


def _pnl_usdt(t: dict[str, Any]) -> float:
    v = _safe_float(t.get("pnl_usdt"))
    return float(v) if v is not None else 0.0


def _pnl_pct(t: dict[str, Any]) -> float | None:
    return _safe_float(t.get("pnl_pct"))


def _is_win(t: dict[str, Any]) -> bool:
    return _pnl_usdt(t) > 1e-9


def _is_loss(t: dict[str, Any]) -> bool:
    return _pnl_usdt(t) < -1e-9


def part1_general_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    wins = [t for t in trades if _is_win(t)]
    losses = [t for t in trades if _is_loss(t)]
    breakeven = n - len(wins) - len(losses)
    win_n, loss_n = len(wins), len(losses)
    wr = (win_n / n * 100.0) if n else None
    gp = sum(_pnl_usdt(t) for t in wins)
    gl = sum(_pnl_usdt(t) for t in losses)
    pf = (gp / abs(gl)) if gl < -1e-9 else None
    exp = (sum(_pnl_usdt(t) for t in trades) / n) if n else None
    avg_w = mean([_pnl_usdt(t) for t in wins]) if wins else None
    avg_l = mean([_pnl_usdt(t) for t in losses]) if losses else None
    return {
        "total_trades": n,
        "wins": win_n,
        "losses": loss_n,
        "breakeven": breakeven,
        "win_rate_pct": round(wr, 4) if wr is not None else None,
        "profit_factor": round(pf, 4) if pf is not None else None,
        "expectancy_usdt": round(exp, 6) if exp is not None else None,
        "avg_winner_usdt": round(avg_w, 6) if avg_w is not None else None,
        "avg_loser_usdt": round(avg_l, 6) if avg_l is not None else None,
        "gross_profit_usdt": round(gp, 6),
        "gross_loss_usdt": round(gl, 6),
    }


def part2_daily_stats(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        ex = str(t.get("exit_time") or "").strip()
        day = ex[:10] if len(ex) >= 10 else "unknown"
        by_day[day].append(t)
    rows: list[dict[str, Any]] = []
    for day in sorted(by_day.keys()):
        day_tr = by_day[day]
        w = sum(1 for x in day_tr if _is_win(x))
        l = sum(1 for x in day_tr if _is_loss(x))
        net = sum(_pnl_usdt(x) for x in day_tr)
        tot = len(day_tr)
        rows.append(
            {
                "date": day,
                "trades": tot,
                "wins": w,
                "losses": l,
                "net_pnl_usdt": round(net, 8),
                "win_rate_pct": round(w / tot * 100.0, 4) if tot else None,
            }
        )
    return rows


def _detect_streaks(daily: list[dict[str, Any]]) -> dict[str, Any]:
    """Días con racha negativa (net_pnl < 0 consecutivos)."""
    best = max(daily, key=lambda r: r["net_pnl_usdt"]) if daily else None
    worst = min(daily, key=lambda r: r["net_pnl_usdt"]) if daily else None
    streaks: list[dict[str, Any]] = []
    cur_start = None
    cur_len = 0
    for r in daily:
        if r["net_pnl_usdt"] < 0:
            if cur_start is None:
                cur_start = r["date"]
                cur_len = 1
            else:
                cur_len += 1
        else:
            if cur_len >= 2:
                streaks.append({"start": cur_start, "length": cur_len})
            cur_start = None
            cur_len = 0
    if cur_len >= 2 and cur_start:
        streaks.append({"start": cur_start, "length": cur_len})
    streaks.sort(key=lambda s: -s["length"])
    return {"best_day": best, "worst_day": worst, "negative_streaks": streaks[:15]}


def part3_equity_curve(trades: list[dict[str, Any]], *, initial: float = 10_000.0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sorted_tr = sorted(
        trades,
        key=lambda r: (_parse_iso_dt(str(r.get("exit_time") or "")) or datetime.min.replace(tzinfo=timezone.utc),),
    )
    cap = float(initial)
    peak = cap
    max_dd = 0.0
    rows: list[dict[str, Any]] = []
    for t in sorted_tr:
        pnl = _pnl_usdt(t)
        cap += pnl
        peak = max(peak, cap)
        dd = peak - cap
        max_dd = max(max_dd, dd)
        rows.append(
            {
                "exit_time": str(t.get("exit_time") or ""),
                "symbol": str(t.get("symbol") or ""),
                "source_kind": str(t.get("source_kind") or ""),
                "pnl_usdt": round(pnl, 8),
                "pnl_pct": t.get("pnl_pct"),
                "capital_after": round(cap, 6),
                "drawdown_from_peak": round(dd, 6),
                "exit_reason": str(t.get("exit_reason") or ""),
            }
        )
    total_pnl = cap - float(initial)
    recovery = (total_pnl / max_dd) if max_dd > 1e-9 else None
    meta = {
        "initial_usdt": initial,
        "final_capital": round(cap, 6),
        "total_pnl_usdt": round(total_pnl, 6),
        "max_drawdown_usdt": round(max_dd, 6),
        "recovery_factor": round(recovery, 4) if recovery is not None else None,
    }
    return rows, meta


def part4_score_buckets(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def score_of(t: dict[str, Any]) -> float | None:
        return _safe_float(t.get("entry_score"))

    buckets: list[tuple[str, Callable[[float | None], bool]]] = [
        ("60-64", lambda s: s is not None and 60 <= s < 65),
        ("65-69", lambda s: s is not None and 65 <= s < 70),
        ("70-74", lambda s: s is not None and 70 <= s < 75),
        ("75-79", lambda s: s is not None and 75 <= s < 80),
        ("80+", lambda s: s is not None and s >= 80),
        ("sin_score", lambda s: s is None),
    ]

    out: list[dict[str, Any]] = []
    for name, pred in buckets:
        subset = [tr for tr in trades if pred(score_of(tr))]
        if not subset:
            continue
        w = sum(1 for x in subset if _is_win(x))
        tot = len(subset)
        wr = (w / tot * 100.0) if tot else None
        ap = mean([_pnl_usdt(x) for x in subset]) if subset else None
        out.append(
            {
                "bucket": name,
                "count": tot,
                "wins": w,
                "losses": sum(1 for x in subset if _is_loss(x)),
                "win_rate_pct": round(wr, 4) if wr is not None else None,
                "avg_pnl_usdt": round(ap, 6) if ap is not None else None,
            }
        )
    return out


def _entry_bar_index(candles: list[list[float]], entry_ms: int) -> int | None:
    if not candles:
        return None
    best = None
    for i, c in enumerate(candles):
        t = int(c[0])
        if t <= entry_ms:
            best = i
    return best


def _btc_bull_at_ms(btc_candles: list[list[float]], entry_ms: int) -> bool | None:
    if len(btc_candles) < 60:
        return None
    regimes, _inds = _build_indicator_matrix(btc_candles)
    idx = _entry_bar_index(btc_candles, entry_ms)
    if idx is None or idx < 0 or idx >= len(regimes):
        return None
    return regimes[idx] == "bull"


def _first_idx_with_core_indicators(indicators: list[Any]) -> int:
    """Primer índice con RSI+ADX+MACD hist calculables (warmup de _build_indicator_matrix)."""
    for i, bi in enumerate(indicators):
        if bi.rsi14 is not None and bi.adx14 is not None and bi.macd_hist is not None:
            return i
    return 55


def enrich_trade_with_entry_indicators(
    trade: dict[str, Any],
    *,
    default_timeframe: str = "30m",
    candle_cache: dict[tuple[str, str, int, int, int], list[list[float]]],
    btc_cache: dict[tuple[str, str, int, int, int], list[list[float]]],
    ohlcv_timeout_ms: int = 30_000,
    ohlcv_max_retries: int = 3,
) -> dict[str, Any]:
    """Añade indicadores en la vela de entrada (reconstrucción OHLCV)."""
    out = dict(trade)
    sym = str(trade.get("symbol") or "").strip()
    entry_ms = _iso_to_ms(str(trade.get("entry_time") or ""))
    tf = str(trade.get("timeframe") or default_timeframe).strip() or default_timeframe
    tf_ms = timeframe_to_ms(tf)
    if not sym or entry_ms is None:
        out["indicators_error"] = "missing_symbol_or_entry_time"
        return out

    last_err = "unknown"
    candles: list[list[float]] | None = None
    regimes = None
    indicators = None
    idx: int | None = None
    used_pad_days = 120
    used_start_ms = 0

    for pad_days in (120, 200):
        used_pad_days = pad_days
        pad_ms = pad_days * 24 * 60 * 60 * 1000
        start_ms = entry_ms - pad_ms
        end_ms = entry_ms + tf_ms * 6
        used_start_ms = start_ms
        ck = _ohlcv_cache_key(sym, tf, pad_days, start_ms, end_ms)
        try:
            if ck not in candle_cache:
                candle_cache[ck] = fetch_ohlcv_for_analysis_window(
                    symbol=sym,
                    timeframe=tf,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    max_pages=400,
                    timeout_ms=ohlcv_timeout_ms,
                    max_retries=ohlcv_max_retries,
                )
            cand = candle_cache[ck]
        except Exception as e:
            last_err = _format_fetch_failed_error(e)
            candles = None
            continue
        if len(cand) < 60:
            last_err = "insufficient_candles"
            candles = None
            continue
        reg, inds = _build_indicator_matrix(cand)
        ix = _entry_bar_index(cand, entry_ms)
        if ix is None:
            last_err = "entry_bar_not_found"
            candles = None
            continue
        need = _first_idx_with_core_indicators(inds)
        if ix < need:
            last_err = f"entry_bar_before_warmup(idx={ix},need={need})"
            candles = None
            continue
        bi = inds[ix]
        if bi.rsi14 is None and bi.adx14 is None:
            last_err = "indicators_null_at_entry_bar"
            candles = None
            continue
        candles = cand
        regimes = reg
        indicators = inds
        idx = ix
        last_err = ""
        break

    if candles is None or regimes is None or indicators is None or idx is None:
        out["indicators_error"] = last_err or "indicator_reconstruction_failed"
        return out

    bi = indicators[idx]
    out.pop("indicators_error", None)
    out["ind_rsi14"] = bi.rsi14
    out["ind_macd_hist"] = bi.macd_hist
    out["ind_ema20"] = bi.ema20
    out["ind_ema50"] = bi.ema50
    out["ind_adx14"] = bi.adx14
    out["ind_atr14_pct"] = bi.atr14_pct
    out["ind_volume_ratio"] = bi.volume_ratio
    out["ind_breakout20"] = bi.breakout20
    out["ind_pullback_ema20"] = bi.pullback_valid
    out["ind_regime"] = regimes[idx]

    bck = _ohlcv_cache_key("BTC/USDT", tf, used_pad_days, entry_ms - used_pad_days * _DAY_MS, entry_ms + tf_ms * 6)
    try:
        if bck not in btc_cache:
            pad_ms = used_pad_days * 24 * 60 * 60 * 1000
            btc_cache[bck] = fetch_ohlcv_for_analysis_window(
                symbol="BTC/USDT",
                timeframe=tf,
                start_ms=entry_ms - pad_ms,
                end_ms=entry_ms + tf_ms * 6,
                max_pages=400,
                timeout_ms=ohlcv_timeout_ms,
                max_retries=ohlcv_max_retries,
            )
        btc_candles = btc_cache[bck]
        out["ind_btc_trend_bull"] = _btc_bull_at_ms(btc_candles, entry_ms)
    except Exception:
        out["ind_btc_trend_bull"] = None

    out["indicators_timeframe"] = tf
    out["indicators_pad_days"] = used_pad_days
    return out


def _flag_row(r: dict[str, Any]) -> dict[str, bool]:
    def fget(key: str) -> float | None:
        v = r.get(key)
        if v is None:
            return None
        try:
            x = float(v)
            return x if math.isfinite(x) else None
        except (TypeError, ValueError):
            return None

    rsi = fget("ind_rsi14")
    adx = fget("ind_adx14")
    mh = fget("ind_macd_hist")
    vr = fget("ind_volume_ratio")
    atrp = fget("ind_atr14_pct")
    btc = r.get("ind_btc_trend_bull")

    def rsi_gt(x: float) -> bool:
        return rsi is not None and rsi > x

    def adx_gt(x: float) -> bool:
        return adx is not None and adx > x

    def adx_lt(x: float) -> bool:
        return adx is not None and adx < x

    return {
        "rsi_gt_60": rsi_gt(60),
        "rsi_50_60": rsi is not None and 50 <= rsi <= 60,
        "rsi_lt_50": rsi is not None and rsi < 50,
        "macd_hist_gt_0": mh is not None and mh > 0,
        "adx_gt_25": adx_gt(25),
        "adx_gt_20": adx_gt(20),
        "adx_lt_18": adx_lt(18),
        "adx_lt_20": adx_lt(20),
        "vol_ratio_gt_1_1": vr is not None and vr > 1.1,
        "vol_ratio_gt_1_2": vr is not None and vr > 1.2,
        "vol_ratio_lt_0_9": vr is not None and vr < 0.9,
        "btc_trend_bull": btc is True,
        "btc_trend_not_bull": btc is False,
        "breakout20": bool(r.get("ind_breakout20")),
        "pullback_ema20": bool(r.get("ind_pullback_ema20")),
        "ema20_gt_ema50": bool(r.get("ind_regime") == "bull"),
        "atr_pct_low": atrp is not None and atrp < 0.35,
        "atr_pct_high": atrp is not None and atrp > 0.55,
        "rsi_high_vol_low": rsi_gt(60) and (vr is not None and vr < 1.0),
        "macd_pos_adx_weak": (mh is not None and mh > 0) and (adx is not None and adx < 20),
    }


def _bucket_stats_for_predicate(
    rows: list[dict[str, Any]],
    name: str,
    pred: Callable[[dict[str, Any]], bool],
) -> dict[str, Any] | None:
    sub = [r for r in rows if pred(r)]
    if not sub:
        return None
    w = sum(1 for x in sub if _is_win(x))
    tot = len(sub)
    wr = w / tot * 100.0
    ap = mean([_pnl_usdt(x) for x in sub])
    return {
        "indicator_bucket": name,
        "count": tot,
        "wins": w,
        "losses": sum(1 for x in sub if _is_loss(x)),
        "win_rate_pct": round(wr, 4),
        "avg_pnl_usdt": round(ap, 6),
    }


def part5_indicator_stats(enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    valid = [r for r in enriched if not r.get("indicators_error")]
    preds: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        # Bandas numéricas: si casi ningún trade cumple flags booleanos, el CSV no queda vacío.
        ("RSI band <40", lambda r: (v := _safe_float(r.get("ind_rsi14"))) is not None and v < 40),
        ("RSI band 40-50", lambda r: (v := _safe_float(r.get("ind_rsi14"))) is not None and 40 <= v < 50),
        ("RSI band 50-60", lambda r: (v := _safe_float(r.get("ind_rsi14"))) is not None and 50 <= v < 60),
        ("RSI band 60-70", lambda r: (v := _safe_float(r.get("ind_rsi14"))) is not None and 60 <= v < 70),
        ("RSI band 70+", lambda r: (v := _safe_float(r.get("ind_rsi14"))) is not None and v >= 70),
        ("RSI null", lambda r: _safe_float(r.get("ind_rsi14")) is None),
        ("ADX <20", lambda r: (v := _safe_float(r.get("ind_adx14"))) is not None and v < 20),
        ("ADX 20-30", lambda r: (v := _safe_float(r.get("ind_adx14"))) is not None and 20 <= v < 30),
        ("ADX 30-40", lambda r: (v := _safe_float(r.get("ind_adx14"))) is not None and 30 <= v < 40),
        ("ADX 40+", lambda r: (v := _safe_float(r.get("ind_adx14"))) is not None and v >= 40),
        ("ADX null", lambda r: _safe_float(r.get("ind_adx14")) is None),
        ("MACD hist <0", lambda r: (v := _safe_float(r.get("ind_macd_hist"))) is not None and v < 0),
        ("MACD hist >=0", lambda r: (v := _safe_float(r.get("ind_macd_hist"))) is not None and v >= 0),
        ("Vol ratio <0.9", lambda r: (v := _safe_float(r.get("ind_volume_ratio"))) is not None and v < 0.9),
        ("Vol ratio 0.9-1.1", lambda r: (v := _safe_float(r.get("ind_volume_ratio"))) is not None and 0.9 <= v <= 1.1),
        ("Vol ratio >1.1", lambda r: (v := _safe_float(r.get("ind_volume_ratio"))) is not None and v > 1.1),
        ("Vol ratio null", lambda r: _safe_float(r.get("ind_volume_ratio")) is None),
        ("ATR% <0.35", lambda r: (v := _safe_float(r.get("ind_atr14_pct"))) is not None and v < 0.35),
        ("ATR% 0.35-0.55", lambda r: (v := _safe_float(r.get("ind_atr14_pct"))) is not None and 0.35 <= v <= 0.55),
        ("ATR% >0.55", lambda r: (v := _safe_float(r.get("ind_atr14_pct"))) is not None and v > 0.55),
        ("ATR% null", lambda r: _safe_float(r.get("ind_atr14_pct")) is None),
        ("RSI>60", lambda r: _flag_row(r)["rsi_gt_60"]),
        ("RSI 50-60", lambda r: _flag_row(r)["rsi_50_60"]),
        ("RSI<50", lambda r: _flag_row(r)["rsi_lt_50"]),
        ("MACD hist>0", lambda r: _flag_row(r)["macd_hist_gt_0"]),
        ("ADX>25", lambda r: _flag_row(r)["adx_gt_25"]),
        ("ADX>20", lambda r: _flag_row(r)["adx_gt_20"]),
        ("ADX<20", lambda r: _flag_row(r)["adx_lt_20"]),
        ("ADX<18", lambda r: _flag_row(r)["adx_lt_18"]),
        ("VolumeRatio>1.2", lambda r: _flag_row(r)["vol_ratio_gt_1_2"]),
        ("VolumeRatio>1.1", lambda r: _flag_row(r)["vol_ratio_gt_1_1"]),
        ("VolumeRatio<0.9", lambda r: _flag_row(r)["vol_ratio_lt_0_9"]),
        ("BTC trend bull", lambda r: _flag_row(r)["btc_trend_bull"]),
        ("BTC trend not bull", lambda r: _flag_row(r)["btc_trend_not_bull"]),
        ("Breakout20", lambda r: _flag_row(r)["breakout20"]),
        ("Pullback EMA20", lambda r: _flag_row(r)["pullback_ema20"]),
        ("EMA20>EMA50 (bull)", lambda r: _flag_row(r)["ema20_gt_ema50"]),
        ("ATR% bajo", lambda r: _flag_row(r)["atr_pct_low"]),
        ("ATR% alto", lambda r: _flag_row(r)["atr_pct_high"]),
        ("RSI alto + vol bajo", lambda r: _flag_row(r)["rsi_high_vol_low"]),
        ("MACD>0 + ADX<20", lambda r: _flag_row(r)["macd_pos_adx_weak"]),
    ]
    for name, pred in preds:
        row = _bucket_stats_for_predicate(valid, name, pred)
        if row:
            rows.append(row)
    return rows


def _combo_stats(
    enriched: list[dict[str, Any]],
    *,
    min_samples: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid = [r for r in enriched if not r.get("indicators_error")]
    keys = [
        "rsi_gt_60",
        "adx_gt_20",
        "adx_gt_25",
        "macd_hist_gt_0",
        "vol_ratio_gt_1_1",
        "vol_ratio_gt_1_2",
        "btc_trend_bull",
        "breakout20",
        "pullback_ema20",
        "ema20_gt_ema50",
    ]
    pair_results: list[dict[str, Any]] = []
    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1 :]:
            label = f"{k1}+{k2}"

            def make_pred(a: str, b: str) -> Callable[[dict[str, Any]], bool]:
                return lambda r, aa=a, bb=b: _flag_row(r)[aa] and _flag_row(r)[bb]

            pred = make_pred(k1, k2)
            sub = [r for r in valid if pred(r)]
            if len(sub) < min_samples:
                continue
            w = sum(1 for x in sub if _is_win(x))
            tot = len(sub)
            wr = w / tot * 100.0
            exp = sum(_pnl_usdt(x) for x in sub) / tot
            ls = sum(1 for x in sub if _is_loss(x))
            pair_results.append(
                {
                    "combo": label,
                    "count": tot,
                    "wins": w,
                    "losses": ls,
                    "win_rate_pct": round(wr, 4),
                    "expectancy_usdt": round(exp, 6),
                }
            )
    top_win = sorted(pair_results, key=lambda r: (-r["win_rate_pct"], -r["count"]))[:20]
    top_lose = sorted(pair_results, key=lambda r: (r["win_rate_pct"], -r["count"]))[:20]
    return top_win, top_lose


def _loser_prevalence(enriched: list[dict[str, Any]], *, min_loss_trades: int = 2) -> list[dict[str, Any]]:
    valid = [r for r in enriched if not r.get("indicators_error")]
    losers = [r for r in valid if _is_loss(r)]
    wins = [r for r in valid if _is_win(r)]
    if len(losers) < min_loss_trades:
        return []
    lw, ll = len(wins), len(losers)
    out: list[dict[str, Any]] = []
    for name, pred in [
        ("RSI>60", lambda r: _flag_row(r)["rsi_gt_60"]),
        ("RSI<50", lambda r: _flag_row(r)["rsi_lt_50"]),
        ("MACD hist>0", lambda r: _flag_row(r)["macd_hist_gt_0"]),
        ("ADX<18", lambda r: _flag_row(r)["adx_lt_18"]),
        ("ADX<20", lambda r: _flag_row(r)["adx_lt_20"]),
        ("VolRatio<0.9", lambda r: _flag_row(r)["vol_ratio_lt_0_9"]),
        ("Sin BTC bull", lambda r: _flag_row(r)["btc_trend_not_bull"]),
        ("ATR% bajo", lambda r: _flag_row(r)["atr_pct_low"]),
        ("RSI alto + vol bajo", lambda r: _flag_row(r)["rsi_high_vol_low"]),
        ("MACD>0 + ADX débil", lambda r: _flag_row(r)["macd_pos_adx_weak"]),
    ]:
        in_loss = sum(1 for r in losers if pred(r))
        in_win = sum(1 for r in wins if pred(r))
        rate_loss = in_loss / ll * 100.0 if ll else 0.0
        rate_win = in_win / lw * 100.0 if lw else 0.0
        skew = rate_loss - rate_win
        out.append(
            {
                "pattern": name,
                "pct_of_losers": round(rate_loss, 4),
                "pct_of_winners": round(rate_win, 4),
                "skew_vs_winners_pct": round(skew, 4),
                "count_in_losers": in_loss,
            }
        )
    out.sort(key=lambda r: (-r["skew_vs_winners_pct"], -r["count_in_losers"]))
    return out[:20]


def part8_recommendations(
    general: dict[str, Any],
    score_rows: list[dict[str, Any]],
    ind_rows: list[dict[str, Any]],
    top_win: list[dict[str, Any]],
    top_lose: list[dict[str, Any]],
    loser_prev: list[dict[str, Any]],
) -> list[str]:
    recs: list[str] = []
    wr = general.get("win_rate_pct")
    pf = general.get("profit_factor")
    if wr is not None and wr < 40:
        recs.append(f"Win rate global bajo ({wr:.1f}%): revisar filtros de entrada o reducir overtrading.")
    if pf is not None and pf < 1.0:
        recs.append(f"Profit factor < 1 ({pf}): las pérdidas superan las ganancias brutas en USDT.")

    best_bucket = None
    best_wr = -1.0
    for s in score_rows:
        if s["bucket"] == "sin_score":
            continue
        if s.get("win_rate_pct") is not None and s["count"] >= 3:
            if s["win_rate_pct"] > best_wr:
                best_wr = s["win_rate_pct"]
                best_bucket = s["bucket"]
    if best_bucket:
        recs.append(
            f"Por score histórico, el bucket «{best_bucket}» tuvo mejor win rate ({best_wr:.1f}%) "
            f"(muestras pequeñas: validar con más trades)."
        )

    for row in ind_rows:
        if row["count"] >= 5 and row["win_rate_pct"] >= 60 and row["avg_pnl_usdt"] and row["avg_pnl_usdt"] > 0:
            recs.append(
                f"Condición favorable histórica: «{row['indicator_bucket']}» "
                f"(WR {row['win_rate_pct']}%, n={row['count']})."
            )
            break

    for row in ind_rows:
        if row["count"] >= 5 and row["win_rate_pct"] <= 35:
            recs.append(
                f"Condición débil histórica: «{row['indicator_bucket']}» "
                f"(WR {row['win_rate_pct']}%, n={row['count']}). Considerar evitar o endurecer filtro."
            )
            break

    if top_win:
        t = top_win[0]
        recs.append(
            f"Mejor combo observado (muestra): {t['combo']} — WR {t['win_rate_pct']}%, "
            f"expectancy {t['expectancy_usdt']} USDT (n={t['count']})."
        )
    if top_lose:
        t = top_lose[0]
        recs.append(
            f"Combo débil observado: {t['combo']} — WR {t['win_rate_pct']}%, "
            f"expectancy {t['expectancy_usdt']} USDT (n={t['count']})."
        )

    if loser_prev:
        p = loser_prev[0]
        recs.append(
            f"Patrón más sobrepresentado en perdedores vs ganadores: «{p['pattern']}» "
            f"(Δ% en cohortes {p['skew_vs_winners_pct']})."
        )

    recs.append(
        "Estas sugerencias son heurísticas sobre el historial local; no sustituyen validación "
        "out-of-sample ni cambios en bot_runner."
    )
    return recs


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fieldnames})


_TRADE_INDICATOR_SNAPSHOT_FIELDS = [
    "source_kind",
    "symbol",
    "timeframe",
    "entry_time",
    "exit_time",
    "pnl_usdt",
    "pnl_pct",
    "entry_rsi",
    "entry_adx",
    "entry_macd_hist",
    "entry_volume_ratio",
    "entry_atr_pct",
    "entry_breakout20",
    "entry_pullback_ema20",
    "entry_btc_trend",
    "indicators_error",
    "indicators_pad_days",
]


def _indicator_context_summary(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(enriched)
    with_ctx = sum(1 for r in enriched if not r.get("indicators_error"))
    without = n - with_ctx
    err_keys = [
        str(r.get("indicators_error") or "").strip() or "unknown" for r in enriched if r.get("indicators_error")
    ]
    c = Counter(err_keys)
    return {
        "total_trades": n,
        "trades_with_indicator_context": with_ctx,
        "trades_without_indicator_context": without,
        "without_context_error_counts": dict(c),
    }


def _trade_indicator_snapshot_rows(enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in enriched:
        btc = r.get("ind_btc_trend_bull")
        if btc is True:
            entry_btc_trend = "bull"
        elif btc is False:
            entry_btc_trend = "not_bull"
        else:
            entry_btc_trend = ""
        pad = r.get("indicators_pad_days")
        rows.append(
            {
                "source_kind": r.get("source_kind") or "",
                "symbol": r.get("symbol") or "",
                "timeframe": r.get("timeframe") or r.get("indicators_timeframe") or "",
                "entry_time": r.get("entry_time") or "",
                "exit_time": r.get("exit_time") or "",
                "pnl_usdt": r.get("pnl_usdt"),
                "pnl_pct": r.get("pnl_pct"),
                "entry_rsi": r.get("ind_rsi14"),
                "entry_adx": r.get("ind_adx14"),
                "entry_macd_hist": r.get("ind_macd_hist"),
                "entry_volume_ratio": r.get("ind_volume_ratio"),
                "entry_atr_pct": r.get("ind_atr14_pct"),
                "entry_breakout20": r.get("ind_breakout20"),
                "entry_pullback_ema20": r.get("ind_pullback_ema20"),
                "entry_btc_trend": entry_btc_trend,
                "indicators_error": r.get("indicators_error") or "",
                "indicators_pad_days": pad if pad is not None else "",
            }
        )
    return rows


def _try_plot_pngs(
    equity_rows: list[dict[str, Any]],
    daily_rows: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    out_dir: Path,
) -> list[str]:
    notes: list[str] = []
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        notes.append("matplotlib no instalado: se omiten PNG (pip install matplotlib).")
        return notes

    if equity_rows:
        xs = list(range(len(equity_rows)))
        ys = [float(r["capital_after"]) for r in equity_rows]
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(xs, ys, color="#2563eb", lw=1.2)
        ax.set_title("Equity curve (USDT)")
        ax.set_xlabel("Trade # (orden por cierre)")
        ax.set_ylabel("Capital")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "equity_curve.png", dpi=120)
        plt.close(fig)

    if daily_rows:
        days = [r["date"] for r in daily_rows]
        pnl = [float(r["net_pnl_usdt"]) for r in daily_rows]
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.bar(days, pnl, color=["#16a34a" if x >= 0 else "#dc2626" for x in pnl])
        ax.set_title("PnL neto por día (USDT)")
        ax.tick_params(axis="x", rotation=45)
        ax.axhline(0, color="#666", lw=0.8)
        fig.tight_layout()
        fig.savefig(out_dir / "daily_pnl.png", dpi=120)
        plt.close(fig)

    score_plot = [r for r in score_rows if r["bucket"] != "sin_score" and r["count"]]
    if score_plot:
        labels = [r["bucket"] for r in score_plot]
        wrs = [float(r["win_rate_pct"] or 0) for r in score_plot]
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(labels, wrs, color="#7c3aed")
        ax.set_ylim(0, max(100, max(wrs) * 1.1))
        ax.set_title("Win rate % por bucket de score de entrada")
        ax.set_ylabel("Win rate %")
        fig.tight_layout()
        fig.savefig(out_dir / "score_vs_winrate.png", dpi=120)
        plt.close(fig)

    notes.append("PNG generados en trade_analysis/")
    return notes


def run_bot_trade_analysis_v2(
    *,
    sources: list[str] | None = None,
    default_timeframe: str = "30m",
    output_dir: Path | None = None,
    skip_network: bool = False,
    max_trades: int | None = None,
    symbols: Iterable[str] | None = None,
    ohlcv_timeout_ms: int = 30_000,
    ohlcv_max_retries: int = 3,
) -> dict[str, Any]:
    out_dir = output_dir or _OUTPUT_DIR
    trades = load_merged_trades(sources=sources)
    _log(f"trades cargados: {len(trades)}")

    want_syms = (
        {_ccxt_symbol(s).strip().upper() for s in symbols if str(s).strip()} if symbols else None
    )
    if want_syms:
        trades = [t for t in trades if _ccxt_symbol(str(t.get("symbol") or "")).strip().upper() in want_syms]
        _log(f"filtrado por símbolos {sorted(want_syms)}: {len(trades)} trades")
    if max_trades is not None and max_trades > 0:
        trades = trades[-max_trades:]
        _log(f"max_trades={max_trades} (más recientes por exit_time): {len(trades)} trades")

    _log(f"trades a analizar: {len(trades)}")

    p1 = part1_general_stats(trades)
    daily = part2_daily_stats(trades)
    streak_meta = _detect_streaks(daily)
    eq_rows, eq_meta = part3_equity_curve(trades)
    score_rows = part4_score_buckets(trades)

    candle_cache: dict[tuple[str, str, int, int, int], list[list[float]]] = {}
    btc_cache: dict[tuple[str, str, int, int, int], list[list[float]]] = {}
    enriched: list[dict[str, Any]] = []
    if not skip_network:
        ntr = len(trades)
        if ntr:
            _log("inicio enriquecimiento OHLCV/indicadores (ccxt, puede tardar)...")
        for i, t in enumerate(trades):
            enriched.append(
                enrich_trade_with_entry_indicators(
                    t,
                    default_timeframe=default_timeframe,
                    candle_cache=candle_cache,
                    btc_cache=btc_cache,
                    ohlcv_timeout_ms=ohlcv_timeout_ms,
                    ohlcv_max_retries=ohlcv_max_retries,
                )
            )
            if ntr and ((i + 1) % 5 == 0 or (i + 1) == ntr):
                _log(f"enriching indicators {i + 1}/{ntr}")
    else:
        enriched = [dict(t) for t in trades]
        for r in enriched:
            r["indicators_error"] = "skipped_network"

    ctx_summary = _indicator_context_summary(enriched)

    ind_stats = part5_indicator_stats(enriched)
    top_win, top_lose = _combo_stats(enriched)
    loser_prev = _loser_prevalence(enriched)

    combo_rows: list[dict[str, Any]] = []
    for r in top_win:
        combo_rows.append({**r, "tier": "top_winning"})
    for r in top_lose:
        combo_rows.append({**r, "tier": "top_losing"})

    recs = part8_recommendations(p1, score_rows, ind_stats, top_win, top_lose, loser_prev)

    _write_csv(
        out_dir / "equity_curve.csv",
        ["exit_time", "symbol", "source_kind", "pnl_usdt", "pnl_pct", "capital_after", "drawdown_from_peak", "exit_reason"],
        eq_rows,
    )
    _write_csv(
        out_dir / "daily_stats.csv",
        ["date", "trades", "wins", "losses", "net_pnl_usdt", "win_rate_pct"],
        daily,
    )
    _write_csv(
        out_dir / "score_stats.csv",
        ["bucket", "count", "wins", "losses", "win_rate_pct", "avg_pnl_usdt"],
        score_rows,
    )
    _write_csv(
        out_dir / "indicator_stats.csv",
        ["indicator_bucket", "count", "wins", "losses", "win_rate_pct", "avg_pnl_usdt"],
        ind_stats,
    )
    _write_csv(
        out_dir / "combo_stats.csv",
        ["tier", "combo", "count", "wins", "losses", "win_rate_pct", "expectancy_usdt"],
        combo_rows,
    )
    _write_csv(
        out_dir / "loser_pattern_stats.csv",
        ["pattern", "pct_of_losers", "pct_of_winners", "skew_vs_winners_pct", "count_in_losers"],
        loser_prev,
    )
    snap_rows = _trade_indicator_snapshot_rows(enriched)
    _write_csv(out_dir / "trade_indicator_snapshot.csv", _TRADE_INDICATOR_SNAPSHOT_FIELDS, snap_rows)

    meta_path = out_dir / "analysis_meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "part1": p1,
                "equity_meta": eq_meta,
                "daily_streaks": streak_meta,
                "indicator_context": ctx_summary,
                "recommendations": recs,
                "loser_patterns": loser_prev,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    png_notes = _try_plot_pngs(eq_rows, daily, score_rows, out_dir)

    return {
        "ok": True,
        "output_dir": str(out_dir.resolve()),
        "part1": p1,
        "equity_meta": eq_meta,
        "daily_streaks": streak_meta,
        "score_rows": score_rows,
        "indicator_stats": ind_stats,
        "indicator_context": ctx_summary,
        "combo_top_win": top_win,
        "combo_top_lose": top_lose,
        "recommendations": recs,
        "png_notes": png_notes,
        "trades_enriched_sample": enriched[:3],
    }


def print_indicator_context_footer(result: dict[str, Any]) -> None:
    """Resumen de reconstrucción de indicadores (siempre imprimir al cerrar el script)."""
    ic = result.get("indicator_context") or {}
    print(f"trades_with_indicator_context={ic.get('trades_with_indicator_context')}", flush=True)
    print(f"trades_without_indicator_context={ic.get('trades_without_indicator_context')}", flush=True)
    wce = ic.get("without_context_error_counts") or {}
    print(f"without_context_error_counts={json.dumps(wce, ensure_ascii=False)}", flush=True)


def print_executive_summary(result: dict[str, Any]) -> None:
    p1 = result.get("part1") or {}
    print("\n========== RESUMEN EJECUTIVO (BOT TRADES V2) ==========\n")
    print(f"Total trades: {p1.get('total_trades')}")
    print(f"Win rate: {p1.get('win_rate_pct')}%")
    print(f"Profit factor: {p1.get('profit_factor')}")
    print(f"Expectancy (USDT/trade): {p1.get('expectancy_usdt')}")
    em = result.get("equity_meta") or {}
    print(f"Capital final (base 10k): {em.get('final_capital')} USDT")
    print(f"Max drawdown: {em.get('max_drawdown_usdt')} USDT | Recovery factor: {em.get('recovery_factor')}")
    ic = result.get("indicator_context") or {}
    print(
        f"Indicadores en entrada: con contexto {ic.get('trades_with_indicator_context')} | "
        f"sin contexto {ic.get('trades_without_indicator_context')}"
    )

    best_score = None
    for r in result.get("score_rows") or []:
        if r.get("bucket") == "sin_score":
            continue
        if (r.get("count") or 0) >= 2 and r.get("win_rate_pct") is not None:
            if best_score is None or r["win_rate_pct"] > best_score[1]:
                best_score = (r["bucket"], r["win_rate_pct"])
    if best_score:
        print(f"Score bucket con mejor WR (muestra): {best_score[0]} @ {best_score[1]}%")

    score_rows = result.get("score_rows") or []
    b80 = next((r for r in score_rows if r["bucket"] == "80+"), None)
    b6064 = next((r for r in score_rows if r["bucket"] == "60-64"), None)
    if b80 and b6064 and (b80.get("count") or 0) >= 2 and (b6064.get("count") or 0) >= 2:
        print(
            f"\n¿Subir score mejora? Comparación rápida: "
            f"80+ WR {b80.get('win_rate_pct')}% (n={b80.get('count')}) vs "
            f"60-64 WR {b6064.get('win_rate_pct')}% (n={b6064.get('count')}). "
            "Interpretar con cautela (muestras pequeñas / sesgo de régimen)."
        )
    inds = sorted(result.get("indicator_stats") or [], key=lambda x: -float(x.get("win_rate_pct") or 0))[:5]
    print("\n--- Indicadores con mayor WR (TOP 5, n>=1) ---")
    for r in inds:
        print(
            f"  {r['indicator_bucket']}: WR {r['win_rate_pct']}%  "
            f"avgPnL {r['avg_pnl_usdt']}  n={r['count']}"
        )
    worst = sorted(result.get("indicator_stats") or [], key=lambda x: float(x.get("win_rate_pct") or 0))[:5]
    if worst:
        print("\n--- Indicadores con menor WR (TOP 5) ---")
        for r in worst:
            if (r.get("count") or 0) < 1:
                continue
            print(
                f"  {r['indicator_bucket']}: WR {r['win_rate_pct']}%  "
                f"avgPnL {r['avg_pnl_usdt']}  n={r['count']}"
            )
    print("\n--- Mejores combinaciones (TOP 5) ---")
    for r in (result.get("combo_top_win") or [])[:5]:
        print(f"  {r['combo']}: WR {r['win_rate_pct']}%  E={r['expectancy_usdt']}  n={r['count']}")
    print("\n--- Peores combinaciones (TOP 5) ---")
    for r in (result.get("combo_top_lose") or [])[:5]:
        print(f"  {r['combo']}: WR {r['win_rate_pct']}%  E={r['expectancy_usdt']}  n={r['count']}")
    print("\n--- Recomendaciones (texto) ---")
    for line in result.get("recommendations") or []:
        print(f"  - {line}")
    print("\nCSV y PNG en:", result.get("output_dir"))
    print("========================================================\n")
