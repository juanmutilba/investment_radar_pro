from __future__ import annotations

import re
import warnings
from datetime import datetime
from html import unescape
from typing import Any

import requests

from services.options.models import OptionContract
from services.options.normalizer import (
    normalize_option_type,
    normalize_strike,
    normalize_symbol,
    normalize_underlying,
)

ALLARIA_OPCION_URL = "https://allaria.com.ar/Opcion"

# Parámetro de filtro (--underlying) → ticker "Subyacente" tal como aparece en la tabla Allaria.
_UNDERLYING_PARAM_TO_TABLE: dict[str, str] = {
    "GFG": "GGAL",
    "GGAL": "GGAL",
    "ALU": "ALUA",
    "ALUA": "ALUA",
    "TXA": "TXAR",
    "TXAR": "TXAR",
    "TRA": "TRAN",
    "TRAN": "TRAN",
    "PAM": "PAMP",
    "PAMP": "PAMP",
    "YPF": "YPFD",
    "YPFD": "YPFD",
    "COM": "COME",
    "COME": "COME",
    "BYM": "BYMA",
    "BYMA": "BYMA",
}


def _log(msg: str) -> None:
    print(f"[OPTIONS_ALLARIA] {msg}", flush=True)


def _normalize_allaria_strike_for_underlying(underlying: str, strike: float | None) -> float | None:
    """
    Escala strikes Allaria al espacio de cotización esperado por fuente (sin tocar normalizer global).
    GFG/GGAL: si el strike viene en escala "x10" (>= 20000), dividir por 10 para alinearlo a Matriz/Rava.
    """
    if strike is None:
        return None
    try:
        x = float(strike)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    u = normalize_underlying(underlying) or (underlying or "").strip().upper()
    if u == "GFG" and x >= 20000.0:
        return round(x / 10.0, 4)
    return round(x, 4)


def _fetch_opcion_html() -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        )
    }
    r = requests.get(ALLARIA_OPCION_URL, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text or ""


def _strip_tags(s: str) -> str:
    t = re.sub(r"<[^>]+>", " ", s or "")
    t = unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _td_by_label(tr_html: str, label: str) -> str:
    pat = rf"""<td[^>]+(?:data-label|datal-label)=["']{re.escape(label)}["'][^>]*>(?P<body>.*?)</td>"""
    m = re.search(pat, tr_html, flags=re.I | re.S)
    return _strip_tags(m.group("body")) if m else ""


def _parse_allaria_expiry_display(raw: str) -> str | None:
    """Convierte fecha tipo 19/6/2026 a YYYY-MM-DD; si no es clara, None."""
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.isoformat()
        except ValueError:
            continue
    return None


def _parse_priceish(raw: str) -> float | None:
    """Campo numérico Allaria (puede mezclar variación con %)."""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if "%" in s:
        tail = s.split("%")[-1].strip()
        v = normalize_strike(tail)
        if v is not None:
            return v
    return normalize_strike(s)


def _extract_table_rows(html: str) -> list[dict[str, str]]:
    """
    Misma estrategia que scripts/debug_allaria_options.py::_extract_rows_from_html_tr:
    filas <tr> con link /Opcion/Especie/ y celdas data-label.
    """
    rows: list[dict[str, str]] = []
    for m in re.finditer(r"<tr\b[^>]*>(?P<body>.*?)</tr>", html, flags=re.I | re.S):
        tr = m.group("body") or ""
        if "/Opcion/Especie/" not in tr and "/opcion/especie/" not in tr.lower():
            continue

        m2 = re.search(r"""href=["']/Opcion/Especie/(?P<s>[A-Z0-9.]+)["']""", tr, flags=re.I)
        if not m2:
            continue
        especie = (m2.group("s") or "").strip().upper()
        if not especie:
            continue

        sub = _td_by_label(tr, "Subyacente").upper()
        tipo = _td_by_label(tr, "Tipo")
        vto = _td_by_label(tr, "Vencimiento")
        strike = _td_by_label(tr, "Precio ejercicio")
        ultimo = _td_by_label(tr, "Último precio (prima)") or _td_by_label(tr, "Ultimo precio (prima)")
        if not ultimo:
            # HTML a veces usa label sin tilde en data-label
            ultimo = _td_by_label(tr, "ltimo precio (prima)")
        compra = _td_by_label(tr, "Precio compra")
        venta = _td_by_label(tr, "Precio venta")
        vol = _td_by_label(tr, "Volumen (lotes)")
        hora = _td_by_label(tr, "Hora")

        if not sub or not tipo or not vto:
            continue

        rows.append(
            {
                "subyacente": sub.strip(),
                "especie": especie,
                "tipo": tipo.strip(),
                "vencimiento": vto.strip(),
                "precio_ejercicio": strike.strip(),
                "ultimo": ultimo.strip(),
                "precio_compra": compra.strip(),
                "precio_venta": venta.strip(),
                "volumen_lotes": vol.strip(),
                "hora": hora.strip(),
            }
        )
    return rows


def _table_ticker_for_param(underlying: str) -> str:
    u = (underlying or "").strip().upper()
    return _UNDERLYING_PARAM_TO_TABLE.get(u, u)


def fetch_allaria_option_contracts(underlying: str) -> list[OptionContract]:
    """
    Descarga https://allaria.com.ar/Opcion y devuelve contratos cuyo subyacente (columna tabla)
    coincide con el ticker esperado en Allaria (p. ej. GGAL o alias GFG).

    No inventa expiry/strike/option_type: si no se pueden derivar con claridad, quedan None.
    """
    want = _table_ticker_for_param(underlying)
    _log(f"fetch start underlying_param={underlying!r} table_ticker={want!r} url={ALLARIA_OPCION_URL}")
    scale_u = normalize_underlying(underlying) or (underlying or "").strip().upper()
    if scale_u == "GFG":
        _log("strike_scale underlying='GFG' factor='conditional_/10_if_>=20000'")

    html = _fetch_opcion_html()
    raw_rows = _extract_table_rows(html)
    _log(f"parsed_html_rows_total={len(raw_rows)}")

    out: list[OptionContract] = []
    for row in raw_rows:
        if (row.get("subyacente") or "").strip().upper() != want:
            continue

        sym = normalize_symbol(row.get("especie"))
        if not sym:
            warnings.warn(f"[OPTIONS_ALLARIA] fila sin especie válida: {row!r}", UserWarning, stacklevel=2)
            continue

        sub_norm = normalize_underlying(row.get("subyacente")) or (row.get("subyacente") or "").strip().upper()
        expiry = _parse_allaria_expiry_display(row.get("vencimiento") or "")
        if expiry is None and (row.get("vencimiento") or "").strip():
            warnings.warn(
                f"[OPTIONS_ALLARIA] vencimiento no parseado especie={sym!r} raw={row.get('vencimiento')!r}",
                UserWarning,
                stacklevel=2,
            )

        ot_raw = row.get("tipo")
        option_type = normalize_option_type(ot_raw)
        if option_type is None and (ot_raw or "").strip():
            warnings.warn(
                f"[OPTIONS_ALLARIA] tipo no reconocido especie={sym!r} raw={ot_raw!r}",
                UserWarning,
                stacklevel=2,
            )

        strike = normalize_strike(row.get("precio_ejercicio"))
        if strike is None and (row.get("precio_ejercicio") or "").strip():
            warnings.warn(
                f"[OPTIONS_ALLARIA] strike no parseado especie={sym!r} raw={row.get('precio_ejercicio')!r}",
                UserWarning,
                stacklevel=2,
            )

        strike_adj = _normalize_allaria_strike_for_underlying(underlying, strike)
        strike_factor = (
            0.1
            if scale_u == "GFG" and strike is not None and float(strike) >= 20000.0
            else 1.0
        )

        bid = _parse_priceish(row.get("precio_compra") or "")
        ask = _parse_priceish(row.get("precio_venta") or "")
        last = _parse_priceish(row.get("ultimo") or "")
        volume = normalize_strike(row.get("volumen_lotes"))

        raw_debug = dict(row)
        raw_debug["_allaria_url"] = ALLARIA_OPCION_URL
        if strike is not None:
            raw_debug["allaria_strike_original"] = float(strike)
        raw_debug["allaria_strike_factor"] = strike_factor

        out.append(
            OptionContract(
                underlying=sub_norm,
                expiry=expiry,
                strike=strike_adj,
                option_type=option_type,
                symbol=sym,
                bid=bid,
                ask=ask,
                last=last,
                volume=volume,
                open_interest=None,
                source="allaria",
                raw=raw_debug,
            )
        )

    _log(f"contracts_for_table_ticker={want!r} count={len(out)}")
    if not out:
        warnings.warn(
            f"[OPTIONS_ALLARIA] sin contratos para {want!r} (¿ticker o página vacía?)",
            UserWarning,
            stacklevel=2,
        )

    return out
