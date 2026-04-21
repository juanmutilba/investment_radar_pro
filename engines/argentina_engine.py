from __future__ import annotations

import pandas as pd
import time
import yfinance as yf

from core.config import PRICE_HISTORY_PERIOD, YFINANCE_INFO_TIMEOUT_S
from core.risk import calculate_risk_score, classify_risk_profile
from core.scoring import calculate_fund_score, calculate_tech_score
from core.signals import classify_conviction, classify_setup, classify_signal_state, suggested_capital
from core.technicals import compute_technical_metrics
from data.universe_arg import ARGENTINA_UNIVERSE
from services.engine_run_metrics import format_delta_line, load_previous_engine, save_engine_metrics
from services.fundamentals_cache import FundamentalsCache
from services.yfinance_helpers import fetch_info_with_timeout, precio_valido, try_apply_fast_info_price


def format_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _arg_log(level: str, yahoo_ticker: str, local_ticker: str, panel: str, msg: str) -> None:
    """
    Logger simple por stdout para el motor Argentina.
    Mantener formato estable para grep: [ARG][LEVEL][LOCAL][YAHOO][PANEL] mensaje
    """
    lvl = (level or "INFO").strip().upper()
    yt = (yahoo_ticker or "").strip()
    lt = (local_ticker or "").strip()
    pn = (panel or "").strip() or "?"
    print(f"[ARG][{lvl}][{lt}][{yt}][{pn}] {msg}")


def run_argentina_engine() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    t0 = time.perf_counter()
    prev_run = load_previous_engine("arg")
    if prev_run:
        print(
            f"[ARG] Referencia corrida anterior: t={prev_run.get('elapsed_s')}s | "
            f"OK={prev_run.get('n_ok')} cache_hits={prev_run.get('cache_hits')} "
            f"info_fetches={prev_run.get('info_fetches')} SIN_HISTORY={prev_run.get('sin_history_total')}"
        )
    results = []
    universe_rows = []
    cache = FundamentalsCache()
    cache.load()
    n_ok = 0
    n_fail = 0
    n_hist_empty = 0
    n_hist_short = 0
    n_fast_price_used = 0
    n_sin_precio = 0
    fail_history_exc = 0
    fail_tech_exc = 0
    fail_info_exc = 0
    fail_other = 0
    # Diagnóstico: tickers sospechosos de símbolo Yahoo incorrecto / no soportado
    suspected_bad_yahoo: list[tuple[str, str, str]] = []

    for item in ARGENTINA_UNIVERSE:
        yahoo_ticker = item['ticker']
        local_ticker = item['local_ticker']
        panel = item.get("panel") or "Merval"
        mercado = item.get("mercado") or ("General" if str(panel).strip().lower() in ("general", "panel general") else "Merval")
        t_ticker0 = time.perf_counter()
        _arg_log("INFO", yahoo_ticker, local_ticker, panel, "start")
        stage = "init"
        try:
            asset = yf.Ticker(yahoo_ticker)
            stage = "history"
            # repair=True puede requerir scipy en algunas instalaciones de yfinance; evitarlo para robustez.
            data = asset.history(period=PRICE_HISTORY_PERIOD, auto_adjust=False, actions=False, repair=False)
            if data.empty:
                n_hist_empty += 1
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, "omitido: history vacío (sin velas)")
                suspected_bad_yahoo.append((local_ticker, yahoo_ticker, "history_empty"))
                continue

            required_cols = {"Close"}
            missing_cols = sorted([c for c in required_cols if c not in data.columns])
            if missing_cols:
                n_hist_empty += 1
                _arg_log(
                    "WARN",
                    yahoo_ticker,
                    local_ticker,
                    panel,
                    f"omitido: history sin columnas requeridas missing={missing_cols} cols={list(data.columns)}",
                )
                suspected_bad_yahoo.append((local_ticker, yahoo_ticker, f"missing_cols:{','.join(missing_cols)}"))
                continue

            close = pd.to_numeric(data['Close'], errors='coerce').dropna()
            if close.empty:
                n_hist_empty += 1
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, "omitido: Close vacío/NaN tras coerción")
                suspected_bad_yahoo.append((local_ticker, yahoo_ticker, "close_all_nan"))
                continue
            if len(close) < 200:
                n_hist_short += 1
                _arg_log(
                    "WARN",
                    yahoo_ticker,
                    local_ticker,
                    panel,
                    f"omitido: history insuficiente ({len(close)} velas válidas < 200)",
                )
                continue

            stage = "info"
            info = cache.get_or_fetch_info(
                ticker=yahoo_ticker,
                fetcher=lambda: fetch_info_with_timeout(asset, timeout_s=YFINANCE_INFO_TIMEOUT_S),
            )
            if not isinstance(info, dict) or not info:
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, "info vacío/no dict (se sigue con defaults)")
                info = info if isinstance(info, dict) else {}
            company = info.get('longName') or info.get('shortName') or local_ticker
            sector = info.get('sector')
            industry = info.get('industry')
            market_cap = format_number(info.get('marketCap'))
            beta = format_number(info.get('beta'))
            roe = format_number(info.get('returnOnEquity'))
            risk_profile = classify_risk_profile(beta)
            risk_score = calculate_risk_score(beta)

            stage = "technicals"
            technicals = compute_technical_metrics(close)
            # Diagnóstico: llaves mínimas que el engine espera de technicals
            missing_tech_keys = [k for k in ("Precio", "RSI", "MA50", "MA200", "MACD_Bull", "Pullback", "Trend") if k not in technicals]
            if missing_tech_keys:
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, f"technicals incompleto missing_keys={missing_tech_keys}")
            if try_apply_fast_info_price(asset, technicals, format_number):
                n_fast_price_used += 1
            pe = format_number(info.get('trailingPE'))
            price_to_book = format_number(info.get('priceToBook'))
            ebitda = format_number(info.get('ebitda'))
            net_income = format_number(info.get('netIncomeToCommon'))
            total_debt = format_number(info.get('totalDebt'))
            debt_to_equity = format_number(info.get('debtToEquity'))
            target_price = format_number(info.get('targetMeanPrice'))

            debt_to_ebitda = None
            if total_debt is not None and ebitda is not None and ebitda > 0:
                debt_to_ebitda = round(total_debt / ebitda, 2)

            upside = None
            if target_price is not None and technicals['Precio']:
                upside = (target_price - technicals['Precio']) / technicals['Precio']

            # Diagnóstico: datos críticos ausentes (no cambia cálculos; solo informa)
            if not precio_valido(technicals.get("Precio")):
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, f"precio no válido para scoring: Precio={technicals.get('Precio')!r}")
            if technicals.get("RSI") is None:
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, "RSI=None (puede afectar score técnico)")

            tech_score = calculate_tech_score(
                rsi=technicals['RSI'],
                pullback=technicals['Pullback'],
                trend_positive=technicals['Trend'],
                macd_bullish=technicals['MACD_Bull'],
            )
            fund_score = calculate_fund_score(net_income, ebitda, debt_to_equity, pe, upside)
            total_score = tech_score + fund_score + risk_score

            setup = classify_setup(
                rsi=technicals['RSI'],
                pullback=technicals['Pullback'],
                trend_positive=technicals['Trend'],
                macd_bullish=technicals['MACD_Bull'],
            )
            signal_state = classify_signal_state(
                total_score=total_score,
                upside=upside,
                price=technicals['Precio'],
                target_price=target_price,
                rsi=technicals['RSI'],
                macd_bullish=technicals['MACD_Bull'],
                trend_positive=technicals['Trend'],
            )
            conviction = classify_conviction(total_score)
            capital = suggested_capital(total_score)

            results.append([
                local_ticker, company, sector, industry, 'ARGENTINA', panel, mercado,
                market_cap, beta, roe, risk_profile, risk_score,
                technicals['Precio'], technicals['RSI'], technicals['MA50'], technicals['MA200'],
                technicals['MACD_Bull'], technicals['Pullback'], technicals['Trend'],
                round(pe, 2) if pe is not None else None,
                round(price_to_book, 2) if price_to_book is not None else None,
                ebitda,
                net_income,
                round(debt_to_equity, 2) if debt_to_equity is not None else None,
                debt_to_ebitda,
                round(target_price, 2) if target_price is not None else None,
                round(upside * 100, 2) if upside is not None else None,
                tech_score, fund_score, total_score,
                setup, signal_state, conviction, capital,
            ])

            universe_rows.append([
                local_ticker, company, sector, industry, 'ARGENTINA', panel, mercado,
                market_cap, beta, roe, risk_profile,
            ])
            if not precio_valido(technicals.get("Precio")):
                n_sin_precio += 1
                _arg_log(
                    "WARN",
                    yahoo_ticker,
                    local_ticker,
                    panel,
                    f"precio inválido tras history/fast_info: {technicals.get('Precio')!r}",
                )

            n_ok += 1
            elapsed_ms = (time.perf_counter() - t_ticker0) * 1000.0
            _arg_log("INFO", yahoo_ticker, local_ticker, panel, f"ok elapsed_ms={elapsed_ms:.0f}")
        except Exception as e:
            n_fail += 1
            if stage == "history":
                fail_history_exc += 1
                suspected_bad_yahoo.append((local_ticker, yahoo_ticker, f"history_exc:{type(e).__name__}"))
            elif stage == "info":
                fail_info_exc += 1
            elif stage == "technicals":
                fail_tech_exc += 1
            else:
                fail_other += 1
            elapsed_ms = (time.perf_counter() - t_ticker0) * 1000.0
            _arg_log("ERROR", yahoo_ticker, local_ticker, panel, f"FAIL stage={stage} err={type(e).__name__}: {e} elapsed_ms={elapsed_ms:.0f}")

    if suspected_bad_yahoo:
        # Log simple para ayudar a detectar símbolos Yahoo incorrectos sin rehacer mapping ahora.
        uniq: dict[tuple[str, str], set[str]] = {}
        for lt, yt, reason in suspected_bad_yahoo:
            uniq.setdefault((lt, yt), set()).add(reason)
        top = sorted(uniq.items(), key=lambda kv: (kv[0][0], kv[0][1]))
        print("[ARG][WARN] Tickers con sospecha de símbolo Yahoo incorrecto/no soportado:")
        for (lt, yt), reasons in top[:30]:
            print(f"[ARG][WARN] - {lt} -> {yt} reasons={sorted(reasons)}")

    df = pd.DataFrame(results, columns=[
        'Ticker', 'Empresa', 'Sector', 'Industria', 'TipoUniverso', 'Panel', 'Mercado',
        'MarketCap', 'Beta', 'ROE', 'RiskProfile', 'RiskScore',
        'Precio', 'RSI', 'MA50', 'MA200', 'MACD_Bull', 'Pullback', 'Trend',
        'PE', 'PriceToBook', 'EBITDA', 'NetIncome', 'DebtToEquity', 'DebtToEbitda', 'TargetPrice', 'Upside_%',
        'TechScore', 'FundScore', 'TotalScore', 'Setup', 'SignalState',
        'Conviccion', 'CapitalSugerido_%',
    ])

    df_universo = pd.DataFrame(universe_rows, columns=[
        'Ticker', 'Empresa', 'Sector', 'Industria', 'TipoUniverso', 'Panel', 'Mercado',
        'MarketCap', 'Beta', 'ROE', 'RiskProfile',
    ]).drop_duplicates(subset=['Ticker'])

    sector_summary = (
        df.groupby('Sector', dropna=False)
        .agg(SectorScorePromedio=('TotalScore', 'mean'), CantidadActivos=('Ticker', 'count'))
        .reset_index()
    )
    if not sector_summary.empty:
        sector_summary['SectorScorePromedio'] = sector_summary['SectorScorePromedio'].round(2)
        sector_summary = sector_summary.sort_values('SectorScorePromedio', ascending=False).reset_index(drop=True)
        sector_summary['RankingSector'] = sector_summary.index + 1
        df = df.merge(sector_summary[['Sector', 'SectorScorePromedio', 'RankingSector']], on='Sector', how='left')
    else:
        df['SectorScorePromedio'] = None
        df['RankingSector'] = None

    cache.save()

    elapsed = time.perf_counter() - t0
    sin_hist_total = n_hist_empty + n_hist_short
    cmp = format_delta_line("[ARG]", prev_run, elapsed)
    if cmp:
        print(cmp)
    print(
        f"[ARG] OK={n_ok} FAIL={n_fail} | "
        f"SIN_HISTORY={sin_hist_total} (vacío={n_hist_empty} insuf_velas={n_hist_short}) | "
        f"SIN_PRECIO_OK={n_sin_precio} | "
        f"cache_hits={cache.stats.hits} cache_misses={cache.stats.misses} "
        f"info_fetches={cache.stats.stores} | "
        f"fast_price_used={n_fast_price_used} | "
        f"fail_breakdown=(history_exc={fail_history_exc} info_exc={fail_info_exc} tech_exc={fail_tech_exc} other={fail_other}) | "
        f"t={elapsed:.1f}s"
    )

    save_engine_metrics(
        "arg",
        {
            "elapsed_s": round(elapsed, 3),
            "n_ok": n_ok,
            "n_fail": n_fail,
            "sin_history_empty": n_hist_empty,
            "sin_history_short": n_hist_short,
            "sin_history_total": sin_hist_total,
            "n_sin_precio_en_ok": n_sin_precio,
            "cache_hits": cache.stats.hits,
            "cache_misses": cache.stats.misses,
            "info_fetches": cache.stats.stores,
            "fast_price_used": n_fast_price_used,
            "cache_errors": cache.stats.errors,
        },
    )

    return df, df_universo, sector_summary
