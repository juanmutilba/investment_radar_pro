from __future__ import annotations

import time

from core.config import (
    ENABLE_TELEGRAM,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from notifications.telegram_notifier import send_alerts_dataframe
from services.export_service import export_results
from services.scan_service import run_full_scan


def main():
    # Pausa anti YFRateLimit entre motor USA y Argentina: run_full_scan aplica time.sleep(pause_after_usa_s).
    pause_after_usa_s = 2.0
    outputs = run_full_scan(verbose=True, pause_after_usa_s=pause_after_usa_s)
    previous_file = outputs.pop("previous_file")

    if previous_file:
        print(f"\nComparando contra archivo previo: {previous_file}")
    else:
        print("\nNo hay archivo previo para comparar.")

    usa_alerts = outputs["usa_alerts"]
    arg_alerts = outputs["arg_alerts"]

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

    export_results(outputs)


if __name__ == "__main__":
    main()
