from __future__ import annotations

from core.config import (
    EXPORT_FOLDER,
    OUTPUT_EXCEL,
    ENABLE_TELEGRAM,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)


from core.signals import classify_priority
from core.alerts_engine import generate_alerts
from engines.argentina_engine import run_argentina_engine
from engines.usa_engine import run_usa_engine
from export.exporter import export_all
from notifications.telegram_notifier import send_alerts_dataframe
from core.history import find_previous_export, merge_history

def prepare_dataframe(df, previous_file, previous_sheet_name):
    df = merge_history(df, previous_file, previous_sheet_name)

    df["PrioridadRadar"] = df.apply(
        lambda row: classify_priority(row["TotalScore"], row["Evolucion"]),
        axis=1,
    )

    priority_order = {"ALTA": 0, "MEDIA": 1, "BAJA": 2, "IGNORAR": 3}
    df["PriorityOrder"] = df["PrioridadRadar"].map(priority_order)

    df = df.sort_values(
        by=["PriorityOrder", "TotalScore", "TechScore", "Upside_%"],
        ascending=[True, False, False, False],
    ).drop(columns=["PriorityOrder"])

    return df


def main():
    print("Corriendo motor USA...")
    usa_df, usa_universo, usa_sectores, _ = run_usa_engine()

    print("\nCorriendo motor Argentina...")
    arg_df, arg_universo, arg_sectores = run_argentina_engine()

    previous_file = find_previous_export(EXPORT_FOLDER, OUTPUT_EXCEL)

    if previous_file:
        print(f"\nComparando contra archivo previo: {previous_file}")
    else:
        print("\nNo hay archivo previo para comparar.")

    usa_df = prepare_dataframe(usa_df, previous_file, "Radar_Completo")
    arg_df = prepare_dataframe(arg_df, previous_file, "Radar_Argentina_Completo")

    usa_top10 = usa_df.head(10).copy()
    arg_top10 = arg_df.head(10).copy()

    # =========================
    # ALERTAS
    # =========================
    usa_alerts = generate_alerts(usa_df)
    arg_alerts = generate_alerts(arg_df)

    print("\nALERTAS USA DETECTADAS\n")
    if not usa_alerts.empty:
        print(usa_alerts[["Ticker", "TipoAlerta"]].to_string(index=False))
    else:
        print("Sin alertas relevantes en USA")

    print("\nALERTAS ARGENTINA DETECTADAS\n")
    if not arg_alerts.empty:
        print(arg_alerts[["Ticker", "TipoAlerta"]].to_string(index=False))
    else:
        print("Sin alertas relevantes en Argentina")
        
            # =========================
    # TELEGRAM
    # =========================
    if ENABLE_TELEGRAM and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        print("\nEnviando alertas por Telegram...")

        sent_usa = send_alerts_dataframe(
            TELEGRAM_BOT_TOKEN,
            TELEGRAM_CHAT_ID,
            usa_alerts,
            title="ALERTAS RADAR USA",
        )

        sent_arg = send_alerts_dataframe(
            TELEGRAM_BOT_TOKEN,
            TELEGRAM_CHAT_ID,
            arg_alerts,
            title="ALERTAS RADAR ARGENTINA",
        )

        print(f"Alertas USA enviadas: {sent_usa}")
        print(f"Alertas Argentina enviadas: {sent_arg}")
    else:
        print("\nTelegram desactivado o sin credenciales configuradas.")

    outputs = {
        "usa_df": usa_df,
        "usa_universo": usa_universo,
        "usa_sectores": usa_sectores,
        "usa_top10": usa_top10,
        "usa_alerts": usa_alerts,
        "arg_df": arg_df,
        "arg_universo": arg_universo,
        "arg_sectores": arg_sectores,
        "arg_top10": arg_top10,
        "arg_alerts": arg_alerts,
    }

    excel_path, csv_path = export_all(outputs)

    print("\nEXPORTACIÓN COMPLETA")
    print(f"Excel generado: {excel_path}")
    print(f"CSV generado:   {csv_path}")


if __name__ == "__main__":
    main()