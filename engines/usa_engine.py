from __future__ import annotations

import pandas as pd
import time
import yfinance as yf

from core.config import PRICE_HISTORY_PERIOD, YFINANCE_INFO_TIMEOUT_S
from core.risk import calculate_risk_score, classify_risk_profile
from core.scoring import calculate_fund_score, calculate_tech_score
from core.signals import classify_conviction, classify_setup, classify_signal_state, suggested_capital
from core.technicals import compute_technical_metrics
from data.universe_usa import TICKERS_USA, classify_universe_type, classify_universe_visual
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


def run_usa_engine() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    t0 = time.perf_counter()
    prev_run = load_previous_engine("usa")
    if prev_run:
        print(
            f"[USA] Referencia corrida anterior: t={prev_run.get('elapsed_s')}s | "
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

    for ticker in TICKERS_USA:
        print(f'Procesando USA: {ticker}')
        stage = "init"
        try:
            asset = yf.Ticker(ticker)
            stage = "history"
            # repair=True puede requerir scipy en algunas instalaciones de yfinance; evitarlo para robustez.
            data = asset.history(period=PRICE_HISTORY_PERIOD, auto_adjust=False, actions=False, repair=False)
            if data.empty:
                n_hist_empty += 1
                print(f"[USA] omitido {ticker}: history vacío (sin velas)")
                continue

            close = pd.to_numeric(data['Close'], errors='coerce').dropna()
            if len(close) < 200:
                n_hist_short += 1
                print(
                    f"[USA] omitido {ticker}: history insuficiente "
                    f"({len(close)} velas válidas < 200)"
                )
                continue

            # INFO es lo más lento y poco variable: cache por ticker con TTL.
            stage = "info"
            info = cache.get_or_fetch_info(
                ticker=ticker,
                fetcher=lambda: fetch_info_with_timeout(asset, timeout_s=YFINANCE_INFO_TIMEOUT_S),
            )
            company = info.get('longName') or info.get('shortName') or ticker
            sector = info.get('sector')
            industry = info.get('industry')
            market_cap = format_number(info.get('marketCap'))
            beta = format_number(info.get('beta'))
            roe = format_number(info.get('returnOnEquity'))
            risk_profile = classify_risk_profile(beta)
            risk_score = calculate_risk_score(beta)
            universe_type = classify_universe_type(ticker)
            universe_visual = classify_universe_visual(ticker=ticker, exchange=info.get("exchange"))

            stage = "technicals"
            technicals = compute_technical_metrics(close)
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
                ticker, company, sector, industry, universe_type, universe_visual,
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
                ticker, company, sector, industry, universe_type, universe_visual,
                market_cap, beta, roe, risk_profile,
            ])
            if not precio_valido(technicals.get("Precio")):
                n_sin_precio += 1
                print(f"[USA] precio inválido tras history/fast_info: {ticker} → {technicals.get('Precio')!r}")

            n_ok += 1
        except Exception as e:
            n_fail += 1
            if stage == "history":
                fail_history_exc += 1
            elif stage == "info":
                fail_info_exc += 1
            elif stage == "technicals":
                fail_tech_exc += 1
            else:
                fail_other += 1
            print(f"[USA] FAIL {ticker} stage={stage} err={type(e).__name__}: {e}")

    df = pd.DataFrame(results, columns=[
        'Ticker', 'Empresa', 'Sector', 'Industria', 'TipoUniverso', 'Universo',
        'MarketCap', 'Beta', 'ROE', 'RiskProfile', 'RiskScore',
        'Precio', 'RSI', 'MA50', 'MA200', 'MACD_Bull', 'Pullback', 'Trend',
        'PE', 'PriceToBook', 'EBITDA', 'NetIncome', 'DebtToEquity', 'DebtToEbitda', 'TargetPrice', 'Upside_%',
        'TechScore', 'FundScore', 'TotalScore', 'Setup', 'SignalState',
        'Conviccion', 'CapitalSugerido_%',
    ])

    df_universo = pd.DataFrame(universe_rows, columns=[
        'Ticker', 'Empresa', 'Sector', 'Industria', 'TipoUniverso', 'Universo',
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

    # Persistir cache 1 vez por corrida.
    cache.save()

    elapsed = time.perf_counter() - t0
    sin_hist_total = n_hist_empty + n_hist_short
    cmp = format_delta_line("[USA]", prev_run, elapsed)
    if cmp:
        print(cmp)
    print(
        f"[USA] OK={n_ok} FAIL={n_fail} | "
        f"SIN_HISTORY={sin_hist_total} (vacío={n_hist_empty} insuf_velas={n_hist_short}) | "
        f"SIN_PRECIO_OK={n_sin_precio} | "
        f"cache_hits={cache.stats.hits} cache_misses={cache.stats.misses} "
        f"info_fetches={cache.stats.stores} | "
        f"fast_price_used={n_fast_price_used} | "
        f"fail_breakdown=(history_exc={fail_history_exc} info_exc={fail_info_exc} tech_exc={fail_tech_exc} other={fail_other}) | "
        f"t={elapsed:.1f}s"
    )

    save_engine_metrics(
        "usa",
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

    return df, df_universo, sector_summary, df[['Ticker']].copy()
