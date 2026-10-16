"""POST a OpenRouter con los errores del flujo; lo comparten el guardrail, el decisor JEV, la búsqueda de guías y el OCR."""
import time

import requests

from .errores import FlujoDetenido
from .reintentos import con_reintentos_503

URL_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
URL_DECISIONS = "https://openrouter.ai/api/alpha/decisions"


def post_openrouter(
    post, url: str, payload: dict, api_key: str, timeout, *, sin_conexion: str, respondio: str, error=FlujoDetenido
):
    """POST con JSON. Levanta `error` si no hay conexión o si el estado no es 200 (con `status_code`, que lee es_503).

    `sin_conexion` es el inicio del mensaje de red; `respondio` es el del estado y lleva el marcador {codigo}."""
    try:
        r = post(url, json=payload, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
    except requests.RequestException as e:
        raise error(f"{sin_conexion}: {e}") from e
    if r.status_code != 200:
        fallo = error(f"{respondio.format(codigo=r.status_code)}: {r.text[:200]}")
        fallo.status_code = r.status_code
        raise fallo
    return r


def payload_decisions(modelo: str, estado: str, preguntas: dict) -> dict:
    return {"model": modelo, "state": estado, "questions": preguntas}


def post_decisions(post, payload: dict, api_key: str, timeout, esperar=time.sleep, *, error=FlujoDetenido, etiqueta=""):
    """POST a la Decisions API; un 503 se reintenta hasta 3 veces con 1, 2 y 4 s, otros errores fallan de inmediato."""

    def llamar():
        return post_openrouter(
            post, URL_DECISIONS, payload, api_key, timeout, error=error,
            sin_conexion=f"No se pudo llamar a la Decisions API{etiqueta}",
            respondio=f"La Decisions API{etiqueta} respondió {{codigo}}",
        )

    return con_reintentos_503(llamar, esperar=esperar)
