from __future__ import annotations

import pandas as pd
import yfinance as yf

from core.config import PRICE_HISTORY_PERIOD
from core.risk import calculate_risk_score, classify_risk_profile
from core.scoring import calculate_fund_score, calculate_tech_score
from core.signals import classify_conviction, classify_setup, classify_signal_state, suggested_capital
from core.technicals import compute_technical_metrics
from data.universe_usa import TICKERS_USA, classify_universe_type


def format_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def run_usa_engine() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    results = []
    universe_rows = []

    for ticker in TICKERS_USA:
        print(f'Procesando USA: {ticker}')
        try:
            asset = yf.Ticker(ticker)
            data = asset.history(period=PRICE_HISTORY_PERIOD, auto_adjust=False)
            if data.empty:
                continue

            close = pd.to_numeric(data['Close'], errors='coerce').dropna()
            if len(close) < 200:
                continue

            info = asset.info
            company = info.get('longName') or info.get('shortName') or ticker
            sector = info.get('sector')
            industry = info.get('industry')
            market_cap = format_number(info.get('marketCap'))
            beta = format_number(info.get('beta'))
            roe = format_number(info.get('returnOnEquity'))
            risk_profile = classify_risk_profile(beta)
            risk_score = calculate_risk_score(beta)
            universe_type = classify_universe_type(ticker)

            technicals = compute_technical_metrics(close)
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
                ticker, company, sector, industry, universe_type,
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
                ticker, company, sector, industry, universe_type,
                market_cap, beta, roe, risk_profile,
            ])
        except Exception as e:
            print(f'Error USA en {ticker}: {e}')

    df = pd.DataFrame(results, columns=[
        'Ticker', 'Empresa', 'Sector', 'Industria', 'TipoUniverso',
        'MarketCap', 'Beta', 'ROE', 'RiskProfile', 'RiskScore',
        'Precio', 'RSI', 'MA50', 'MA200', 'MACD_Bull', 'Pullback', 'Trend',
        'PE', 'PriceToBook', 'EBITDA', 'NetIncome', 'DebtToEquity', 'DebtToEbitda', 'TargetPrice', 'Upside_%',
        'TechScore', 'FundScore', 'TotalScore', 'Setup', 'SignalState',
        'Conviccion', 'CapitalSugerido_%',
    ])

    df_universo = pd.DataFrame(universe_rows, columns=[
        'Ticker', 'Empresa', 'Sector', 'Industria', 'TipoUniverso',
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

    return df, df_universo, sector_summary, df[['Ticker']].copy()
