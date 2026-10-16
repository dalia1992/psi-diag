"""Avance en vivo dentro de un paso: eventos `detalle` que el flujo emite mientras el paso todavía corre.

`ejecutar_eventos` registra un emisor en una variable de contexto; el código que corre dentro de un paso (la búsqueda
CIE-11, las guías) llama a `detalle()` sin conocer el transporte. Sin emisor registrado no hace nada.
Con `clave`, la pantalla actualiza la línea que ya tenía esa clave en lugar de agregar otra."""
from contextvars import ContextVar
from typing import Callable

_emisor: ContextVar[Callable[[dict], None] | None] = ContextVar("emisor_detalle", default=None)


def registrar_emisor(emisor: Callable[[dict], None] | None) -> None:
    """Solo vale para la tarea actual y las que cree después (cada tarea tiene su copia del contexto): no hace falta soltarlo."""
    _emisor.set(emisor)


def hay_emisor() -> bool:
    return _emisor.get() is not None


def detalle(paso: str, texto: str, negrita: str = "", clave: str = "") -> None:
    """Línea nueva (o actualizada, si lleva `clave`) en el detalle del paso. Solo texto ya anonimizado o sin datos del caso."""
    emisor = _emisor.get()
    if emisor is None:
        return
    linea: dict | str = {"negrita": negrita, "texto": texto} if negrita else texto
    evento = {"tipo": "detalle", "paso": paso, "linea": linea}
    if clave:
        evento["clave"] = clave
    emisor(evento)
