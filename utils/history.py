from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from core.signals import classify_evolution


def find_previous_export(export_folder: Path, current_output_path: Path) -> Path | None:
    excel_files = [
        export_folder / f
        for f in os.listdir(export_folder)
        if f.endswith('.xlsx')
    ]
    excel_files = [f for f in excel_files if f.resolve() != current_output_path.resolve()]
    if not excel_files:
        return None
    excel_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return excel_files[0]


def merge_history(df: pd.DataFrame, previous_file: Path | None, sheet_name: str) -> pd.DataFrame:
    if previous_file is None:
        df['ScoreAnterior'] = None
        df['EstadoAnterior'] = None
        df['CambioScore'] = None
        df['Evolucion'] = 'SIN HISTORIAL'
        return df

    try:
        df_prev = pd.read_excel(previous_file, sheet_name=sheet_name)
        comparison_cols = df_prev[['Ticker', 'TotalScore', 'SignalState']].copy()
        comparison_cols = comparison_cols.rename(columns={
            'TotalScore': 'ScoreAnterior',
            'SignalState': 'EstadoAnterior',
        })
        df = df.merge(comparison_cols, on='Ticker', how='left')
        df['CambioScore'] = df['TotalScore'] - df['ScoreAnterior']
        df['Evolucion'] = df.apply(
            lambda row: classify_evolution(
                current_score=row['TotalScore'],
                previous_score=row['ScoreAnterior'] if pd.notna(row['ScoreAnterior']) else None,
                current_state=row['SignalState'],
                previous_state=row['EstadoAnterior'] if pd.notna(row['EstadoAnterior']) else None,
            ),
            axis=1,
        )
        return df
    except Exception:
        df['ScoreAnterior'] = None
        df['EstadoAnterior'] = None
        df['CambioScore'] = None
        df['Evolucion'] = 'SIN HISTORIAL'
        return df
