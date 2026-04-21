# Yahoo Finance suele usar sufijo .BA para acciones argentinas.
# Mantener el contrato actual: `ARGENTINA_UNIVERSE` es una lista de dicts con
# {ticker (Yahoo), local_ticker (sin sufijo), panel}.

YAHOO_ARG_SUFFIX = ".BA"

# Universo principal (Merval) solicitado. Mantener sin sufijo Yahoo.
ARG_TICKERS_MERVAL: list[str] = [
    "ALUA",
    "BBAR",
    "BMA",
    "BYMA",
    "CEPU",
    "COME",
    "CRES",
    "EDN",
    "GGAL",
    "IRSA",
    "LOMA",
    "METR",
    "MIRG",
    "PAMP",
    "SUPV",
    "TECO2",
    "TGNO4",
    "TGSU2",
    "TRAN",
    "TXAR",
    "VALO",
    "YPFD",
]

# Extras actuales (se conservan para no romper lo existente).
ARG_TICKERS_MERVAL_EXTRA: list[str] = [
    "AGRO",
    "AUSO",
    "SEMI",
    "INVJ",
    "SAMI",
    "RICH",
    "DOME",
    "OEST",
    "BIOX",
    "INTR",
    "MORI",
    "POLL",
]

ARG_TICKERS_PANEL_GENERAL: list[str] = [
    "CVH",
    "HARG",
    "CGPA2",
    "DGCU2",
    "FERR",
    "GARO",
]


def _norm_local(sym: str) -> str:
    return (sym or "").strip().upper()


def _yahoo_from_local(local_ticker: str) -> str:
    s = _norm_local(local_ticker)
    if not s:
        return ""
    if s.endswith(YAHOO_ARG_SUFFIX):
        return s
    return f"{s}{YAHOO_ARG_SUFFIX}"


def _build_universe() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    merval_set = {_norm_local(t) for t in ARG_TICKERS_MERVAL if _norm_local(t)}

    def add(local_ticker: str) -> None:
        lt = _norm_local(local_ticker)
        if not lt:
            return
        if lt in seen:
            return
        seen.add(lt)
        if lt in merval_set:
            panel = "Merval"
            mercado = "Merval"
        else:
            panel = "Panel General"
            mercado = "General"
        out.append(
            {
                "ticker": _yahoo_from_local(lt),
                "local_ticker": lt,
                "panel": panel,
                "mercado": (mercado or "").strip() or panel,
            }
        )

    # Universo principal (Merval): estos tickers deben ser los únicos clasificados como Merval.
    for t in ARG_TICKERS_MERVAL:
        add(t)
    for t in ARG_TICKERS_MERVAL_EXTRA:
        add(t)

    # Panel General (extras)
    for t in ARG_TICKERS_PANEL_GENERAL:
        add(t)

    return out


ARGENTINA_UNIVERSE = _build_universe()
