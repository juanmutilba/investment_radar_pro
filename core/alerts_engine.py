from datetime import datetime, timedelta

from core.history import get_last_state, save_state


COOLDOWNS_MINUTOS = {
    "compra": 120,
    "venta": 60,
    "toma_ganancia": 90,
}

CAMBIO_SCORE_COMPRA = 8
CAMBIO_SCORE_VENTA = -8
CAMBIO_SCORE_TOMA = -6
CAMBIO_MINIMO_REENVIO = 5
SALTO_SCORE_IMPORTANTE = 15


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


PRIORIDAD = {
    "venta": 3,
    "toma_ganancia": 2,
    "compra": 1,
}


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


def detectar_compra(row):

    score = row.get("score", 0)
    score_prev = row.get("score_anterior", 0)
    cambio = score - score_prev
    senales = row.get("senales", {})

    cantidad = contar_senales(senales, CLAVES_COMPRA)
    fingerprint = construir_fingerprint(senales, CLAVES_COMPRA)
    nueva_senal = es_fingerprint_nuevo(row["ticker"], fingerprint)

    senal_fuerte = (
        senales.get("breakout") or
        senales.get("macd_bullish_cross")
    )

    confluencia = cantidad >= 2

    if (
        score >= 80 and
        (
            cambio >= CAMBIO_SCORE_COMPRA or
            nueva_senal or
            cambio >= SALTO_SCORE_IMPORTANTE
        ) and
        (senal_fuerte or confluencia)
    ):

        return {
            "ticker": row["ticker"],
            "mercado": row.get("mercado", ""),
            "tipo_alerta": "compra",
            "score": score,
            "score_anterior": score_prev,
            "cambio_score": cambio,
            "fingerprint": fingerprint,
            "senales_activas": [
                k for k in CLAVES_COMPRA if senales.get(k)
            ],
            "motivo": "score_alto_y_senales_de_compra"
        }

    return None

def detectar_venta(row):

    score = row.get("score", 0)
    score_prev = row.get("score_anterior", 0)
    cambio = score - score_prev
    senales = row.get("senales", {})

    cantidad = contar_senales(senales, CLAVES_VENTA)
    fingerprint = construir_fingerprint(senales, CLAVES_VENTA)
    nueva_senal = es_fingerprint_nuevo(row["ticker"], fingerprint)

    senal_fuerte = (
        senales.get("loss_support") or
        senales.get("breakdown")
    )

    confluencia = cantidad >= 2

    if (
        score <= 35 and
        (
            cambio <= CAMBIO_SCORE_VENTA or
            nueva_senal or
            cambio <= -SALTO_SCORE_IMPORTANTE
        ) and
        (senal_fuerte or confluencia)
    ):

        return {
            "ticker": row["ticker"],
            "mercado": row.get("mercado", ""),
            "tipo_alerta": "venta",
            "score": score,
            "score_anterior": score_prev,
            "cambio_score": cambio,
            "fingerprint": fingerprint,
            "senales_activas": [
                k for k in CLAVES_VENTA if senales.get(k)
            ],
            "motivo": "deterioro_y_senales_de_venta"
        }

    return None


def detectar_toma(row):

    score = row.get("score", 0)
    score_prev = row.get("score_anterior", 0)
    cambio = score - score_prev
    senales = row.get("senales", {})

    cantidad = contar_senales(senales, CLAVES_TOMA)
    fingerprint = construir_fingerprint(senales, CLAVES_TOMA)
    nueva_senal = es_fingerprint_nuevo(row["ticker"], fingerprint)

    if (
        score >= 65 and
        (
            cambio <= CAMBIO_SCORE_TOMA or
            nueva_senal
        ) and
        cantidad >= 1
    ):

        return {
            "ticker": row["ticker"],
            "mercado": row.get("mercado", ""),
            "tipo_alerta": "toma_ganancia",
            "score": score,
            "score_anterior": score_prev,
            "cambio_score": cambio,
            "fingerprint": fingerprint,
            "senales_activas": [
                k for k in CLAVES_TOMA if senales.get(k)
            ],
            "motivo": "agotamiento_o_extension"
        }

    return None


def elegir_alerta(alertas):

    alertas_validas = [a for a in alertas if a]

    if not alertas_validas:
        return None

    return sorted(

        alertas_validas,

        key=lambda a:PRIORIDAD.get(
            a["tipo_alerta"],0
        ),

        reverse=True

    )[0]


def dentro_cooldown(alerta, estado_previo):

    if not estado_previo:
        return False

    tipo = alerta["tipo_alerta"]

    ultima = estado_previo.get("ultima_alerta")

    if not ultima:
        return False

    ultima_dt = datetime.fromisoformat(ultima)

    cooldown = COOLDOWNS_MINUTOS.get(tipo,60)

    return (
        datetime.now() - ultima_dt
        <
        timedelta(minutes=cooldown)
    )


def debe_enviar(alerta, estado_previo):

    if not estado_previo:
        return True, "primera_alerta"

    mismo_tipo = (
        estado_previo.get("tipo_alerta")
        ==
        alerta.get("tipo_alerta")
    )

    mismo_fp = (
        estado_previo.get("fingerprint")
        ==
        alerta.get("fingerprint")
    )

    score_prev = estado_previo.get("score", 0)
    score_actual = alerta.get("score", 0)
    cambio = abs(score_actual - score_prev)

    if dentro_cooldown(alerta, estado_previo):
        if mismo_tipo and mismo_fp and cambio < CAMBIO_MINIMO_REENVIO:
            return False, "duplicada_en_cooldown"

    if mismo_tipo and mismo_fp and cambio < CAMBIO_MINIMO_REENVIO:
        return False, "sin_cambio_relevante"

    return True, "enviar"


def formatear(alerta):

    iconos = {
        "compra": "🟢",
        "venta": "🔴",
        "toma_ganancia": "🟡"
    }

    icono = iconos.get(alerta["tipo_alerta"], "📡")
    senales = ", ".join(alerta["senales_activas"])
    motivo = alerta.get("motivo", "")

    return (
        f"{icono} {alerta['tipo_alerta'].upper()} {alerta['ticker']} ({alerta.get('mercado', '').upper()})\n"
        f"Score {alerta['score']} "
        f"(prev {alerta['score_anterior']} | Δ {alerta['cambio_score']:+})\n"
        f"Señales: {senales}\n"
        f"Motivo: {motivo}"
    )
def procesar_alertas(rows, notifier):

    enviadas = []

    for row in rows:

        alertas = [
            detectar_compra(row),
            detectar_venta(row),
            detectar_toma(row)
        ]

        alerta = elegir_alerta(alertas)

        if not alerta:
            ticker = row.get("ticker", "SIN_TICKER")
            print(f"[ALERTA] {ticker} sin alerta operable")
            continue

        previo = get_last_state(alerta["ticker"])

        enviar, motivo = debe_enviar(alerta, previo)

        if not enviar:
            print(f"[ALERTA] {alerta['ticker']} descartada: {motivo}")
            continue

        alerta["ultima_alerta"] = datetime.now().isoformat()

        mensaje = formatear(alerta)

        try:
            notifier.send(mensaje)
            save_state(alerta["ticker"], alerta)
            enviadas.append(alerta)

            print(
                f"[ALERTA] {alerta['ticker']} "
                f"{alerta['tipo_alerta']} enviada"
            )

        except Exception as e:
            print(
                f"[ALERTA] error enviando {alerta['ticker']} "
                f"{alerta['tipo_alerta']}: {e}"
            )

    return enviadas

