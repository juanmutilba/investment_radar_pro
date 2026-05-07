from __future__ import annotations

"""
Diagnóstico: Allaria como fuente alternativa/complementaria de opciones argentinas.

Fuente:
  https://allaria.com.ar/Opcion

Objetivo:
- Detectar si la data viene en HTML (tabla), JSON embebido o endpoint interno.
- Extraer filas con columnas clave si es posible.
- Comparar conteos contra Rava (prices/arg) por subyacente.

Restricciones:
- Sin dependencias nuevas (usa requests + stdlib).
- No toca frontend ni reemplaza Rava.
"""

import json
import re
import sys
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.options.rava_chain_builder import _parse_option_symbol  # noqa: E402
from services.options.expiry_utils import resolve_expiry_date  # noqa: E402


ALLARIA_URL = "https://allaria.com.ar/Opcion"
RAVA_URL = "https://mercado.rava.com/api/prices/arg"

# Comparación pedida (Radar/Acción) -> prefijo opciones (Rava/Allaria)
COMPARE = [
    ("GGAL", "GFG"),
    ("ALUA", "ALU"),
    ("TXAR", "TXA"),
    ("TRAN", "TRA"),
    ("PAMP", "PAM"),
    ("YPFD", "YPF"),
]


@dataclass(frozen=True)
class AllariaRow:
    subyacente: str
    especie: str
    tipo: str
    vencimiento: str
    strike_raw: str
    ultimo_raw: str
    compra_raw: str
    venta_raw: str
    volumen_lotes_raw: str
    hora: str


@dataclass(frozen=True)
class OptionPoint:
    symbol: str
    underlying_prefix: str
    option_type: str  # C / V
    expiry_code_raw: str
    expiry_key: str  # YYYY-MM-DD or "code:<X>" when unknown
    strike: float | None


def _fetch_text(url: str) -> tuple[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        )
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    ct = str(r.headers.get("content-type") or "")
    return r.text or "", ct


def _fetch_allaria_especie(especie: str) -> tuple[str, str]:
    s = (especie or "").strip().upper()
    if not s:
        raise ValueError("especie vacía")
    url = f"https://allaria.com.ar/Opcion/Especie/{s}"
    return _fetch_text(url)


def _detect_internal_endpoints(html: str) -> list[str]:
    """
    Heurística: buscar URLs típicas dentro de scripts/atributos.
    Importante: esta página contiene miles de links /Opcion/Especie/... (no es "API").
    Por performance, devolvemos una muestra acotada y priorizamos patrones "api/js/json".
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(u: str) -> None:
        if not u or u in seen:
            return
        seen.add(u)
        candidates.append(u)

    # 1) URLs absolutas interesantes
    for m in re.finditer(r"""(?P<u>https?://[^\s"'<>]+)""", html, flags=re.IGNORECASE):
        u = m.group("u")
        ul = u.lower()
        if "allaria.com.ar" not in ul:
            continue
        if any(x in ul for x in ("/api", ".json", ".js", "graphql")):
            _add(u)
        elif "/opcion" in ul and "/especie/" not in ul:
            _add(u)
        if len(candidates) >= 80:
            break

    # 2) Paths relativos interesantes
    for m in re.finditer(r"""(?P<u>/(?:api|Api)[^\s"'<>]+)""", html):
        _add("https://allaria.com.ar" + m.group("u"))
        if len(candidates) >= 120:
            break

    # 3) Cualquier otro path /Opcion... que NO sea /Opcion/Especie/...
    for m in re.finditer(r"""(?P<u>/(?:OPCION|Opcion|opcion)[^\s"'<>]+)""", html):
        u = m.group("u")
        if "/Opcion/Especie/" in u or "/opcion/especie/" in u.lower():
            continue
        _add("https://allaria.com.ar" + u)
        if len(candidates) >= 160:
            break

    return sorted(candidates)[:160]


def _extract_embedded_json_blobs(html: str) -> list[dict[str, Any]]:
    blobs: list[dict[str, Any]] = []
    # application/json script tags (común en SSR frameworks)
    for m in re.finditer(r"""<script[^>]+type=["']application/json["'][^>]*>(?P<body>.*?)</script>""", html, flags=re.I | re.S):
        body = (m.group("body") or "").strip()
        if not body:
            continue
        if len(body) > 10_000_000:
            continue
        try:
            obj = json.loads(body)
        except Exception:
            continue
        if isinstance(obj, dict):
            blobs.append(obj)
    # Next.js style
    m = re.search(r"""<script[^>]+id=["']__NEXT_DATA__["'][^>]*>(?P<body>.*?)</script>""", html, flags=re.I | re.S)
    if m:
        body = (m.group("body") or "").strip()
        try:
            obj = json.loads(body)
            if isinstance(obj, dict):
                blobs.append(obj)
        except Exception:
            pass
    return blobs


class _AllariaTableParser(HTMLParser):
    """
    Extrae la primera tabla que parezca ser la de opciones (contiene columna 'Subyacente' y 'Especie').
    Sin dependencias externas, solo stdlib.
    """

    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.seen_candidate_header = False
        self.in_tr = False
        self.in_cell = False
        self._cell_buf: list[str] = []
        self._row: list[str] = []
        self.header: list[str] = []
        self.rows: list[list[str]] = []

        self._table_depth = 0
        self._cell_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t == "table":
            self._table_depth += 1
            if not self.in_table:
                self.in_table = True
                self.seen_candidate_header = False
                self.header = []
                self.rows = []
        if not self.in_table:
            return
        if t == "tr":
            self.in_tr = True
            self._row = []
        if t in ("td", "th"):
            self.in_cell = True
            self._cell_tag = t
            self._cell_buf = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "table":
            if self._table_depth > 0:
                self._table_depth -= 1
            # Cerrar tabla: si ya capturamos una tabla válida, detener
            if self.in_table and self.seen_candidate_header and self.header and self.rows:
                self.in_table = False
                return
            if self._table_depth == 0:
                self.in_table = False
            return
        if not self.in_table:
            return
        if t in ("td", "th") and self.in_cell:
            txt = unescape("".join(self._cell_buf)).strip()
            txt = re.sub(r"\s+", " ", txt)
            self._row.append(txt)
            self.in_cell = False
            self._cell_tag = None
            self._cell_buf = []
            return
        if t == "tr" and self.in_tr:
            self.in_tr = False
            if not self._row:
                return
            # Detectar header: fila que contiene varias columnas esperadas.
            row_join = " | ".join(self._row).lower()
            expected = ("subyacente", "especie", "tipo", "vencimiento", "precio ejercicio", "último", "ultimo", "compra", "venta", "volumen", "hora")
            hits = sum(1 for k in expected if k in row_join)
            if hits >= 4 and not self.header:
                self.header = self._row
                self.seen_candidate_header = True
                return
            # Solo agregar filas si ya vimos header candidato y coincide largo
            if self.seen_candidate_header and self.header and len(self._row) == len(self.header):
                # Evitar repetir el header
                if [c.lower() for c in self._row] == [c.lower() for c in self.header]:
                    return
                self.rows.append(self._row)
            return

    def handle_data(self, data: str) -> None:
        if self.in_table and self.in_cell:
            self._cell_buf.append(data)


def _parse_markdown_table(text: str) -> tuple[list[str], list[list[str]]]:
    """
    El fetch de Cursor suele convertir HTML -> Markdown.
    Aprovechamos: buscar una tabla markdown:
      | Col1 | Col2 | ... |
      | --- | --- | ... |
      | ... |
    """
    lines = [ln.rstrip("\n") for ln in (text or "").splitlines()]
    # Encontrar header
    header_idx = -1
    for i, ln in enumerate(lines):
        if ln.strip().startswith("|") and "Subyacente" in ln and "Especie" in ln and "Vencimiento" in ln:
            header_idx = i
            break
    if header_idx < 0 or header_idx + 2 >= len(lines):
        return [], []
    header = [c.strip() for c in lines[header_idx].strip().strip("|").split("|")]
    # separador markdown (| --- |)
    sep = lines[header_idx + 1].strip()
    if "---" not in sep:
        return [], []

    rows: list[list[str]] = []
    for ln in lines[header_idx + 2 :]:
        if not ln.strip().startswith("|"):
            # fin de tabla
            if rows:
                break
            continue
        cols = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cols) != len(header):
            continue
        rows.append(cols)
    return header, rows


def _strip_tags(s: str) -> str:
    t = re.sub(r"<[^>]+>", " ", s or "")
    t = unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _parse_float_locale(v: str) -> float | None:
    s = (v or "").strip()
    if not s:
        return None
    # Allaria usa formato es-AR (miles con ., decimal con ,)
    # También aparecen valores como "640.00" (decimal punto).
    s = s.replace("\xa0", " ")
    s = s.replace(".", "").replace(",", ".") if ("," in s and "." in s) else s.replace(",", ".")
    s = s.strip()
    try:
        x = float(s)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _expiry_key_from_code(code: str) -> str:
    c = (code or "").strip().upper()
    if not c:
        return "code:_"
    d = _EXPIRY_CACHE.get(c)
    if d is None and c not in _EXPIRY_CACHE:
        # resolve_expiry_date() loguea a stdout en este repo; evitar spam del script
        # al resolver cientos de veces. Cacheamos por código.
        try:
            import contextlib
            import io

            with contextlib.redirect_stdout(io.StringIO()):
                d2 = resolve_expiry_date(c)
        except Exception:
            d2 = None
        _EXPIRY_CACHE[c] = d2
        d = d2
    if d is None:
        return f"code:{c}"
    return d.isoformat()


_EXPIRY_CACHE: dict[str, Any] = {}


def _build_point_from_symbol(sym: str) -> OptionPoint | None:
    s = (sym or "").strip().upper()
    if not s:
        return None
    p = _parse_option_symbol(s)
    if p is None:
        return None
    und = (p.get("underlying_guess") or "").strip().upper()
    ot = (p.get("option_type") or "").strip().upper()
    code = (p.get("expiry_code_raw") or "").strip().upper()
    strike_raw = (p.get("strike_raw") or "").strip()
    strike = _parse_float_locale(strike_raw)
    return OptionPoint(
        symbol=s,
        underlying_prefix=und,
        option_type=ot,
        expiry_code_raw=code,
        expiry_key=_expiry_key_from_code(code),
        strike=strike,
    )


def _extract_rows_from_html_tr(html: str) -> tuple[list[str], list[AllariaRow]]:
    """
    Fallback: Allaria puede no renderizar un header con <th>. En ese caso,
    parseamos filas directamente desde <tr> y sus <td data-label="...">.
    """
    wanted_cols = [
        "Subyacente",
        "Especie",
        "Tipo",
        "Vencimiento",
        "Precio ejercicio",
        "Último precio (prima)",
        "Precio compra",
        "Precio venta",
        "Volumen (lotes)",
        "Hora",
    ]

    def td_by_label(tr_html: str, label: str) -> str:
        # a veces aparece data-label o datal-label (typo en HTML)
        pat = rf"""<td[^>]+(?:data-label|datal-label)=["']{re.escape(label)}["'][^>]*>(?P<body>.*?)</td>"""
        m = re.search(pat, tr_html, flags=re.I | re.S)
        return _strip_tags(m.group("body")) if m else ""

    out: list[AllariaRow] = []
    # Filtrar solo filas que contienen link a especie
    for m in re.finditer(r"<tr\b[^>]*>(?P<body>.*?)</tr>", html, flags=re.I | re.S):
        tr = m.group("body") or ""
        if "/Opcion/Especie/" not in tr and "/opcion/especie/" not in tr.lower():
            continue

        especie = ""
        m2 = re.search(r"""href=["']/Opcion/Especie/(?P<s>[A-Z0-9.]+)["']""", tr, flags=re.I)
        if m2:
            especie = (m2.group("s") or "").strip().upper()
        if not especie:
            continue

        sub = td_by_label(tr, "Subyacente").upper()
        tipo = td_by_label(tr, "Tipo")
        vto = td_by_label(tr, "Vencimiento")
        strike = td_by_label(tr, "Precio ejercicio")
        ultimo = td_by_label(tr, "Último precio (prima)") or td_by_label(tr, "Ultimo precio (prima)")
        compra = td_by_label(tr, "Precio compra")
        venta = td_by_label(tr, "Precio venta")
        vol = td_by_label(tr, "Volumen (lotes)")
        hora = td_by_label(tr, "Hora")

        # Evitar "subfilas" / filas incompletas (p. ej. layouts responsive)
        if not sub or not tipo or not vto:
            continue

        out.append(
            AllariaRow(
                subyacente=sub.strip(),
                especie=especie,
                tipo=tipo.strip(),
                vencimiento=vto.strip(),
                strike_raw=strike.strip(),
                ultimo_raw=ultimo.strip(),
                compra_raw=compra.strip(),
                venta_raw=venta.strip(),
                volumen_lotes_raw=vol.strip(),
                hora=hora.strip(),
            )
        )

    return wanted_cols, out


def _to_allaria_rows(header: list[str], rows: list[list[str]]) -> list[AllariaRow]:
    if not header or not rows:
        return []
    idx = {name.strip().lower(): i for i, name in enumerate(header)}

    def col(name: str, cols: list[str]) -> str:
        i = idx.get(name.lower())
        return cols[i] if i is not None and 0 <= i < len(cols) else ""

    out: list[AllariaRow] = []
    for cols in rows:
        sub = col("Subyacente", cols)
        esp = col("Especie", cols)
        tipo = col("Tipo", cols)
        vto = col("Vencimiento", cols)
        strike = col("Precio ejercicio", cols)
        ultimo = col("Último precio (prima)", cols) or col("Ultimo precio (prima)", cols)
        compra = col("Precio compra", cols)
        venta = col("Precio venta", cols)
        vol = col("Volumen (lotes)", cols)
        hora = col("Hora", cols)

        # La "Especie" viene como markdown link: [GFGC...](url)
        m = re.match(r"^\[(?P<s>[A-Z0-9.]+)\]\(", esp.strip())
        if m:
            esp_sym = m.group("s").strip()
        else:
            esp_sym = esp.strip()

        out.append(
            AllariaRow(
                subyacente=sub.strip().upper(),
                especie=esp_sym.strip().upper(),
                tipo=tipo.strip(),
                vencimiento=vto.strip(),
                strike_raw=strike.strip(),
                ultimo_raw=ultimo.strip(),
                compra_raw=compra.strip(),
                venta_raw=venta.strip(),
                volumen_lotes_raw=vol.strip(),
                hora=hora.strip(),
            )
        )
    return out


def _rava_opt_items() -> list[dict[str, Any]]:
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(RAVA_URL, headers=headers, timeout=30)
    r.raise_for_status()
    obj: Any = r.json()
    datos = obj.get("datos") if isinstance(obj, dict) else None
    if not isinstance(datos, list):
        return []
    out: list[dict[str, Any]] = []
    for it in datos:
        if not isinstance(it, dict):
            continue
        st = str(it.get("securitytype") or "").strip().upper()
        if st == "OPT":
            out.append(it)
            continue
        # Algunos instrumentos (ej. TRAC/TRAV) pueden venir con securitytype vacío.
        # Si el símbolo parsea como opción, incluirlo para la comparación.
        if not st:
            sym = _pick_symbol(it)
            if sym and _parse_option_symbol(sym) is not None:
                out.append(it)
    return out


def _pick_symbol(it: dict[str, Any]) -> str:
    for k in ("especie", "simbolo"):
        v = it.get(k)
        if v is None:
            continue
        s = str(v).strip().upper()
        if s:
            return s
    return ""


def _index_points(points: list[OptionPoint]) -> dict[str, dict[str, dict[str, set[float]]]]:
    """
    index[underlying_prefix][expiry_key][C|V] = {strikes}
    (solo strikes numéricos)
    """
    idx: dict[str, dict[str, dict[str, set[float]]]] = defaultdict(lambda: defaultdict(lambda: {"C": set(), "V": set()}))
    for p in points:
        if not p.underlying_prefix:
            continue
        if p.option_type not in ("C", "V"):
            continue
        if p.strike is None:
            continue
        idx[p.underlying_prefix][p.expiry_key][p.option_type].add(p.strike)
    return idx


def _summarize_underlying(
    points: list[OptionPoint],
    *,
    underlying_prefix: str,
    label: str,
    limit_exp: int = 12,
    limit_examples: int = 10,
) -> None:
    pts = [p for p in points if p.underlying_prefix == underlying_prefix]
    total = len(pts)
    calls = sum(1 for p in pts if p.option_type == "C")
    puts = sum(1 for p in pts if p.option_type == "V")
    by_exp = Counter(p.expiry_key for p in pts)

    # strikes por exp/tipo
    strikes_by_exp: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"C": [], "V": []})
    examples: list[str] = []
    seen = set()
    for p in pts:
        if p.symbol and p.symbol not in seen and len(examples) < limit_examples:
            examples.append(p.symbol)
            seen.add(p.symbol)
        if p.strike is None:
            continue
        if p.option_type in ("C", "V"):
            strikes_by_exp[p.expiry_key][p.option_type].append(p.strike)

    print(f"{label} {underlying_prefix}: total={total} calls={calls} puts={puts}")
    exps_sorted = [k for k, _ in sorted(by_exp.items(), key=lambda kv: (-kv[1], kv[0]))]
    print(f"  expiries_detected={len(exps_sorted)} top={[(k, by_exp[k]) for k in exps_sorted[:limit_exp]]}")
    for ek in sorted(exps_sorted)[:limit_exp]:
        c = strikes_by_exp[ek]["C"]
        v = strikes_by_exp[ek]["V"]
        cmin, cmax = (min(c), max(c)) if c else (None, None)
        vmin, vmax = (min(v), max(v)) if v else (None, None)
        print(
            f"  - {ek}: count={by_exp[ek]} "
            f"C_strikes={len(c)} range={cmin}-{cmax} "
            f"V_strikes={len(v)} range={vmin}-{vmax}"
        )
    print(f"  examples={examples}")


def _diff_underlying(
    *,
    allaria_points: list[OptionPoint],
    rava_points: list[OptionPoint],
    underlying_prefix: str,
) -> None:
    a_idx = _index_points([p for p in allaria_points if p.underlying_prefix == underlying_prefix])
    r_idx = _index_points([p for p in rava_points if p.underlying_prefix == underlying_prefix])

    a_exps = set(a_idx.get(underlying_prefix, {}).keys())
    r_exps = set(r_idx.get(underlying_prefix, {}).keys())

    only_a = sorted(a_exps - r_exps)
    only_r = sorted(r_exps - a_exps)
    both = sorted(a_exps & r_exps)

    print(f"[DIFF] {underlying_prefix}: expiries only_in_allaria={len(only_a)} only_in_rava={len(only_r)} both={len(both)}")
    if only_a:
        print(f"  only_in_allaria={only_a[:12]}")
    if only_r:
        print(f"  only_in_rava={only_r[:12]}")

    # strikes diff por expiry y tipo
    for ek in both[:10]:
        aC = a_idx[underlying_prefix][ek]["C"]
        aV = a_idx[underlying_prefix][ek]["V"]
        rC = r_idx[underlying_prefix][ek]["C"]
        rV = r_idx[underlying_prefix][ek]["V"]
        c_only_a = sorted(aC - rC)
        c_only_r = sorted(rC - aC)
        v_only_a = sorted(aV - rV)
        v_only_r = sorted(rV - aV)
        if c_only_a or c_only_r or v_only_a or v_only_r:
            print(f"  expiry={ek}:")
            if c_only_a:
                print(f"    CALL only_allaria={c_only_a[:12]}")
            if c_only_r:
                print(f"    CALL only_rava={c_only_r[:12]}")
            if v_only_a:
                print(f"    PUT  only_allaria={v_only_a[:12]}")
            if v_only_r:
                print(f"    PUT  only_rava={v_only_r[:12]}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Diagnóstico Allaria vs Rava (opciones).")
    ap.add_argument("--underlying", default="", help="Filtrar detalle por subyacente (ej: GGAL o prefijo opciones GFG)")
    ap.add_argument("--especie", default="", help="Descargar /Opcion/Especie/<ESPECIE> y mostrar indicios")
    args = ap.parse_args(argv)

    if args.especie:
        html_e, ct_e = _fetch_allaria_especie(args.especie)
        endpoints_e = _detect_internal_endpoints(html_e)
        blobs_e = _extract_embedded_json_blobs(html_e)
        print(f"[ALLARIA_ESPECIE] especie={args.especie!r} content_type={ct_e!r} bytes={len(html_e)}")
        print(f"[ALLARIA_ESPECIE] embedded_json_blobs={len(blobs_e)}")
        print(f"[ALLARIA_ESPECIE] internal_endpoint_candidates(sample)={endpoints_e[:25]}")
        # Pequeño snippet de texto (sin tags) para ver campos
        txt = _strip_tags(html_e)
        print(f"[ALLARIA_ESPECIE] text_prefix={txt[:800]!r}")
        return 0

    html, ct = _fetch_text(ALLARIA_URL)
    has_table = "<table" in html.lower()
    endpoints = _detect_internal_endpoints(html)
    blobs = _extract_embedded_json_blobs(html)

    # Intento 1: parsear tabla HTML real (con header)
    p = _AllariaTableParser()
    p.feed(html)
    header = p.header
    html_rows = p.rows

    # Intento 2 (fallback): si el HTML fue preconvertido a markdown en alguna capa, intentar tabla markdown.
    if not header or not html_rows:
        # Intento 2a: parse directo de <tr>/<td data-label>
        header2, rows2 = _extract_rows_from_html_tr(html)
        if rows2:
            header = header2
            rows = rows2
            parsed_via = "html_tr"
        else:
            # Intento 2b: tabla markdown (solo si existe)
            header, md_rows = _parse_markdown_table(html)
            rows = _to_allaria_rows(header, md_rows)
            parsed_via = "markdown"
    else:
        rows = _to_allaria_rows(header, html_rows)
        parsed_via = "html_table"

    print(f"[ALLARIA] url={ALLARIA_URL}")
    print(f"[ALLARIA] content_type={ct!r} bytes={len(html)} has_html_table={has_table}")
    # Ojo: en SSR, puede haber miles de links /Opcion/Especie/..., esto no implica API.
    print(f"[ALLARIA] internal_endpoint_candidates(sample)={endpoints[:12]}")
    print(f"[ALLARIA] embedded_json_blobs={len(blobs)}")
    print(f"[ALLARIA] parsed_via={parsed_via} columns={header[:20]}")
    print(f"[ALLARIA] parsed_rows={len(rows)}")

    # Parsear Allaria a OptionPoint (prefijo opciones + tipo + strike + expiry)
    allaria_points: list[OptionPoint] = []
    for r in rows:
        pt = _build_point_from_symbol(r.especie)
        if pt is None:
            continue
        allaria_points.append(pt)

    # Conteos Rava
    rava_opt = _rava_opt_items()
    rava_points: list[OptionPoint] = []
    for it in rava_opt:
        sym = _pick_symbol(it)
        pt = _build_point_from_symbol(sym)
        if pt is None:
            continue
        rava_points.append(pt)

    print()
    print("[ALLARIA] puntos parseados por prefijo (top 20):")
    a_by_prefix = Counter(p.underlying_prefix for p in allaria_points if p.underlying_prefix)
    for und, cnt in a_by_prefix.most_common(20):
        print(f"  {und}: {cnt}")

    print()
    print(f"[RAVA] opt_items={len(rava_opt)} puntos parseados por prefijo (top 20):")
    r_by_prefix = Counter(p.underlying_prefix for p in rava_points if p.underlying_prefix)
    for und, cnt in r_by_prefix.most_common(20):
        print(f"  {und}: {cnt}")

    print()
    u_filter = (args.underlying or "").strip().upper()
    # Permitir --underlying como símbolo acción (GGAL) o prefijo opciones (GFG)
    prefixes_to_report: list[str] = []
    if u_filter:
        # si coincide con acción, mapear a prefijo; si no, usar tal cual
        m = {a: p for a, p in COMPARE}
        prefixes_to_report = [m.get(u_filter, u_filter)]
    else:
        prefixes_to_report = [p for _a, p in COMPARE]

    print("[COMPARE] detalle Allaria vs Rava por prefijo opciones:")
    for action_sym, opt_prefix in COMPARE:
        if opt_prefix not in prefixes_to_report:
            continue
        print()
        print(f"== {action_sym}/{opt_prefix} ==")
        _summarize_underlying(allaria_points, underlying_prefix=opt_prefix, label="[ALLARIA]")
        _summarize_underlying(rava_points, underlying_prefix=opt_prefix, label="[RAVA]")
        _diff_underlying(allaria_points=allaria_points, rava_points=rava_points, underlying_prefix=opt_prefix)

    # Campos disponibles (desde header)
    print()
    print("[FIELDS] columnas Allaria detectadas:")
    for c in header:
        print(f"  - {c}")

    # Muestras por símbolo
    print()
    print("[SAMPLES] primeras filas Allaria (hasta 8):")
    for r in rows[:8]:
        print(
            f"  {r.subyacente} {r.especie} {r.tipo} vto={r.vencimiento} strike={r.strike_raw} "
            f"ult={r.ultimo_raw} bid={r.compra_raw} ask={r.venta_raw} vol={r.volumen_lotes_raw} hora={r.hora}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

