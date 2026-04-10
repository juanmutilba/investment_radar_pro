from core.alerts_engine import procesar_alertas


class DummyNotifier:
    def send(self, message):
        print("\n=== MENSAJE ENVIADO ===")
        print(message)
        return True


rows = [
    {
        "Ticker": "AAPL",
        "mercado": "usa",
        "TotalScore": 8,
        "score_anterior": 6,
        "senales": {
            "breakout": True,
            "macd_bullish_cross": True,
            "rsi_recovery": False,
            "trend_up": True,
            "loss_support": False,
            "macd_bearish_cross": False,
            "trend_down": False,
            "breakdown": False,
            "extended_from_mean": False,
            "rsi_overbought": False,
            "momentum_loss": False,
        },
    }
]

notifier = DummyNotifier()
resultado = procesar_alertas(rows, notifier)

print("\n=== RESULTADO ===")
print(resultado)
