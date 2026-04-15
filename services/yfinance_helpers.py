from __future__ import annotations

import math
import concurrent.futures
from typing import Any, Callable


def try_apply_fast_info_price(
    asset: Any,
    technicals: dict,
    format_number: Callable[[Any], float | None],
) -> bool:
    """
    Si fast_info trae last_price, reemplaza technicals['Precio'].
    Los indicadores (RSI, MACD, etc.) siguen basados en el cierre del history.
    Retorna True si se usó fast_info para el precio mostrado.
    """
    try:
        fi = getattr(asset, "fast_info", None)
        fast_price = None
        if isinstance(fi, dict):
            fast_price = fi.get("last_price") or fi.get("lastPrice") or fi.get("regularMarketPrice")
        if fast_price is None and fi is not None:
            try:
                fast_price = fi["last_price"]  # type: ignore[index]
            except Exception:
                fast_price = None
        fp = format_number(fast_price)
        if fp is not None and fp > 0:
            technicals["Precio"] = round(fp, 2)
            return True
    except Exception:
        pass
    return False


def fetch_info_with_timeout(asset: Any, *, timeout_s: float) -> dict[str, Any]:
    """
    Lee asset.info con timeout para evitar que un ticker congele el engine.
    Mantiene semántica: si falla/timeout, se propaga excepción para que el ticker cuente como FAIL.
    """
    def _read() -> dict[str, Any]:
        info = asset.info
        return info if isinstance(info, dict) else {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_read)
        return fut.result(timeout=timeout_s)


def precio_valido(p: object) -> bool:
    if p is None:
        return False
    try:
        x = float(p)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if math.isnan(x) or math.isinf(x):
        return False
    return x > 0
