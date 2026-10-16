"""Reintentos ante un 503 (servicio sobrecargado): 3 reintentos con espera 2**0, 2**1 y 2**2 segundos."""
import asyncio
import logging
import re
import time

logger = logging.getLogger(__name__)

REINTENTOS = 3


def es_503(error: Exception) -> bool:
    """True si el error es un 503: por su código, por el de su respuesta o por el texto del mensaje."""
    for objeto in (error, getattr(error, "response", None)):
        if getattr(objeto, "status_code", None) == 503:
            return True
    return re.search(r"\b503\b", str(error)) is not None


def _espera(intento: int) -> int:
    return 2**intento  # 1, 2, 4


def _segundos_de_espera(error: Exception, intento: int, reintentable=es_503):
    """Segundos a esperar antes de reintentar, o None si el error no es reintentable o ya se agotaron los reintentos."""
    if not reintentable(error) or intento == REINTENTOS:
        return None
    segundos = _espera(intento)
    logger.warning("503 (servicio sobrecargado): reintento %d de %d en %d s", intento + 1, REINTENTOS, segundos)
    return segundos


def con_reintentos_503(funcion, *args, esperar=time.sleep, reintentable=es_503, **kwargs):
    for intento in range(REINTENTOS + 1):
        try:
            return funcion(*args, **kwargs)
        except Exception as error:
            segundos = _segundos_de_espera(error, intento, reintentable)
            if segundos is None:
                raise
            esperar(segundos)


async def acon_reintentos_503(funcion, *args, aesperar=asyncio.sleep, reintentable=es_503, **kwargs):
    for intento in range(REINTENTOS + 1):
        try:
            return await funcion(*args, **kwargs)
        except Exception as error:
            segundos = _segundos_de_espera(error, intento, reintentable)
            if segundos is None:
                raise
            await aesperar(segundos)


REINTENTOS_FORMATO = 2


def es_error_de_formato(error: Exception) -> bool:
    """True si el LLM devolvió una salida estructurada inválida (ValidationError / OutputParserException)."""
    from langchain_core.exceptions import OutputParserException
    from pydantic import ValidationError

    return isinstance(error, (ValidationError, OutputParserException))


def con_reintentos_formato(funcion, *args, corregir=None, **kwargs):
    """Reintenta sin espera si el modelo rompió el contrato (p. ej. una lista entregada como texto). 503 se maneja aparte.

    Repetir la misma petición no sirve: a temperatura 0 y con la caché de LLM activa (celda 1.1) devuelve la misma respuesta
    mala sin llamar al modelo. `corregir(args, error) -> args` permite cambiar la petición en cada reintento."""
    for intento in range(REINTENTOS_FORMATO + 1):
        try:
            return funcion(*args, **kwargs)
        except Exception as error:
            if not es_error_de_formato(error) or intento == REINTENTOS_FORMATO:
                raise
            logger.warning("Salida con formato inválido: reintento %d de %d", intento + 1, REINTENTOS_FORMATO)
            if corregir:
                args = corregir(args, error)


def estructurar(llm, esquema):
    """El LLM con salida estructurada por function calling (el contrato es el esquema Pydantic)."""
    return llm.with_structured_output(esquema, method="function_calling")


def invocar_estructurado(invocar, mensajes, esperar=time.sleep, corregir=None):
    """Llama al LLM con salida estructurada: reintenta un 503 con espera y una salida con formato inválido sin ella."""
    return con_reintentos_formato(con_reintentos_503, invocar, mensajes, esperar=esperar, corregir=corregir)
