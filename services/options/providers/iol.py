"""
Opciones BYMA vía IOL (aislado; no integrado al merge Allaria+Rava).

Requiere credenciales en memoria (`configure_iol_credentials`) como el resto del proyecto.
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime
from typing import Any

from services.market_data.providers.iol import IolOptionsRawError, get_iol_options_raw, is_iol_enabled
from services.options.models import OptionContract
from services.options.normalizer import normalize_option_type, normalize_strike, normalize_underlying
from services.options.spot_mapping import option_underlying_to_spot_symbol


def _log(msg: str) -> None:
    print(f"[OPTIONS_IOL] {msg}", flush=True)


def _pick_first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] is not None and str(d[k]).strip() != "":
            return d[k]
    return None


def _flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    """Une subdicts (`cotizacion`, `titulo`, …). No copia ``puntas`` al flat (bid/ask vía ``_bid_ask_from_row``)."""
    out = dict(row)
    for nest in ("cotizacion", "Cotizacion", "titulo", "Titulo", "opcion", "Opcion", "instrumento", "Instrumento"):
        sub = row.get(nest)
        if isinstance(sub, dict):
            for k, v in sub.items():
                if k == "puntas":
                    continue
                out.setdefault(k, v)
    return out


def _parse_strike_locale_token(s: str) -> float | None:
    """
    IOL en `descripcion` usa miles con coma y decimales con punto (ej. 4,255.30).
    `normalize_strike` asume otro patrón si hay ambos separadores; acá forzamos ese caso.
    """
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{1,3}(?:,\d{3})+)(?:\.(\d+))?$", s)
    if m:
        whole = m.group(1).replace(",", "")
        frac = m.group(2)
        return normalize_strike(f"{whole}.{frac}" if frac is not None else whole)
    return normalize_strike(s)


def _strike_from_descripcion(desc: str | None) -> float | None:
    """Ej.: 'Call GGAL 4,255.30 Vencimiento: 19/06/2026' → strike 4255.3."""
    if not desc or not str(desc).strip():
        return None
    m = re.search(r"(\d[\d.,]*)\s+Vencimiento", str(desc), flags=re.IGNORECASE)
    if not m:
        return None
    return _parse_strike_locale_token(m.group(1))


def _str_symbol(flat: dict[str, Any]) -> str | None:
    v = _pick_first(flat, ("simbolo", "Simbolo", "ticker", "Ticker", "symbol", "Symbol", "codneg", "CodNeg"))
    if v is None:
        return None
    s = str(v).strip().upper().replace(" ", "")
    return s or None


def _parse_expiry(flat: dict[str, Any]) -> str | None:
    v = _pick_first(
        flat,
        (
            "fechaVencimiento",
            "fechaVencimientoLlamado",
            "vencimiento",
            "Vencimiento",
            "expiration",
            "fechaVenc",
            "fechaVto",
        ),
    )
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return s[:10] if len(s) >= 10 else None


def _parse_option_type(flat: dict[str, Any]) -> str | None:
    v = _pick_first(
        flat,
        (
            "tipoOpcion",
            "TipoOpcion",
            "tipo",
            "Tipo",
            "putCall",
            "PutCall",
            "clase",
            "Clase",
            "optionType",
        ),
    )
    if v is None:
        return None
    s = str(v).strip().upper()
    ot = normalize_option_type(s)
    if ot:
        return ot
    if "CALL" in s or s in ("C", "COMPRA"):
        return "CALL"
    if "PUT" in s or s in ("P", "V", "VENTA"):
        return "PUT"
    if s in ("1", "CALL"):
        return "CALL"
    if s in ("2", "PUT"):
        return "PUT"
    return None


def _parse_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        return x if x == x and x >= 0 else None
    return normalize_strike(v)


def _float_gt_zero(v: Any) -> float | None:
    x = _parse_float(v)
    if x is None or x <= 0:
        return None
    return x


def _collect_puntas_lists(row: dict[str, Any]) -> list[list[dict[str, Any]]]:
    out: list[list[dict[str, Any]]] = []
    for nest in ("cotizacion", "Cotizacion"):
        sub = row.get(nest)
        if not isinstance(sub, dict):
            continue
        puntas = sub.get("puntas")
        if isinstance(puntas, list) and puntas:
            dicts = [x for x in puntas if isinstance(x, dict)]
            if dicts:
                out.append(dicts)
    return out


def _bid_ask_from_puntas_list(puntas: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    keys_bid = ("precioCompra", "PrecioCompra", "precioCompraD", "pCompra", "compra", "Compra")
    keys_ask = ("precioVenta", "PrecioVenta", "precioVentaD", "pVenta", "venta", "Venta")
    if not puntas:
        return None, None
    p0 = puntas[0]
    b0 = _float_gt_zero(_pick_first(p0, keys_bid))
    a0 = _float_gt_zero(_pick_first(p0, keys_ask))
    if b0 is not None and a0 is not None:
        return b0, a0
    bids: list[float] = []
    asks: list[float] = []
    for p in puntas:
        b = _float_gt_zero(_pick_first(p, keys_bid))
        a = _float_gt_zero(_pick_first(p, keys_ask))
        if b is not None:
            bids.append(b)
        if a is not None:
            asks.append(a)
    bid = max(bids) if bids else None
    ask = min(asks) if asks else None
    return bid, ask


def _bid_ask_from_row(row: dict[str, Any], flat: dict[str, Any]) -> tuple[float | None, float | None, int]:
    """
    Bid/ask: todas las ``puntas`` > campos directos en ``cotizacion`` > top-level en ``flat``.
    No usa 0 como valor útil.
    """
    keys_bid = ("precioCompra", "PrecioCompra", "precioCompraD", "bid", "Bid", "pCompra")
    keys_ask = ("precioVenta", "PrecioVenta", "precioVentaD", "ask", "Ask", "pVenta")
    puntas_total = 0
    best_bid: float | None = None
    best_ask: float | None = None

    for plist in _collect_puntas_lists(row):
        puntas_total += len(plist)
        b, a = _bid_ask_from_puntas_list(plist)
        if b is not None:
            best_bid = b if best_bid is None else max(best_bid, b)
        if a is not None:
            best_ask = a if best_ask is None else min(best_ask, a)

    if best_bid is None or best_ask is None:
        for nest in ("cotizacion", "Cotizacion"):
            sub = row.get(nest)
            if not isinstance(sub, dict):
                continue
            if best_bid is None:
                best_bid = _float_gt_zero(_pick_first(sub, keys_bid)) or best_bid
            if best_ask is None:
                best_ask = _float_gt_zero(_pick_first(sub, keys_ask)) or best_ask

    if best_bid is None:
        best_bid = _float_gt_zero(_pick_first(flat, keys_bid))
    if best_ask is None:
        best_ask = _float_gt_zero(_pick_first(flat, keys_ask))

    return best_bid, best_ask, puntas_total


def _log_quote_line(
    symbol: str,
    raw_bid: Any,
    raw_ask: Any,
    parsed_bid: float | None,
    parsed_ask: float | None,
    puntas_len: int,
) -> None:
    print(
        "[OPTIONS_IOL_QUOTE] symbol=%s raw_bid=%r raw_ask=%r parsed_bid=%r parsed_ask=%r puntas_len=%s"
        % (symbol, raw_bid, raw_ask, parsed_bid, parsed_ask, puntas_len),
        flush=True,
    )


def _row_to_contract(chain_underlying: str, row: dict[str, Any]) -> OptionContract | None:
    flat = _flatten_row(row)
    sym = _str_symbol(flat)
    if not sym:
        return None
    strike = _parse_float(
        _pick_first(flat, ("strike", "Strike", "precioEjercicio", "PrecioEjercicio", "precioEjer", "ejercicio")),
    )
    if strike is None:
        strike = _strike_from_descripcion(_pick_first(flat, ("descripcion", "Descripcion", "descripcionTitulo")))

    expiry = _parse_expiry(flat)
    ot = _parse_option_type(flat)
    bid, ask, puntas_len = _bid_ask_from_row(row, flat)
    keys_bid_top = ("precioCompra", "PrecioCompra", "precioCompraD", "bid", "Bid", "pCompra")
    keys_ask_top = ("precioVenta", "PrecioVenta", "precioVentaD", "ask", "Ask", "pVenta")
    raw_bid = _pick_first(flat, keys_bid_top)
    raw_ask = _pick_first(flat, keys_ask_top)
    if os.environ.get("OPTIONS_IOL_QUOTE_VERBOSE", "").strip().lower() in ("1", "true", "yes", "on"):
        _log_quote_line(sym, raw_bid, raw_ask, bid, ask, puntas_len)

    last = _parse_float(
        _pick_first(flat, ("ultimoPrecio", "UltimoPrecio", "ultimo", "Ultimo", "last", "Last", "cierre", "Cierre")),
    )
    vol = _parse_float(
        _pick_first(
            flat,
            (
                "volumenNominal",
                "VolumenNominal",
                "volumen",
                "Volumen",
                "volume",
                "Volume",
                "cantidadOperaciones",
                "operado",
                "Operado",
            ),
        ),
    )
    oi = _parse_float(
        _pick_first(flat, ("interesesAbiertos", "InteresesAbiertos", "openInterest", "OpenInterest", "interesAbierto"))
    )

    u_norm = normalize_underlying(chain_underlying) or chain_underlying.strip().upper()

    return OptionContract(
        underlying=u_norm,
        expiry=expiry,
        strike=strike,
        option_type=ot,
        symbol=sym,
        bid=bid,
        ask=ask,
        last=last,
        volume=vol,
        open_interest=oi,
        source="iol",
        raw=deepcopy(row) if isinstance(row, dict) else {"value": row},
    )


def _unwrap_options_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        for k in ("items", "titulos", "opciones", "data", "result", "Results"):
            v = raw.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def fetch_iol_option_contracts(underlying: str) -> list[OptionContract]:
    """
    Descarga la cadena de opciones del subyacente vía IOL (GET .../Opciones v2).

    ``underlying`` puede ser GGAL, GFG, YPFD, ALU, etc.; se normaliza al ticker BCBA
    que IOL suele esperar (p. ej. GFG -> GGAL) antes de llamar a la API.
    """
    if not is_iol_enabled():
        _log("disabled reason=missing_credentials underlying=%r" % (underlying,))
        return []

    spot = option_underlying_to_spot_symbol(underlying.strip() or None)
    if not spot:
        _log("skip empty underlying=%r" % (underlying,))
        return []

    try:
        raw = get_iol_options_raw(spot)
    except IolOptionsRawError as e:
        _log(
            "error underlying=%r spot=%r http=%s iol401=%s detail=%r"
            % (underlying, spot, e.status_code, getattr(e, "iol_resource_401", False), (e.detail or "")[:200])
        )
        return []
    except Exception as ex:
        _log("error underlying=%r spot=%r ex=%s" % (underlying, spot, ex))
        return []

    rows = _unwrap_options_list(raw)
    if not rows and raw is not None:
        preview = ""
        try:
            preview = json.dumps(raw, ensure_ascii=False, default=str)[:400]
        except TypeError:
            preview = str(raw)[:400]
        _log("unwrap_empty underlying=%r spot=%r raw_preview=%r" % (underlying, spot, preview))

    out: list[OptionContract] = []
    for row in rows:
        c = _row_to_contract(underlying, row)
        if c is not None:
            out.append(c)

    _log("ok underlying=%r spot=%r rows=%s contracts=%s" % (underlying, spot, len(rows), len(out)))
    if rows and out and rows[0]:
        flat0 = _flatten_row(rows[0])
        _log("sample_keys=%s" % (list(flat0.keys())[:40],))

    n_tot = len(out)
    bid_gt0 = sum(1 for c in out if c.bid is not None and c.bid > 0)
    ask_gt0 = sum(1 for c in out if c.ask is not None and c.ask > 0)
    both_gt0 = sum(1 for c in out if (c.bid or 0) > 0 and (c.ask or 0) > 0)
    print(
        "[OPTIONS_IOL_QUOTE] summary underlying=%r contracts=%s bid_gt0=%s ask_gt0=%s both_gt0=%s "
        "(per-row: set OPTIONS_IOL_QUOTE_VERBOSE=1)"
        % (underlying, n_tot, bid_gt0, ask_gt0, both_gt0),
        flush=True,
    )
    keys_bid_top = ("precioCompra", "PrecioCompra", "precioCompraD", "bid", "Bid", "pCompra")
    keys_ask_top = ("precioVenta", "PrecioVenta", "precioVentaD", "ask", "Ask", "pVenta")
    shown = 0
    for c in out:
        if shown >= 5:
            break
        if (c.bid or 0) > 0 or (c.ask or 0) > 0:
            rw = c.raw if isinstance(c.raw, dict) else {}
            fl = _flatten_row(rw)
            _, _, plen = _bid_ask_from_row(rw, fl)
            _log_quote_line(
                c.symbol or "?",
                _pick_first(fl, keys_bid_top),
                _pick_first(fl, keys_ask_top),
                c.bid,
                c.ask,
                plen,
            )
            shown += 1

    return out
