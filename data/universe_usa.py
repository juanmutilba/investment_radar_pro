TICKERS_CORE = [
    'AAPL', 'MSFT', 'META', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'AMD', 'NFLX', 'MELI',
    'KO', 'PEP', 'WMT', 'COST', 'PG', 'JNJ', 'UNH', 'XOM', 'CVX', 'V',
    'MA', 'JPM', 'HD', 'DIS', 'MCD', 'NKE', 'CAT', 'BA', 'IBM', 'ORCL'
]

TICKERS_ETF = [
    'SPY', 'QQQ', 'DIA', 'IWM', 'EEM', 'XLF', 'XLE', 'XLK', 'ARKK', 'IVV'
]

TICKERS_GROWTH = [
    'ASML', 'TEAM', 'NOW', 'PATH', 'CEG', 'HOOD', 'RKLB', 'OKLO', 'AI', 'TEM'
]

TICKERS_USA = TICKERS_CORE + TICKERS_ETF + TICKERS_GROWTH


def classify_universe_type(ticker: str) -> str:
    if ticker in TICKERS_CORE:
        return 'CORE'
    if ticker in TICKERS_ETF:
        return 'ETF'
    if ticker in TICKERS_GROWTH:
        return 'GROWTH'
    return 'OTRO'
