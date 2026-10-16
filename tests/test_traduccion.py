import json
import pathlib
import re

from poc_psico.traduccion import ETIQUETAS_HERRAMIENTAS, PASOS, detalle_legible, frase_herramienta
from poc_psico.traza import parsear_contenido

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
PROHIBIDOS = re.compile(r"icd11_|uri_api|guardrail|traza|tool|http://id\.who\.int", re.IGNORECASE)

# Datos personales originales: solo aparecen en el mapa de placeholders, nunca deben salir en el detalle.
ORIGINALES = {"[PER_1]": "Laura Mendoza Ríos", "[LOC_1]": "Guadalajara", "[ORG_1]": "Banorte", "[PER_2]": "Xiomara"}
TEXTO_ANON = (
    "Paciente: [PER_1], mujer de 34 años, vive en [LOC_1] y trabaja en [ORG_1]. "
    "[PER_2] es su hermana. [PER_1] refiere tristeza casi todos los días."
)


def _leer(nombre):
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def _traza_desde_fixtures():
    """Traza con la forma de extraer_traza, construida con las respuestas reales grabadas en fixtures."""
    return [
        {"herramienta": f["tool"], "input": f["args"], "resultado": parsear_contenido(f["content"]), "error": False}
        for f in (_leer(n) for n in ("mms_depresion.json", "criterios_depresion.json", "sintomas_tristeza.json", "fundacion_depresion.json"))
    ]


def _datos_por_paso():
    """Estado parcial del grafo para cada paso, con datos reales de los fixtures."""
    candidatos = [
        {
            "codigo": "6A70",
            "titulo": "Trastorno depresivo de episodio único",
            "url": "https://icd.who.int/browse/2024-01/mms/es#1001",
            "definicion": "Episodio depresivo de al menos dos semanas.",
            "inclusiones": [],
            "exclusiones": [],
        }
    ]
    return {
        "lectura": {"texto_ocr": "Paciente: Laura Mendoza Ríos, mujer de 34 años.\nVive en Guadalajara."},
        "proteccion": {"texto_anon": TEXTO_ANON, "mapa": ORIGINALES},
        "verificacion": {"prob_clinico": 0.97, "continuar": True},
        "sintomas": {
            "sintomas": {
                "cognitivos": ["dificultad para concentrarse"],
                "emocionales": ["tristeza casi todos los días", "sentimientos de culpa"],
                "conductuales": ["insomnio de conciliación"],
                "afectacion_social": ["falta al trabajo con frecuencia"],
                "temporalidad": "dos meses",
                "datos_faltantes": ["severidad de los síntomas"],
            }
        },
        "cie11": {
            "candidatos": candidatos,
            "alternativas": [{"codigo": "6A71", "titulo": "Trastorno depresivo recurrente", "url": "https://icd.who.int/x"}],
            "traza_tools": _traza_desde_fixtures(),
        },
        "guias": {"guias": [{"tipo": "imss", "titulo": "Guía de depresión", "url": "https://www.imss.gob.mx/x", "cita": "..."}]},
        "reporte": {"reporte_datos": {"hipotesis": candidatos, "datos_faltantes": ["duración"], "pruebas": []}},
    }


def _textos(resultado):
    return [resultado["resumen"], *resultado["lineas"]]


def test_ninguna_frase_expone_nombres_tecnicos():
    datos = _datos_por_paso()
    textos = [paso.titulo for paso in PASOS]
    for paso in PASOS:
        textos += _textos(detalle_legible(paso.id, datos[paso.id]))
    textos += list(ETIQUETAS_HERRAMIENTAS.values())
    textos += [frase_herramienta(h) for h in ETIQUETAS_HERRAMIENTAS]
    for texto in textos:
        assert not PROHIBIDOS.search(texto), texto


def test_herramienta_desconocida_usa_frase_generica():
    assert frase_herramienta("icd11_herramienta_inexistente") == "Consultando la CIE-11…"
    assert frase_herramienta("icd11_buscar_sintomas_y_signos") == "Buscando por síntomas y signos en la CIE-11"
    assert frase_herramienta("icd11_buscar_codigo_mms") == "Obteniendo el código CIE-11"
    assert frase_herramienta("icd11_buscar_fundacion") == "Buscando el trastorno en la CIE-11"
    assert frase_herramienta("icd11_obtener_criterios_clinicos") == "Revisando los criterios clínicos"


def test_proteccion_cuenta_marcadores_sin_valores_originales():
    resultado = detalle_legible("proteccion", _datos_por_paso()["proteccion"])
    texto = " ".join(_textos(resultado))
    assert "[PER_1]" in texto and "[LOC_1]" in texto and "[ORG_1]" in texto
    for original in ORIGINALES.values():
        assert original not in texto
    for original in ("Laura", "Mendoza", "Guadalajara", "Banorte", "Xiomara"):
        assert original not in texto
    linea_personas = next(linea for linea in resultado["lineas"] if linea.startswith("Personas"))
    assert "2" in linea_personas


def test_lectura_muestra_el_texto_leido():
    texto = "Paciente con tristeza.\n\nDuerme poco desde hace dos meses."
    resultado = detalle_legible("lectura", {"texto_ocr": texto})
    assert resultado["lineas"] == ["Paciente con tristeza.", "Duerme poco desde hace dos meses."]
    assert "revisa que sea correcto" in resultado["resumen"]


def test_lectura_recorta_texto_largo_con_aviso():
    por_lineas = detalle_legible("lectura", {"texto_ocr": "\n".join(f"Línea {i}" for i in range(100))})
    assert len(por_lineas["lineas"]) == 41
    assert por_lineas["lineas"][-1] == "… (texto recortado)"

    por_caracteres = detalle_legible("lectura", {"texto_ocr": "x" * 5000})
    *cuerpo, aviso = por_caracteres["lineas"]
    assert sum(len(linea) for linea in cuerpo) <= 4000
    assert aviso == "… (texto recortado)"


def test_verificacion_texto_no_clinico_explica_en_lenguaje_claro():
    resultado = detalle_legible("verificacion", {"prob_clinico": 0.02, "continuar": False})
    texto = " ".join(_textos(resultado))
    assert "no parece" in texto
    assert "caso clínico" in texto
    assert not re.search(r"guardrail|umbral|probabilidad|%", texto, re.IGNORECASE)
