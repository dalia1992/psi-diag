"""Anonimización con NER + reglas. El mapa de datos personales vive fuera del estado del grafo."""
import re
from typing import Callable

TIPOS = ("PER", "LOC", "ORG")
_PATRON_PLACEHOLDER = re.compile(r"\[(?:PER|LOC|ORG)_\d+\]")


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.strip().lower())


class MapaPII:
    """Asigna placeholders numerados ([PER_1]) y guarda el valor real de cada uno."""

    def __init__(self):
        self._entradas = {tipo: [] for tipo in TIPOS}  # tipo -> [[placeholder, valor]]

    def asignar(self, tipo: str, valor: str) -> str:
        tokens = set(_norm(valor).split())
        for entrada in self._entradas[tipo]:
            placeholder, previo = entrada
            tokens_previos = set(_norm(previo).split())
            # "Ana" y "Ana Torres" son la misma persona; se conserva el valor más completo.
            if tokens and tokens_previos and (tokens <= tokens_previos or tokens_previos <= tokens):
                if len(valor) > len(previo):
                    entrada[1] = valor
                return placeholder
        placeholder = f"[{tipo}_{len(self._entradas[tipo]) + 1}]"
        self._entradas[tipo].append([placeholder, valor])
        return placeholder

    def valores(self) -> dict:
        return {ph: valor for lista in self._entradas.values() for ph, valor in lista}

    def reinsertar(self, texto: str):
        valores = self.valores()
        desconocidos = []

        def _sustituir(m):
            placeholder = m.group(0)
            if placeholder in valores:
                return valores[placeholder]
            desconocidos.append(placeholder)
            return placeholder

        return _PATRON_PLACEHOLDER.sub(_sustituir, texto), desconocidos


def aplicar_entidades(texto: str, entidades: list, mapa: MapaPII) -> str:
    """Sustituye las entidades PER/LOC/ORG por placeholders, de atrás hacia adelante."""
    candidatas = []
    for e in entidades:
        tipo = e.get("entity_group") or e.get("entity", "")
        if tipo not in TIPOS:
            continue
        ini, fin = int(e["start"]), int(e["end"])
        segmento = texto[ini:fin]
        ini += len(segmento) - len(segmento.lstrip())
        fin -= len(segmento) - len(segmento.rstrip())
        if fin > ini:
            candidatas.append((ini, fin, tipo))
    candidatas.sort()

    sin_solape, ultimo_fin = [], -1
    for ini, fin, tipo in candidatas:
        if ini >= ultimo_fin:
            sin_solape.append((ini, fin, tipo))
            ultimo_fin = fin

    asignadas = [(ini, fin, mapa.asignar(tipo, texto[ini:fin])) for ini, fin, tipo in sin_solape]
    for ini, fin, placeholder in reversed(asignadas):
        texto = texto[:ini] + placeholder + texto[fin:]
    return texto


_MESES = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre"


def ocultar_fechas(texto: str) -> str:
    """Oculta fechas exactas (14/05/1978, 12 de mayo de 2026). Deja intactas las relativas."""
    texto = re.sub(r"\b(?:0?[1-9]|[12][0-9]|3[01])/(?:0?[1-9]|1[0-2])/(?:19|20)\d{2}\b", "[FECHA]", texto)
    patron_textual = rf"\b(?:0?[1-9]|[12][0-9]|3[01]) de (?:{_MESES})(?: de (?:19|20)\d{{2}})?\b"
    return re.sub(patron_textual, "[FECHA]", texto, flags=re.IGNORECASE)


def ocultar_telefonos(texto: str) -> str:
    patron = r"(?<![\w\[])(?:\d{2,3}[-\s]\d{3,4}[-\s]\d{4}|\d{2}[-\s]\d{4}[-\s]\d{4}|\d{10})(?![\w\]])"
    return re.sub(patron, "[TEL]", texto)


def ocultar_cedulas(texto: str) -> str:
    return re.sub(r"\bc[ée]dula\b[^\d\n]{0,30}\d[\d.\-]*", "[ID]", texto, flags=re.IGNORECASE)


def ocultar_correos(texto: str) -> str:
    return re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[CORREO]", texto)


def anonimizar(texto: str, ner: Callable[[str], list], mapa: MapaPII) -> str:
    """NER (personas, lugares, organizaciones) y después reglas para fechas, teléfonos, cédulas y correos."""
    resultado = aplicar_entidades(texto, ner(texto), mapa)
    for ocultar in (ocultar_fechas, ocultar_telefonos, ocultar_cedulas, ocultar_correos):
        resultado = ocultar(resultado)
    return resultado
