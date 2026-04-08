from __future__ import annotations

import pandas as pd
from openpyxl import load_workbook

from core.config import OUTPUT_CSV, OUTPUT_EXCEL
from export.excel_format import format_workbook


def build_operativo_view(df):

    df = df.copy()

    if "ScoreAnterior" not in df.columns:
        if "score_anterior" in df.columns:
            df["ScoreAnterior"] = df["score_anterior"]
        else:
            df["ScoreAnterior"] = 0

    if "CambioScore" not in df.columns:
        if "Evolucion" in df.columns:
            df["CambioScore"] = df["Evolucion"]
        elif "TotalScore" in df.columns and "ScoreAnterior" in df.columns:
            df["CambioScore"] = df["TotalScore"] - df["ScoreAnterior"]
        elif "score" in df.columns and "ScoreAnterior" in df.columns:
            df["CambioScore"] = df["score"] - df["ScoreAnterior"]
        else:
            df["CambioScore"] = 0

    if "EstadoAnterior" not in df.columns:
        df["EstadoAnterior"] = ""

    columnas_deseadas = [
        "Ticker",
        "Activo",
        "Mercado",
        "TotalScore",
        "ScoreAnterior",
        "CambioScore",
        "Evolucion",
        "PrioridadRadar",
        "Estado",
        "EstadoAnterior",
    ]

    columnas_presentes = [col for col in columnas_deseadas if col in df.columns]

    return df[columnas_presentes]




def export_all(outputs: dict) -> tuple[str, str]:
    usa_df = outputs["usa_df"]
    usa_universo = outputs["usa_universo"]
    usa_sectores = outputs["usa_sectores"]
    usa_top10 = outputs["usa_top10"]
    usa_alerts = outputs["usa_alerts"]

    arg_df = outputs["arg_df"]
    arg_universo = outputs["arg_universo"]
    arg_sectores = outputs["arg_sectores"]
    arg_top10 = outputs["arg_top10"]
    arg_alerts = outputs["arg_alerts"]

    usa_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(OUTPUT_EXCEL, engine="openpyxl") as writer:
        # USA
        build_operativo_view(usa_df).to_excel(
            writer, sheet_name="Radar_Operativo", index=False
        )
        usa_df.to_excel(writer, sheet_name="Radar_Completo", index=False)
        usa_universo.to_excel(writer, sheet_name="Universo", index=False)
        usa_sectores.to_excel(writer, sheet_name="Resumen_Sectores", index=False)
        usa_top10.to_excel(writer, sheet_name="Top_10", index=False)
        usa_alerts.to_excel(writer, sheet_name="Alertas_USA", index=False)

        # Argentina
        build_operativo_view(arg_df).to_excel(
            writer, sheet_name="Radar_Argentina", index=False
        )
        arg_df.to_excel(writer, sheet_name="Radar_Argentina_Completo", index=False)
        arg_universo.to_excel(writer, sheet_name="Universo_Argentina", index=False)
        arg_sectores.to_excel(writer, sheet_name="Sectores_Argentina", index=False)
        arg_top10.to_excel(writer, sheet_name="Top_10_Argentina", index=False)
        arg_alerts.to_excel(writer, sheet_name="Alertas_Argentina", index=False)

    wb = load_workbook(OUTPUT_EXCEL)
    format_workbook(wb)
    wb.save(OUTPUT_EXCEL)

    return str(OUTPUT_EXCEL), str(OUTPUT_CSV)