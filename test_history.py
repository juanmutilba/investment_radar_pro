from core.history import save_state, get_last_state

print("Guardando estado...")

save_state("AAPL", {
    "tipo_alerta": "compra",
    "score": 85,
    "score_anterior": 75,
    "cambio_score": 10,
    "fingerprint": "breakout|trend_up"
})

print("Leyendo estado...")

estado = get_last_state("AAPL")

print(estado)
print("\nTest OK")