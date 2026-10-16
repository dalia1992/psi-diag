"""Errores de la API con forma conocida: se convierten tal cual en el cuerpo JSON o en el evento de error del stream."""
import re
from typing import Any

VERSION = "1.0"
CODIGOS_ERROR = ("validacion", "archivo", "ocr", "acceso", "limite", "sin_configurar", "timeout", "backend")
MENSAJES_ERROR = {
    "validacion": "La solicitud no es válida.",
    "archivo": "No se pudo usar el archivo.",
    "ocr": "Falta confirmar la lectura del archivo.",
    "acceso": "El código de acceso no es correcto.",
    "limite": "Hay demasiadas solicitudes seguidas. Espera un momento y vuelve a intentar.",
    "sin_configurar": "El servicio no está configurado.",
    "timeout": "El análisis tardó demasiado.",
    "backend": "Error inesperado.",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ErrorApi(Exception):
    def __init__(self, codigo: str, mensaje: str, status: int = 400, detalle: str = "", reintentable: bool = False):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.status = status
        self.detalle = detalle
        self.reintentable = reintentable


def limpiar_texto(valor: Any, maximo: int) -> str:
    if valor is None:
        return ""
    texto = valor if isinstance(valor, str) else str(valor)
    return _CONTROL.sub("", texto).replace("\r\n", "\n").strip()[:maximo]


def cuerpo_error(error: ErrorApi) -> dict:
    """Solo la parte `error`, la misma que viaja en el evento del stream."""
    codigo = error.codigo if error.codigo in CODIGOS_ERROR else "backend"
    return {
        "codigo": codigo,
        "mensaje": limpiar_texto(error.mensaje, 200) or MENSAJES_ERROR[codigo],
        "detalle": limpiar_texto(error.detalle, 200),
        "reintentable": bool(error.reintentable),
    }


def respuesta_error(error: ErrorApi, id_solicitud: str, backend: str = "") -> dict:
    return {
        "ok": False,
        "error": cuerpo_error(error),
        "meta": {"version": VERSION, "backend": limpiar_texto(backend, 40), "id": limpiar_texto(id_solicitud, 40)},
    }
