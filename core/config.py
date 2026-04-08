from pathlib import Path
from datetime import datetime
import os

BASE_DIR = Path(__file__).resolve().parent
EXPORT_FOLDER = BASE_DIR / 'exportaciones_excel'
EXPORT_FOLDER.mkdir(exist_ok=True)

# =====================
# TELEGRAM
# =====================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "false").strip().lower() == "true"

TIMESTAMP = datetime.now().strftime('%Y-%m-%d_%H-%M')
OUTPUT_EXCEL = EXPORT_FOLDER / f'radar_{TIMESTAMP}.xlsx'
OUTPUT_CSV = EXPORT_FOLDER / f'radar_{TIMESTAMP}.csv'

PRICE_HISTORY_PERIOD = '1y'
RSI_WINDOW = 14
MA_SHORT = 50
MA_LONG = 200

BUY_PRIORITY_THRESHOLD = 10
BUY_THRESHOLD = 8
FOLLOW_THRESHOLD = 5
UPSIDE_PRIORITY = 0.10
UPSIDE_MIN = 0.05

PE_MAX = 15
DEBT_TO_EQUITY_MAX = 200

RISK_BETA_IDEAL_MIN = 0.8
RISK_BETA_IDEAL_MAX = 1.6
RISK_BETA_NEUTRAL_MIN = 0.6
RISK_BETA_NEUTRAL_MAX = 2.0
