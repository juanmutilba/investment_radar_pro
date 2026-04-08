from core.config import ENABLE_TELEGRAM, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from notifications.telegram_notifier import send_telegram_message

print("TOKEN LEN:", len(TELEGRAM_BOT_TOKEN))
print("TOKEN INICIO:", TELEGRAM_BOT_TOKEN[:10])
print("TOKEN FIN:", TELEGRAM_BOT_TOKEN[-10:])
print("ENABLE_TELEGRAM:", ENABLE_TELEGRAM)
print("TOKEN OK:", bool(TELEGRAM_BOT_TOKEN))
print("CHAT ID OK:", bool(TELEGRAM_CHAT_ID))

ok = send_telegram_message(
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    "Prueba Telegram desde investment_radar_pro"
)

print("ENVIO OK:", ok)