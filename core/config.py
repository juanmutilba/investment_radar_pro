from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

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

# =====================
# ALERTAS (TotalScore ~ -1..12)
# =====================

ALERT_COMPRA_FUERTE_MIN = 8
ALERT_COMPRA_POTENCIAL_SCORE = 7

ALERT_VENTA_MAX_SCORE = 3
ALERT_VENTA_MIN_DELTA = -2

ALERT_TOMA_MIN_SCORE = 7
ALERT_TOMA_MAX_DELTA = -2

ALERT_COMPRA_MIN_DELTA = 2
ALERT_SALTO_SCORE_ABS = 4
ALERT_REENVIO_SCORE_MIN = 2

ALERT_COOLDOWN_MINUTOS = {
    "compra_fuerte": 120,
    "compra_potencial": 120,
    "venta": 60,
    "toma_ganancia": 90,
}

ALERT_PRIORIDAD = {
    "venta": 4,
    "toma_ganancia": 3,
    "compra_fuerte": 2,
    "compra_potencial": 1,
}

ALERT_TIPO_ETIQUETA = {
    "compra_fuerte": "COMPRA FUERTE",
    "compra_potencial": "COMPRA POTENCIAL",
    "venta": "VENTA",
    "toma_ganancia": "TOMA GANANCIA",
}
