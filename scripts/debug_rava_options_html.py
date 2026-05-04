"""
Diagnóstico RAW: inspección HTML de Rava opciones (sin parsear).

Objetivo: verificar si el HTML contiene strings/estructuras útiles para parsear luego.

Uso (desde la raíz del repo):
    python scripts/debug_rava_options_html.py
"""

from __future__ import annotations

import sys

import requests


URL = "https://www.rava.com/cotizaciones/opciones"

def _safe_print(s: str) -> None:
    # En Windows, la consola puede usar cp1252; evitar UnicodeEncodeError.
    try:
        print(s, flush=True)
    except UnicodeEncodeError:
        b = (s or "").encode(getattr(sys.stdout, "encoding", None) or "utf-8", errors="replace")
        sys.stdout.buffer.write(b + b"\n")
        sys.stdout.flush()


def _contains(haystack: str, needle: str) -> bool:
    return needle in (haystack or "")


def _snippet_around(text: str, needle: str, *, radius: int = 250, max_snippets: int = 3) -> list[str]:
    t = text or ""
    if not needle:
        return []
    out: list[str] = []
    start = 0
    while len(out) < max_snippets:
        i = t.find(needle, start)
        if i < 0:
            break
        a = max(0, i - radius)
        b = min(len(t), i + len(needle) + radius)
        out.append(t[a:b].replace("\r", "").replace("\n", "\\n"))
        start = i + len(needle)
    return out


def main() -> int:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        )
    }

    try:
        r = requests.get(URL, headers=headers, timeout=30)
    except requests.RequestException as e:
        print(f"[RAVA_OPTIONS_DEBUG] status_code=error error={type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return 1

    content_type = str(r.headers.get("content-type") or "")
    length = len(r.content or b"")
    html = ""
    try:
        html = r.text or ""
    except Exception:
        html = ""

    html_lower = html.lower()

    contains_ggal = _contains(html, "GGAL") or _contains(html, "ggal")
    contains_call = _contains(html, "Call") or _contains(html_lower, "call")
    contains_put = _contains(html, "Put") or _contains(html_lower, "put")
    contains_table = ("<table" in html_lower) or ("</table" in html_lower)

    _safe_print(f"[RAVA_OPTIONS_DEBUG] status_code={r.status_code}")
    _safe_print(f"[RAVA_OPTIONS_DEBUG] content_type={content_type!r}")
    _safe_print(f"[RAVA_OPTIONS_DEBUG] length={length}")
    _safe_print(f"[RAVA_OPTIONS_DEBUG] contains_GGAL={contains_ggal}")
    _safe_print(f"[RAVA_OPTIONS_DEBUG] contains_Call={contains_call}")
    _safe_print(f"[RAVA_OPTIONS_DEBUG] contains_Put={contains_put}")
    _safe_print(f"[RAVA_OPTIONS_DEBUG] contains_table={contains_table}")

    for needle in ("GGAL", "ggal", "Call", "call", "Put", "put", "<table", "table"):
        snippets = _snippet_around(html, needle)
        if not snippets:
            continue
        for idx, sn in enumerate(snippets, 1):
            _safe_print(f"[RAVA_OPTIONS_DEBUG] snippet needle={needle!r} idx={idx}: {sn}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

