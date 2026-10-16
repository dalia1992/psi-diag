import json
import pathlib
import re

from psi_diag.traduccion import ETIQUETAS_HERRAMIENTAS, PASOS, detalle_legible, frase_herramienta
from psi_diag.traza import parsear_contenido

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
        "conexion": {},
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
    planas = [l if isinstance(l, str) else f"{l['negrita']} {l['texto']}" for l in resultado["lineas"]]
    return [resultado["resumen"], *planas]


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
    assert "psicología clínica" in texto
    assert not re.search(r"guardrail|umbral|probabilidad|%", texto, re.IGNORECASE)


def test_proteccion_muestra_el_texto_anonimizado_sin_valores_originales():
    resultado = detalle_legible("proteccion", _datos_por_paso()["proteccion"])
    assert resultado["lineas"][-1] == "Paciente: [PER_1], mujer de 34 años, vive en [LOC_1] y trabaja en [ORG_1]. [PER_2] es su hermana. [PER_1] refiere tristeza casi todos los días."
    texto = " ".join(_textos(resultado))
    for original in ("Laura", "Mendoza", "Guadalajara", "Banorte", "Xiomara"):
        assert original not in texto


def test_proteccion_conserva_los_saltos_de_linea_y_recorta_el_texto_largo():
    anon = "\n".join(f"[PER_1] línea {i}" for i in range(100))
    lineas = detalle_legible("proteccion", {"texto_anon": anon})["lineas"]
    assert lineas[-1] == "… (texto recortado)"
    assert len([linea for linea in lineas if "línea" in linea]) == 40
    largo = detalle_legible("proteccion", {"texto_anon": "[PER_1] " + "x" * 5000})["lineas"]
    assert largo[-1] == "… (texto recortado)"
    assert sum(len(linea) for linea in largo[1:-1]) <= 4000


def test_proteccion_sin_marcadores_muestra_el_texto_para_que_se_revise():
    resultado = detalle_legible("proteccion", {"texto_anon": "Se siente triste desde hace dos meses."})
    assert "No se detectaron datos personales" in resultado["resumen"]
    assert resultado["lineas"] == ["Se siente triste desde hace dos meses."]


def test_el_detalle_de_sintomas_pone_mayuscula_inicial_en_cada_item():
    datos = {"sintomas": {"cognitivos": ["dificultad para concentrarse", "olvidos frecuentes"], "emocionales": ["tristeza"],
                          "conductuales": [], "afectacion_social": [], "temporalidad": "4 meses",
                          "datos_faltantes": ["antecedentes familiares", "severidad"]}}
    lineas = detalle_legible("sintomas", datos)["lineas"]
    assert {"negrita": "Cognitivos:", "texto": "Dificultad para concentrarse; Olvidos frecuentes"} in lineas
    assert {"negrita": "Emocionales:", "texto": "Tristeza"} in lineas
    assert {"negrita": "Duración:", "texto": "4 meses"} in lineas
    assert {"negrita": "Por recabar:", "texto": "Antecedentes familiares; Severidad"} in lineas
    assert all(set(l) == {"negrita", "texto"} for l in lineas)


def test_el_detalle_de_cie11_marca_el_codigo_en_negrita_y_capitaliza_el_titulo():
    datos = {"candidatos": [{"codigo": "6A70", "titulo": "trastorno depresivo de episodio único", "url": "https://icd.who.int/x"}]}
    lineas = detalle_legible("cie11", datos)["lineas"]
    assert {"negrita": "6A70", "texto": "· Trastorno depresivo de episodio único"} in lineas
