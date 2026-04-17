from data.cedear_mapping import ticker_usa_list_for_universe_merge

# Subyacentes USA de CEDEAR activos se fusionan al final de TICKERS_USA (dedupe; ticker limpio, sin .BA).

TICKERS_CORE = [
    'AAPL', 'MSFT', 'META', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'AMD', 'NFLX', 'MELI',
    'KO', 'PEP', 'WMT', 'COST', 'PG', 'JNJ', 'UNH', 'XOM', 'CVX', 'V',
    'MA', 'JPM', 'HD', 'DIS', 'MCD', 'NKE', 'CAT', 'BA', 'IBM', 'ORCL',
]

# Mega/large cap y líquidos (S&P / Nasdaq); sin solapar con CORE/ETF/GROWTH.
TICKERS_EXTENDED = [
    'LLY', 'ABBV', 'MRK', 'TMO', 'ABT', 'ACN', 'DHR', 'VZ', 'PM', 'TXN',
    'QCOM', 'INTU', 'ISRG', 'AMAT', 'MU', 'ADI', 'LRCX', 'KLAC', 'SNPS', 'CDNS',
    'SYK', 'GILD', 'MDLZ', 'ELV', 'CI', 'HUM', 'BSX', 'EW', 'ZTS', 'REGN',
    'SCHW', 'BLK', 'SPGI', 'MCO', 'ICE', 'CME', 'BKNG', 'TMUS', 'CMCSA', 'T',
    'NEE', 'SO', 'DUK', 'AEP',     'MMC', 'CB', 'PGR', 'ALL', 'LOW', 'TGT',
    'SBUX', 'F', 'GM', 'GE', 'RTX', 'LMT', 'NOC', 'GD', 'DE',
    'EMR', 'ETN', 'ITW', 'FDX', 'UPS', 'SLB', 'COP', 'OXY', 'MPC', 'PSX',
    'VLO', 'EOG', 'WFC', 'BAC', 'C', 'MET', 'PYPL', 'UBER', 'PANW', 'CRWD',
    'SNOW', 'NET', 'DDOG', 'SHOP', 'COIN', 'RBLX', 'BRK-B', 'AXP', 'GS', 'MS',
]

TICKERS_ETF = [
    'SPY', 'QQQ', 'DIA', 'IWM', 'EEM', 'XLF', 'XLE', 'XLK', 'ARKK', 'IVV',
]

TICKERS_GROWTH = [
    'ASML', 'TEAM', 'NOW', 'PATH', 'CEG', 'HOOD', 'RKLB', 'OKLO', 'AI', 'TEM',
]


def _dedupe_preserve_order(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        u = x.upper().strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


TICKERS_USA = _dedupe_preserve_order(
    TICKERS_CORE + TICKERS_EXTENDED + TICKERS_ETF + TICKERS_GROWTH + ticker_usa_list_for_universe_merge(),
)


def classify_universe_type(ticker: str) -> str:
    t = (ticker or "").upper().strip()
    if t in TICKERS_CORE:
        return 'CORE'
    if t in TICKERS_EXTENDED:
        return 'CORE'
    if t in TICKERS_ETF:
        return 'ETF'
    if t in TICKERS_GROWTH:
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

SP500_TICKERS = set(TICKERS_CORE) | set(TICKERS_EXTENDED) | set(TICKERS_GROWTH)


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
