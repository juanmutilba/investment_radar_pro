from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import ALERT_TIPO_ETIQUETA, EXPORT_FOLDER


def resolve_latest_export_path() -> Path | None:
    folder = Path(EXPORT_FOLDER)
    if not folder.is_dir():
        return None
    files = list(folder.glob("radar_*.xlsx"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _read_sheet(path: Path, sheet_name: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    except (ValueError, KeyError, OSError):
        return pd.DataFrame()


def _nonempty_row_count(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    return int(df.dropna(how="all").shape[0])


def read_latest_summary() -> dict[str, Any] | None:
    path = resolve_latest_export_path()
    if path is None:
        return None

    usa_df = _read_sheet(path, "Radar_Completo")
    arg_df = _read_sheet(path, "Radar_Argentina_Completo")
    usa_alerts = _read_sheet(path, "Alertas_USA")
    arg_alerts = _read_sheet(path, "Alertas_Argentina")

    return {
        "file": str(path.resolve()),
        "usa_tickers_count": _nonempty_row_count(usa_df),
        "arg_tickers_count": _nonempty_row_count(arg_df),
        "usa_alerts_count": _nonempty_row_count(usa_alerts),
        "arg_alerts_count": _nonempty_row_count(arg_alerts),
    }


def _df_to_radar_payload(path: Path, sheet: str) -> dict[str, Any]:
    df = _read_sheet(path, sheet)
    if df.empty:
        rows: list[dict[str, Any]] = []
    else:
        df = df.dropna(how="all")
        if df.empty:
            rows = []
        else:
            rows = json.loads(
                df.to_json(orient="records", date_format="iso", default_handler=str)
            )

    return {
        "file": str(path.resolve()),
        "sheet": sheet,
        "rows": rows,
    }


def read_latest_radar() -> dict[str, Any] | None:
    """
    Ultimo radar_*.xlsx: filas de la hoja Radar_Completo como lista de objetos JSON-serializables.
    """
    path = resolve_latest_export_path()
    if path is None:
        return None
    return _df_to_radar_payload(path, "Radar_Completo")


def read_latest_radar_argentina() -> dict[str, Any] | None:
    """
    Ultimo radar_*.xlsx: filas de Radar_Argentina_Completo.
    """
    path = resolve_latest_export_path()
    if path is None:
        return None
    return _df_to_radar_payload(path, "Radar_Argentina_Completo")


def _cell(row: pd.Series, *names: str) -> Any:
    for name in names:
        if name in row.index and pd.notna(row[name]):
            v = row[name]
            if hasattr(v, "item"):
                try:
                    return v.item()
                except (ValueError, AttributeError):
                    return v
            return v
    return None


def _alert_tipo_key(raw: Any) -> str | None:
    """Clave interna del motor (compra_fuerte, …); None si no coincide con tipos conocidos."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().lower()
    if s in ALERT_TIPO_ETIQUETA:
        return s
    return None


def _alert_row_to_dict(row: pd.Series, mercado_fallback: str) -> dict[str, Any]:
    mercado = _cell(row, "mercado", "Mercado")
    if mercado is None or (isinstance(mercado, str) and not mercado.strip()):
        mercado = mercado_fallback

    raw_key = _cell(row, "tipo_alerta")
    tipo_key = _alert_tipo_key(raw_key)
    visible = _cell(row, "TipoAlerta")
    if visible is None or (isinstance(visible, float) and pd.isna(visible)):
        visible = ALERT_TIPO_ETIQUETA.get(tipo_key, raw_key) if tipo_key else raw_key

    return {
        "ticker": _cell(row, "Ticker", "ticker"),
        "tipo_alerta": visible,
        "tipo_alerta_key": tipo_key,
        "score": _cell(row, "score"),
        "score_anterior": _cell(row, "score_anterior", "ScoreAnterior"),
        "cambio_score": _cell(row, "cambio_score", "CambioScore"),
        "mercado": mercado,
    }


def read_latest_alerts() -> list[dict[str, Any]] | None:
    """
    None si no hay ningún export; lista vacía si el archivo existe pero no hay filas de alerta.
    """
    path = resolve_latest_export_path()
    if path is None:
        return None

    out: list[dict[str, Any]] = []

    for sheet, fallback_mercado in (
        ("Alertas_USA", "USA"),
        ("Alertas_Argentina", "Argentina"),
    ):
        df = _read_sheet(path, sheet)
        if df.empty:
            continue
        df = df.dropna(how="all")
        for _, row in df.iterrows():
            out.append(_alert_row_to_dict(row, fallback_mercado))

    return out
