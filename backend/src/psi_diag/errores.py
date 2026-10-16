"""Errores del flujo."""


class FlujoDetenido(Exception):
    """El flujo debe detenerse con un mensaje claro; nunca se continúa con datos incompletos."""
