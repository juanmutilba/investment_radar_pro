
from core.config import (
    ALERT_COMPRA_FUERTE_MIN,
    ALERT_COMPRA_MIN_DELTA,
    ALERT_COMPRA_POTENCIAL_SCORE,
    ALERT_COOLDOWN_MINUTOS,
    ALERT_PRIORIDAD,
    ALERT_REENVIO_SCORE_MIN,
    ALERT_SALTO_SCORE_ABS,
    ALERT_TIPO_ETIQUETA,
    ALERT_TOMA_MAX_DELTA,
    ALERT_TOMA_MIN_SCORE,
    ALERT_VENTA_MAX_SCORE,
    ALERT_VENTA_MIN_DELTA,
)
from core.history import get_last_state, save_state


CLAVES_COMPRA = [
    "breakout",
    "macd_bullish_cross",
    "rsi_recovery",
    "trend_up",
]

CLAVES_VENTA = [
    "loss_support",
    "macd_bearish_cross",
    "trend_down",
    "breakdown",
]

CLAVES_TOMA = [
    "extended_from_mean",
    "rsi_overbought",
    "momentum_loss",
]


def obtener_ticker(row):
    return (
        row.get("ticker")
        or row.get("Ticker")
        or row.get("symbol")
        or row.get("Symbol")
        or row.get("activo")
        or row.get("Activo")
        or row.get("simbolo")
        or row.get("Simbolo")
    )


def obtener_mercado(row):
    for key in ("mercado", "Mercado", "market", "Market"):
        raw = row.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if s and s.lower() != "nan":
            return s

    raw = row.get("TipoUniverso")
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return ""
    if s.upper() == "ARGENTINA":
        return "Argentina"
    return "USA"


def obtener_score(row):
    valor = (
        row.get("score")
        if row.get("score") is not None
        else row.get("TotalScore")
    )

    if valor is None:
        return 0

    return valor


def obtener_score_anterior(row):
    if row.get("score_anterior") is not None:
        return row.get("score_anterior")

    score_actual = obtener_score(row)
    evolucion = row.get("Evolucion", 0)

    try:
        return score_actual - evolucion
    except Exception:
        return 0


def _valor_rsi_fila(row) -> float | None:
    v = row.get("RSI")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _senales_desde_columnas_radar(row) -> dict:
    trend = bool(row.get("Trend"))
    macd_bull = bool(row.get("MACD_Bull"))
    pullback = bool(row.get("Pullback"))
    rsi = _valor_rsi_fila(row)

    rsi_recovery = False
    if rsi is not None:
        rsi_recovery = (30.0 <= rsi <= 45.0) or (pullback and rsi < 48.0)

    breakout = trend and macd_bull and not pullback

    rsi_ob = rsi is not None and rsi > 70.0

    return {
        "breakout": breakout,
        "macd_bullish_cross": macd_bull,
        "rsi_recovery": rsi_recovery,
        "trend_up": trend,
        "loss_support": False,
        "macd_bearish_cross": not macd_bull,
        "trend_down": not trend,
        "breakdown": (not trend) and (not macd_bull),
        "extended_from_mean": False,
        "rsi_overbought": rsi_ob,
        "momentum_loss": pullback and trend,
    }


def obtener_senales(row):
    senales = row.get("senales")
    if isinstance(senales, dict) and senales:
        return senales

    signals = row.get("signals")
    if isinstance(signals, dict) and signals:
        return signals

    return _senales_desde_columnas_radar(row)


def construir_fingerprint(senales, claves):
    activas = sorted([k for k in claves if senales.get(k)])
    return "|".join(activas)


def contar_senales(senales, claves):
    return sum(1 for k in claves if senales.get(k))


def es_fingerprint_nuevo(ticker, fingerprint_actual):
    previo = get_last_state(ticker)
    if not previo:
        return True
    fingerprint_previo = previo.get("fingerprint", "")
    return fingerprint_actual != fingerprint_previo


def _disparador_compra(cambio: int, nueva_senal: bool) -> bool:
    return (
        cambio >= ALERT_COMPRA_MIN_DELTA
        or nueva_senal
        or cambio >= ALERT_SALTO_SCORE_ABS
    )


def detectar_compra_fuerte(row):
    ticker = obtener_ticker(row)
    if not ticker:
        return None

    score = obtener_score(row)
    if score < ALERT_COMPRA_FUERTE_MIN:
        return None

    score_prev = obtener_score_anterior(row)
    cambio = score - score_prev
    senales = obtener_senales(row)
    cantidad = contar_senales(senales, CLAVES_COMPRA)
    fingerprint = construir_fingerprint(senales, CLAVES_COMPRA)
    nueva_senal = es_fingerprint_nuevo(ticker, fingerprint)
    senal_fuerte = senales.get("breakout") or senales.get("macd_bullish_cross")
    confluencia = cantidad >= 2

    if _disparador_compra(cambio, nueva_senal) and (senal_fuerte or confluencia):
        return {
            "ticker": ticker,
            "mercado": obtener_mercado(row),
            "tipo_alerta": "compra_fuerte",
            "score": score,
            "score_anterior": score_prev,
            "cambio_score": cambio,
            "fingerprint": fingerprint,
            "senales_activas": [k for k in CLAVES_COMPRA if senales.get(k)],
            "motivo": "score_alto_y_senales_de_compra",
        }
    return None


def detectar_compra_potencial(row):
    ticker = obtener_ticker(row)
    if not ticker:
        return None

    score = obtener_score(row)
    if score != ALERT_COMPRA_POTENCIAL_SCORE:
        return None

    score_prev = obtener_score_anterior(row)
    cambio = score - score_prev
    senales = obtener_senales(row)
    cantidad = contar_senales(senales, CLAVES_COMPRA)
    fingerprint = construir_fingerprint(senales, CLAVES_COMPRA)
    nueva_senal = es_fingerprint_nuevo(ticker, fingerprint)
    senal_fuerte = senales.get("breakout") or senales.get("macd_bullish_cross")
    confluencia = cantidad >= 2

    if _disparador_compra(cambio, nueva_senal) and (senal_fuerte or confluencia):
        return {
            "ticker": ticker,
            "mercado": obtener_mercado(row),
            "tipo_alerta": "compra_potencial",
            "score": score,
            "score_anterior": score_prev,
            "cambio_score": cambio,
            "fingerprint": fingerprint,
            "senales_activas": [k for k in CLAVES_COMPRA if senales.get(k)],
            "motivo": "score_radar_y_senales_de_compra",
        }
    return None


def detectar_venta(row):
    ticker = obtener_ticker(row)
    if not ticker:
        return None

    score = obtener_score(row)
    if score > ALERT_VENTA_MAX_SCORE:
        return None

    score_prev = obtener_score_anterior(row)
    cambio = score - score_prev
    senales = obtener_senales(row)

    if cambio > ALERT_VENTA_MIN_DELTA:
        return None

    fingerprint = construir_fingerprint(senales, CLAVES_VENTA)

    return {
        "ticker": ticker,
        "mercado": obtener_mercado(row),
        "tipo_alerta": "venta",
        "score": score,
        "score_anterior": score_prev,
        "cambio_score": cambio,
        "fingerprint": fingerprint,
        "senales_activas": [k for k in CLAVES_VENTA if senales.get(k)],
        "motivo": "score_bajo_y_deterioro",
    }


def detectar_toma(row):
    ticker = obtener_ticker(row)
    if not ticker:
        return None

    score = obtener_score(row)
    score_prev = obtener_score_anterior(row)
    cambio = score - score_prev
    senales = obtener_senales(row)

    if score < ALERT_TOMA_MIN_SCORE or cambio > ALERT_TOMA_MAX_DELTA:
        return None

    fingerprint = construir_fingerprint(senales, CLAVES_TOMA)

    return {
        "ticker": ticker,
        "mercado": obtener_mercado(row),
        "tipo_alerta": "toma_ganancia",
        "score": score,
        "score_anterior": score_prev,
        "cambio_score": cambio,
        "fingerprint": fingerprint,
        "senales_activas": [k for k in CLAVES_TOMA if senales.get(k)],
        "motivo": "retroceso_desde_nivel_alto",
    }


def elegir_alerta(alertas):
    alertas_validas = [a for a in alertas if a]
    if not alertas_validas:
        return None
    return sorted(
        alertas_validas,
        key=lambda a: ALERT_PRIORIDAD.get(a["tipo_alerta"], 0),
        reverse=True,
    )[0]


def _cooldown_minutos(tipo_alerta: str) -> int:
    m = ALERT_COOLDOWN_MINUTOS.get(tipo_alerta)
    if m is not None:
        return m
    if tipo_alerta == "compra":
        return ALERT_COOLDOWN_MINUTOS["compra_fuerte"]
    return 60


def dentro_cooldown(alerta, estado_previo):
    if not estado_previo:
        return False

    tipo = alerta["tipo_alerta"]
    ultima = estado_previo.get("ultima_alerta")
    if not ultima:
        return False

    ultima_dt = datetime.fromisoformat(ultima)
    cooldown = _cooldown_minutos(tipo)
    return datetime.now() - ultima_dt < timedelta(minutes=cooldown)


def debe_enviar(alerta, estado_previo):
    if not estado_previo:
        return True, "primera_alerta"

    mismo_tipo = estado_previo.get("tipo_alerta") == alerta.get("tipo_alerta")
    mismo_fp = estado_previo.get("fingerprint") == alerta.get("fingerprint")
    score_prev_hist = estado_previo.get("score", 0)
    score_actual = alerta.get("score", 0)
    delta_abs = abs(score_actual - score_prev_hist)

    if dentro_cooldown(alerta, estado_previo):
        if mismo_tipo and mismo_fp and delta_abs < ALERT_REENVIO_SCORE_MIN:
            return False, "duplicada_en_cooldown"

    if mismo_tipo and mismo_fp and delta_abs < ALERT_REENVIO_SCORE_MIN:
        return False, "sin_cambio_relevante"

    return True, "enviar"


def formatear(alerta):
    tipo = alerta["tipo_alerta"]
    icono = {
        "compra_fuerte": "[CF]",
        "compra_potencial": "[CP]",
        "venta": "[V]",
        "toma_ganancia": "[TG]",
    }.get(tipo, "[*]")
    etiqueta = ALERT_TIPO_ETIQUETA.get(tipo, tipo.upper())
    senales = ", ".join(alerta["senales_activas"])
    motivo = alerta.get("motivo", "")

    return (
        f"{icono} {etiqueta} {alerta['ticker']} ({alerta.get('mercado', '').upper()})\n"
        f"Score {alerta['score']} "
        f"(prev {alerta['score_anterior']} | d {alerta['cambio_score']:+})\n"
        f"Se\u00f1ales: {senales}\n"
        f"Motivo: {motivo}"
    )


def _enriquecer_alerta_export(alerta: dict, mensaje: str) -> None:
    alerta["Mensaje"] = mensaje
    alerta["Ticker"] = alerta["ticker"]
    alerta["TipoAlerta"] = ALERT_TIPO_ETIQUETA.get(
        alerta["tipo_alerta"], alerta["tipo_alerta"]
    )


def procesar_alertas(rows, notifier):
    enviadas = []

    for row in rows:
        alertas = [
            detectar_compra_fuerte(row),
            detectar_compra_potencial(row),
            detectar_venta(row),
            detectar_toma(row),
        ]
        alerta = elegir_alerta(alertas)

        if not alerta:
            ticker = obtener_ticker(row) or row.get("ticker", "SIN_TICKER")
            print(f"[ALERTA] {ticker} sin alerta operable")
            continue

        previo = get_last_state(alerta["ticker"])
        enviar, motivo = debe_enviar(alerta, previo)

        if not enviar:
            print(f"[ALERTA] {alerta['ticker']} descartada: {motivo}")
            continue

        alerta["ultima_alerta"] = datetime.now().isoformat()
        mensaje = formatear(alerta)
        _enriquecer_alerta_export(alerta, mensaje)

        try:
            notifier.send(mensaje)
            save_state(alerta["ticker"], alerta)
            enviadas.append(alerta)
            print(f"[ALERTA] {alerta['ticker']} {alerta['tipo_alerta']} enviada")
        except Exception as e:
            print(
                f"[ALERTA] error enviando {alerta['ticker']} "
                f"{alerta['tipo_alerta']}: {e}"
            )

    return enviadas


class DummyNotifier:
    def send(self, message):
        print("\n=== ALERTA ===")
        print(message)
        return True


def generate_alerts(rows, notifier=None):
    if notifier is None:
        notifier = DummyNotifier()

    if hasattr(rows, "to_dict"):
        rows = rows.to_dict(orient="records")

    alertas = procesar_alertas(rows, notifier)

    try:
        import pandas as pd

        return pd.DataFrame(alertas)
    except Exception:
        return alertas
