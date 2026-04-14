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


# Universo "visual" para el radar (tabs en frontend).
# Prioridad: Dow Jones > S&P 500 > Nasdaq > Otros.
# Nota: la cobertura se puede ampliar editando estas listas sin tocar el pipeline.
DOW_JONES_TICKERS = {
    "AAPL", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "GS",
    "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "MCD", "MMM", "MSFT",
    "NKE", "PG", "TRV", "UNH", "V", "VZ", "WBA", "WMT", "XOM",
}

SP500_TICKERS = set(TICKERS_CORE) | set(TICKERS_GROWTH)


def classify_universe_visual(*, ticker: str, exchange: str | None = None) -> str:
    t = (ticker or "").upper().strip()
    if t in DOW_JONES_TICKERS:
        return "Dow Jones"
    if t in SP500_TICKERS:
        return "S&P 500"
    # En Yahoo suele venir como "NMS" para Nasdaq; dejamos un fallback conservador.
    ex = (exchange or "").upper().strip()
    if ex in {"NMS", "NAS", "NASDAQ"}:
        return "Nasdaq"
    return "Nasdaq"
