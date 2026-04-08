from __future__ import annotations

from typing import Optional

import certifi
import requests


def send_telegram_message(bot_token: str, chat_id: str, message: str) -> bool:
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": message,
            },
            timeout=20,
            verify=certifi.where(),
        )

        print("STATUS:", response.status_code)
        print("RESPUESTA:", response.text)

        return response.status_code == 200

    except Exception as e:
        print(f"Error enviando mensaje Telegram: {e}")
        return False


def send_alerts_dataframe(bot_token: str, chat_id: str, df, title: Optional[str] = None) -> int:
    if df is None or df.empty:
        return 0

    sent = 0

    if title:
        send_telegram_message(bot_token, chat_id, title)

    for _, row in df.iterrows():
        message = row.get("Mensaje")

        if message:
            ok = send_telegram_message(bot_token, chat_id, message)
            if ok:
                sent += 1

    return sent