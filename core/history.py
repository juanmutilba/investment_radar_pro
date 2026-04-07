from __future__ import annotations

from pathlib import Path
import pandas as pd


def find_previous_export(export_folder: str, current_output_file: str | None = None):
    """
    Busca el archivo Excel más reciente dentro de la carpeta de exportación,
    excluyendo opcionalmente el archivo actual si ya existe.
    """
    folder = Path(export_folder)

    if not folder.exists() or not folder.is_dir():
        return None

    excel_files = sorted(
        folder.glob("*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if not excel_files:
        return None

    if current_output_file:
        current_name = Path(current_output_file).name
        excel_files = [f for f in excel_files if f.name != current_name]

    return str(excel_files[0]) if excel_files else None


def merge_history(df: pd.DataFrame, previous_file: str | None, previous_sheet_name: str):
    """
    Compara el dataframe actual contra el archivo Excel previo y agrega columnas
    de historial para no romper exportaciones ni scoring.
    """
    df = df.copy()

    # Columnas mínimas que el resto del proyecto espera
    if "Evolucion" not in df.columns:
        df["Evolucion"] = "NUEVO"

    if "ScoreAnterior" not in df.columns:
        df["ScoreAnterior"] = pd.NA

    if "CambioScore" not in df.columns:
        df["CambioScore"] = 0

    if "EstadoAnterior" not in df.columns:
        df["EstadoAnterior"] = "SIN_HISTORIAL"

    if not previous_file:
        return df

    try:
        prev_df = pd.read_excel(previous_file, sheet_name=previous_sheet_name)
    except Exception:
        return df

    if "Ticker" not in df.columns or "Ticker" not in prev_df.columns:
        return df

    prev_df = prev_df.copy()
    prev_df["Ticker"] = prev_df["Ticker"].astype(str)
    df["Ticker"] = df["Ticker"].astype(str)

    # Detectar mejor columna de score anterior
    score_col = None
    for candidate in ["TotalScore", "ScoreTotal", "Score"]:
        if candidate in prev_df.columns:
            score_col = candidate
            break

    # Detectar mejor columna de estado anterior
    state_col = None
    for candidate in ["PrioridadRadar", "Estado", "Signal", "Clasificacion"]:
        if candidate in prev_df.columns:
            state_col = candidate
            break

    prev_map = prev_df.set_index("Ticker")

    def build_row_history(row):
        ticker = row["Ticker"]

        if ticker not in prev_map.index:
            return pd.Series({
                "Evolucion": "NUEVO",
                "ScoreAnterior": pd.NA,
                "CambioScore": 0,
                "EstadoAnterior": "SIN_HISTORIAL",
            })

        prev_row = prev_map.loc[ticker]

        prev_score = prev_row[score_col] if score_col else pd.NA
        prev_state = prev_row[state_col] if state_col else "SIN_HISTORIAL"

        current_score = row["TotalScore"] if "TotalScore" in row else pd.NA

        try:
            if pd.notna(prev_score) and pd.notna(current_score):
                cambio_score = current_score - prev_score
            else:
                cambio_score = 0
        except Exception:
            cambio_score = 0

        if pd.isna(prev_score):
            evolucion = "MANTIENE"
        else:
            try:
                if cambio_score > 0:
                    evolucion = "MEJORA"
                elif cambio_score < 0:
                    evolucion = "EMPEORA"
                else:
                    evolucion = "MANTIENE"
            except Exception:
                evolucion = "MANTIENE"

        return pd.Series({
            "Evolucion": evolucion,
            "ScoreAnterior": prev_score,
            "CambioScore": cambio_score,
            "EstadoAnterior": prev_state,
        })

    history_df = df.apply(build_row_history, axis=1)

    df["Evolucion"] = history_df["Evolucion"]
    df["ScoreAnterior"] = history_df["ScoreAnterior"]
    df["CambioScore"] = history_df["CambioScore"]
    df["EstadoAnterior"] = history_df["EstadoAnterior"]

    return df