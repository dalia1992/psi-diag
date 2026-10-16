"""Lectura tolerante del reporte: ambos exportadores deben aguantar campos ausentes, nulos o con texto raro."""
import re
from datetime import date

NOMBRE_APP = "Ψ-DIAG con IA"
PIE = "Herramienta de apoyo; no sustituye el criterio clínico"
AZUL, LAVANDA, MENTA, FONDO = "#2F4B7C", "#8E85C2", "#5BB5A2", "#F7F6FC"
ETIQUETAS_SINTOMAS = (
    ("Cognitivos", "cognitivos"), ("Emocionales", "emocionales"),
    ("Conductuales", "conductuales"), ("Afectación social", "afectacion_social"),
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")   # XML 1.0 no admite estos caracteres
_URL = re.compile(r"^https?://[^\s\"'<>\\]{1,2000}$", re.IGNORECASE)


def texto(valor) -> str:
    if valor is None:
        return ""
    return _CONTROL.sub("", valor if isinstance(valor, str) else str(valor)).strip()


def lista(valor) -> list[str]:
    if not isinstance(valor, (list, tuple)):
        return []
    return [t for t in (texto(v) for v in valor) if t]


def dicc(valor) -> dict:
    return valor if isinstance(valor, dict) else {}


def lista_de_dicts(valor) -> list[dict]:
    return [v for v in valor if isinstance(v, dict)] if isinstance(valor, (list, tuple)) else []


def url_segura(valor) -> str:
    """Solo ligas http(s) sin caracteres que rompan el marcado; cualquier otra cosa se descarta."""
    candidata = texto(valor)
    return candidata if _URL.match(candidata) else ""


def mayuscula_inicial(valor) -> str:
    t = texto(valor)
    return t[:1].upper() + t[1:]


def fecha_iso(reporte) -> str:
    """Fecha del reporte (AAAA-MM-DD) o la de hoy si falta o no es válida."""
    try:
        return date.fromisoformat(texto(dicc(reporte).get("fecha"))[:10]).isoformat()
    except ValueError:
        return date.today().isoformat()


def datos_del_caso(reporte: dict) -> list[tuple[str, str]]:
    caso = dicc(reporte.get("caso"))
    edad = caso.get("edad")
    return [
        ("Paciente", texto(caso.get("paciente_ref")) or "No identificado"),
        ("Edad", texto(edad) if edad is not None and texto(edad) else "No indicada"),
        ("Sexo", texto(caso.get("sexo")) or "No indicado"),
        ("Temporalidad", texto(caso.get("temporalidad")) or "No indicada"),
        ("Fecha del reporte", fecha_iso(reporte)),
    ]
