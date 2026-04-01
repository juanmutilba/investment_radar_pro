from __future__ import annotations

import pandas as pd
from openpyxl import load_workbook

from config import OUTPUT_CSV, OUTPUT_EXCEL
from export.excel_format import format_workbook


def build_operativo_view(df: pd.DataFrame) -> pd.DataFrame:
    return df[
        [
            'Ticker', 'Empresa', 'RiskProfile', 'Precio', 'Upside_%', 'RSI',
            'TechScore', 'FundScore', 'RiskScore', 'TotalScore',
            'ScoreAnterior', 'CambioScore', 'Setup', 'SignalState',
            'EstadoAnterior', 'Evolucion', 'PrioridadRadar', 'Conviccion',
            'CapitalSugerido_%',
        ]
    ].copy()


def export_all(outputs: dict) -> tuple[str, str]:
    usa_df = outputs['usa_df']
    usa_universo = outputs['usa_universo']
    usa_sectores = outputs['usa_sectores']
    usa_top10 = outputs['usa_top10']
    arg_df = outputs['arg_df']
    arg_universo = outputs['arg_universo']
    arg_sectores = outputs['arg_sectores']
    arg_top10 = outputs['arg_top10']

    usa_df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')

    with pd.ExcelWriter(OUTPUT_EXCEL, engine='openpyxl') as writer:
        build_operativo_view(usa_df).to_excel(writer, sheet_name='Radar_Operativo', index=False)
        usa_df.to_excel(writer, sheet_name='Radar_Completo', index=False)
        usa_universo.to_excel(writer, sheet_name='Universo', index=False)
        usa_sectores.to_excel(writer, sheet_name='Resumen_Sectores', index=False)
        usa_top10.to_excel(writer, sheet_name='Top_10', index=False)

        build_operativo_view(arg_df).to_excel(writer, sheet_name='Radar_Argentina', index=False)
        arg_df.to_excel(writer, sheet_name='Radar_Argentina_Completo', index=False)
        arg_universo.to_excel(writer, sheet_name='Universo_Argentina', index=False)
        arg_sectores.to_excel(writer, sheet_name='Sectores_Argentina', index=False)
        arg_top10.to_excel(writer, sheet_name='Top_10_Argentina', index=False)

    wb = load_workbook(OUTPUT_EXCEL)
    format_workbook(wb)
    wb.save(OUTPUT_EXCEL)

    return str(OUTPUT_EXCEL), str(OUTPUT_CSV)
