import pandas as pd


def generate_alert_type(row):
    signal = row.get("SignalState")
    previous_signal = row.get("EstadoAnterior")
    evolution = row.get("Evolucion")
    total_score = row.get("TotalScore")
    previous_score = row.get("ScoreAnterior")
    score_change = row.get("CambioScore")
    priority = row.get("PrioridadRadar")

    if signal == "COMPRA PRIORITARIA":
        return "COMPRA PRIORITARIA"

    if priority == "ALTA":
        return "PRIORIDAD ALTA"

    if score_change is not None and pd.notna(score_change) and score_change >= 2:
        return "MEJORA RELEVANTE"

    if signal == "COMPRA POTENCIAL" and previous_signal != "COMPRA POTENCIAL":
        return "NUEVA COMPRA POTENCIAL"

    if evolution == "MEJORANDO":
        return "ACTIVO MEJORANDO"

    if signal == "TOMA DE GANANCIA":
        return "TOMA DE GANANCIA"

    if signal == "DEBILITÁNDOSE":
        return "DEBILITAMIENTO"

    if evolution == "DETERIORANDO":
        return "DETERIORO"

    return None


def build_alert_message(row):
    alert_type = generate_alert_type(row)

    if alert_type is None:
        return None

    ticker = row.get("Ticker")
    company = row.get("Empresa")
    signal = row.get("SignalState")
    previous_signal = row.get("EstadoAnterior")
    total_score = row.get("TotalScore")
    previous_score = row.get("ScoreAnterior")
    score_change = row.get("CambioScore")
    upside = row.get("Upside_%")
    setup = row.get("Setup")
    priority = row.get("PrioridadRadar")

    message = (
        f"ALERTA RADAR\n\n"
        f"Ticker: {ticker}\n"
        f"Empresa: {company}\n"
        f"Tipo: {alert_type}\n"
        f"Estado actual: {signal}\n"
        f"Estado anterior: {previous_signal}\n"
        f"Score actual: {total_score}\n"
        f"Score anterior: {previous_score}\n"
        f"CambioScore: {score_change}\n"
        f"Upside: {upside}%\n"
        f"Setup: {setup}\n"
        f"Prioridad: {priority}"
    )

    return message


def generate_alerts(df: pd.DataFrame) -> pd.DataFrame:
    alerts = []

    for _, row in df.iterrows():
        alert_type = generate_alert_type(row)

        if alert_type is not None:
            alerts.append({
                "Ticker": row.get("Ticker"),
                "Empresa": row.get("Empresa"),
                "TipoAlerta": alert_type,
                "SignalState": row.get("SignalState"),
                "EstadoAnterior": row.get("EstadoAnterior"),
                "TotalScore": row.get("TotalScore"),
                "ScoreAnterior": row.get("ScoreAnterior"),
                "CambioScore": row.get("CambioScore"),
                "Upside_%": row.get("Upside_%"),
                "Setup": row.get("Setup"),
                "PrioridadRadar": row.get("PrioridadRadar"),
                "Mensaje": build_alert_message(row)
            })

    return pd.DataFrame(alerts)