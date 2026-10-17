"""Frases para la persona usuaria: pasos del avance y equivalencias de las herramientas. Nunca muestra nombres técnicos."""
import re
from dataclasses import dataclass

from .reporte import ETIQUETAS_GUIAS, mayuscula_inicial


@dataclass(frozen=True)
class Paso:
    id: str
    titulo: str


PASOS = (
    Paso("conexion", "Conexión con los servicios"),
    Paso("lectura", "Lectura del archivo"),
    Paso("proteccion", "Protección de datos personales"),
    Paso("verificacion", "Verificación del texto"),
    Paso("sintomas", "Identificación de síntomas"),
    Paso("cie11", "Búsqueda de diagnósticos en la CIE-11"),
    Paso("guias", "Búsqueda de guías clínicas (IMSS, APA, OMS)"),
    Paso("reporte", "Redacción del reporte"),
)

ETIQUETAS_HERRAMIENTAS = {
    "icd11_buscar_fundacion": "Buscando el trastorno en la CIE-11",
    "icd11_buscar_codigo_mms": "Obteniendo el código CIE-11",
    "icd11_obtener_criterios_clinicos": "Revisando los criterios clínicos",
    "icd11_buscar_sintomas_y_signos": "Buscando por síntomas y signos en la CIE-11",
}
FRASE_GENERICA = "Consultando la CIE-11…"
MAX_TEXTO_CASO = 8000  # el mismo tope del campo de texto del caso
MAX_LINEAS_LECTURA = 40
MAX_CARACTERES_LECTURA = 4000
TEXTO_RECORTADO = "… (texto recortado)"

_MARCADOR = re.compile(r"\[(?:PER|LOC|ORG)_\d+\]")
_TIPOS_MARCADOR = (("PER", "Personas"), ("LOC", "Lugares"), ("ORG", "Organizaciones"))
_CATEGORIAS_SINTOMAS = (
    ("cognitivos", "Cognitivos"),
    ("emocionales", "Emocionales"),
    ("conductuales", "Conductuales"),
    ("fisiologicos", "Fisiológicos"),
    ("afectacion_social", "Afectación social"),
)
_ANTECEDENTES_MEDICOS = (
    ("condiciones_medicas", "Enfermedades conocidas"),
    ("medicamentos", "Medicamentos"),
)


def frase_herramienta(nombre: str) -> str:
    return ETIQUETAS_HERRAMIENTAS.get(nombre, FRASE_GENERICA)


def _recortar(texto: str) -> list:
    """Líneas no vacías del texto, recortadas a MAX_LINEAS_LECTURA líneas y MAX_CARACTERES_LECTURA caracteres."""
    lineas, total, recortado = [], 0, False
    for linea in (texto or "").splitlines():
        if not linea.strip():
            continue
        if len(lineas) == MAX_LINEAS_LECTURA:
            recortado = True
            break
        espacio = MAX_CARACTERES_LECTURA - total
        if len(linea) > espacio:
            lineas.append(linea[:espacio])
            recortado = True
            break
        lineas.append(linea)
        total += len(linea)
    if recortado:
        lineas.append(TEXTO_RECORTADO)
    return lineas


def _lectura(datos: dict) -> dict:
    """Muestra el texto leído del archivo para que la persona revise el OCR; se recorta si es muy largo."""
    texto = (datos.get("texto_ocr") or "").strip()
    # `texto` completo (hasta el máximo que admite el campo del caso): la pantalla lo usa para «Editar el texto leído» si luego algo falla.
    return {"resumen": "Texto leído del archivo (revisa que sea correcto)", "lineas": _recortar(texto), "texto": texto[:MAX_TEXTO_CASO]}


def _proteccion(datos: dict) -> dict:
    # Solo se lee el texto anonimizado (marcadores en lugar de los valores originales): el mapa de valores no se usa aquí.
    # Va solo al navegador de la propia persona; así puede ver qué se envió a los servicios externos.
    anonimo = datos.get("texto_anon") or ""
    marcadores = list(dict.fromkeys(_MARCADOR.findall(anonimo)))
    total = len(marcadores)
    if not total:
        return {"resumen": "No se detectaron datos personales que ocultar (revisa el texto que se envió a los servicios externos)", "lineas": _recortar(anonimo)}
    lineas = []
    for tipo, etiqueta in _TIPOS_MARCADOR:
        del_tipo = [m for m in marcadores if m.startswith(f"[{tipo}_")]
        if del_tipo:
            lineas.append(f"{etiqueta}: {len(del_tipo)} ({', '.join(del_tipo)})")
    lineas += _recortar(anonimo)
    return {"resumen": f"Datos personales ocultados antes del análisis: {total} (la detección automática puede fallar: revisa el texto que se envió a los servicios externos)", "lineas": lineas}


def _verificacion(datos: dict) -> dict:
    if datos.get("continuar"):
        return {"resumen": "El texto describe un caso clínico", "lineas": []}
    return {
        "resumen": "El texto no parece ser un caso de psicología clínica, así que no se analiza",
        "lineas": ["Describe el caso con síntomas, duración y cómo afecta la vida diaria para continuar."],
    }


def _linea_con_negrita(negrita: str, texto: str) -> dict:
    """Línea del detalle con una parte en negrita (la pantalla la dibuja con <strong>, nunca como HTML)."""
    return {"negrita": negrita, "texto": texto}


def _sintomas(datos: dict) -> dict:
    sintomas = datos.get("sintomas") or {}
    lineas = []
    for clave, etiqueta in _CATEGORIAS_SINTOMAS:
        items = sintomas.get(clave) or []
        if items:
            lineas.append(_linea_con_negrita(f"{etiqueta}:", "; ".join(mayuscula_inicial(i) for i in items)))
    for clave, etiqueta in _ANTECEDENTES_MEDICOS:
        items = sintomas.get(clave) or []
        if items:
            lineas.append(_linea_con_negrita(f"{etiqueta}:", "; ".join(mayuscula_inicial(i) for i in items)))
    if sintomas.get("temporalidad"):
        lineas.append(_linea_con_negrita("Duración:", sintomas["temporalidad"]))
    if sintomas.get("datos_faltantes"):
        lineas.append(_linea_con_negrita("Por recabar:", "; ".join(mayuscula_inicial(i) for i in sintomas["datos_faltantes"])))
    total = sum(len(sintomas.get(clave) or []) for clave, _ in _CATEGORIAS_SINTOMAS)
    return {"resumen": f"Síntomas identificados: {total}", "lineas": lineas}


def _cie11(datos: dict) -> dict:
    candidatos = datos.get("candidatos") or []
    alternativas = datos.get("alternativas") or []
    lineas = [_linea_con_negrita(c["codigo"], f"· {mayuscula_inicial(c['titulo'])}") for c in candidatos]
    if alternativas:
        lineas.append(f"Otros códigos relacionados: {len(alternativas)}")
    for herramienta in dict.fromkeys(t["herramienta"] for t in datos.get("traza_tools") or []):
        lineas.append(frase_herramienta(herramienta))
    resumen = (
        f"Diagnósticos candidatos en la CIE-11: {len(candidatos)}"
        if candidatos else "No se encontraron diagnósticos en la CIE-11"
    )
    return {"resumen": resumen, "lineas": lineas}


def _guias(datos: dict) -> dict:
    guias = datos.get("guias") or []
    lineas = [f"{ETIQUETAS_GUIAS.get(g.get('tipo'), 'Guía clínica')}: {g['titulo']}" for g in guias]
    return {"resumen": f"Guías clínicas consultadas: {len(guias)}", "lineas": lineas}


def _reporte(datos: dict) -> dict:
    reporte = datos.get("reporte_datos") or {}
    lineas = [
        f"Hipótesis: {len(reporte.get('hipotesis') or [])}",
        f"Pruebas sugeridas: {len(reporte.get('pruebas') or [])}",
        f"Información por recabar: {len(reporte.get('datos_faltantes') or [])}",
    ] if reporte else []
    return {"resumen": "Reporte redactado", "lineas": lineas}


_DETALLES = {
    "conexion": lambda datos: {"resumen": "Servicios listos", "lineas": []},
    "lectura": _lectura,
    "proteccion": _proteccion,
    "verificacion": _verificacion,
    "sintomas": _sintomas,
    "cie11": _cie11,
    "guias": _guias,
    "reporte": _reporte,
}


def detalle_legible(paso_id: str, datos: dict) -> dict:
    """Resumen y líneas para «Ver qué encontró». `datos` es el estado parcial del grafo; solo se usan
    marcadores y conteos de datos personales, nunca sus valores originales."""
    return _DETALLES[paso_id](datos or {})
