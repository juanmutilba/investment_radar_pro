from __future__ import annotations

from datetime import date, datetime

_MONTH_BY_CODE: dict[str, int] = {
    "EN": 1,
    "FE": 2,
    "MR": 3,
    "AB": 4,
    "MY": 5,
    "JU": 6,
    "JL": 7,
    "AG": 8,
    "SE": 9,
    "OC": 10,
    "NO": 11,
    "DI": 12,
}

# Los sufijos de 1 letra NO se asumen como meses A–L.
# En Rava/BYMA parecen codificar serie/año además del mes.
# Para evitar vencimientos falsos, solo cargamos casos confirmados contra fuentes externas/mercado.
_SINGLE_LETTER_EXPIRY: dict[str, tuple[int, int]] = {
    # Confirmado (Allaria): GFGC10126A vence 16/4/2027 → tercer viernes de abril 2027.
    "A": (2027, 4),
    # Confirmado (Allaria): varios GFG...J vencen 19/6/2026 → tercer viernes de junio 2026.
    "J": (2026, 6),
}


def _resolve_single_letter(code: str) -> date | None:
    ym = _SINGLE_LETTER_EXPIRY.get(code)
    if ym is None:
        return None
    y, m = ym
    return _third_friday(y, m)


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    # Lunes=0 … Viernes=4
    offset = (4 - first.weekday()) % 7
    first_friday = date(year, month, 1 + offset)
    return date(year, month, first_friday.day + 14)


def resolve_expiry_date(expiry_code_raw: str) -> date | None:
    """
    Convierte código de vencimiento Rava (1 o 2 letras, mes) en fecha de vencimiento:
    tercer viernes de ese mes. Si ese día ya pasó respecto a hoy, usa el mismo mes
    del año siguiente.
    """
    code = (expiry_code_raw or "").strip().upper()
    today = date.today()

    if not code:
        print("[RAVA_EXPIRY] code= resolved_date=None fallback=None", flush=True)
        return None

    # 1 letra: solo casos confirmados (año+mes explícitos)
    if len(code) == 1:
        exp_single = _resolve_single_letter(code)
        if exp_single is None:
            print(f"[RAVA_EXPIRY] code={code!r} resolved_date=None fallback=unsupported_code", flush=True)
            return None
        print(
            f"[RAVA_EXPIRY] code={code!r} resolved_date={exp_single.isoformat()} fallback=single_letter_map",
            flush=True,
        )
        return exp_single

    month = _MONTH_BY_CODE.get(code)
    if month is None:
        print(f"[RAVA_EXPIRY] code={code!r} resolved_date=None fallback=unsupported_code", flush=True)
        return None

    year = datetime.now().year
    exp = _third_friday(year, month)
    if exp < today:
        exp = _third_friday(year + 1, month)

    print(f"[RAVA_EXPIRY] code={code!r} resolved_date={exp.isoformat()} fallback=None", flush=True)
    return exp
