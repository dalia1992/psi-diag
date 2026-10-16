import json
from datetime import date

import pytest

from poc_psico.errores import FlujoDetenido
from poc_psico.esquemas import HipotesisRedactada, PruebaSugerida, ReporteClinico
from poc_psico.grafo import Componentes, ejecutar
from tests.helpers import mensajes_con_error, mensajes_exitosos, mensajes_sin_resultados

ENTRADA = "Laura Mendoza, mujer de 34 años, vive en Guadalajara. Refiere tristeza y falta al trabajo."


class Espia:
    """Registra lo que recibe cada componente, para comprobar qué viaja a servicios externos."""

    def __init__(self):
        self.recibido = []
        self.llamadas = {"guardrail": 0, "extraer": 0, "busqueda_cie11": 0, "redactar": 0}

    def registrar(self, nombre, *args):
        self.llamadas[nombre] += 1
        self.recibido.append(json.dumps(args, default=str, ensure_ascii=False))


def construir(espia=None, **sobre):
    espia = espia or Espia()

    def ner(texto):
        ents = []
        for fragmento, tipo in (("Laura Mendoza", "PER"), ("Guadalajara", "LOC")):
            if fragmento in texto:
                i = texto.index(fragmento)
                ents.append({"entity_group": tipo, "start": i, "end": i + len(fragmento)})
        return ents

    def guardrail(texto):
        espia.registrar("guardrail", texto)
        return 0.95

    def extraer(texto):
        espia.registrar("extraer", texto)
        return {"paciente_ref": "[PER_1]", "edad": 34, "sexo": "femenino", "cognitivos": [], "emocionales": ["tristeza"],
                "conductuales": [], "afectacion_social": ["faltas al trabajo"], "temporalidad": None,
                "datos_faltantes": ["Duración de los síntomas"]}

    async def agente(sintomas):
        espia.registrar("busqueda_cie11", sintomas)
        return mensajes_exitosos()

    def redactar(sintomas, candidatos, alternativas, notas, guias=None):
        espia.registrar("redactar", sintomas, candidatos, alternativas, notas)
        espia.guias_al_redactor = guias
        return ReporteClinico(hipotesis=[HipotesisRedactada(codigo="6A70", justificacion="Tristeza persistente.")],
                              datos_faltantes=["Duración"])

    valores = dict(ner=ner, guardrail=guardrail, extraer=extraer, busqueda_cie11=agente, redactar=redactar, umbral=0.5,
                   fecha=lambda: date(2026, 10, 15))
    valores.update(sobre)
    return Componentes(**valores), espia


async def test_flujo_completo_ok_con_codigo_liga_y_latencias():
    c, _ = construir()
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "ok"
    assert r["rondas_busqueda_cie11"] == 2
    assert [x["codigo"] for x in r["candidatos"]] == ["6A70"]
    assert "`6A70`" in r["reporte_md"] and "Abrir en el navegador OMS" in r["reporte_md"]
    assert {"anonimizar", "guardrail", "extraer", "busqueda_cie11", "reporte"} <= set(r["latencias"])


async def test_los_nombres_no_llegan_a_ningun_componente_externo_ni_al_resultado():
    c, espia = construir()
    r = await ejecutar(ENTRADA, c)
    for recibido in espia.recibido:
        assert "Laura" not in recibido and "Mendoza" not in recibido and "Guadalajara" not in recibido
    sin_reporte = json.dumps({k: v for k, v in r.items() if k != "reporte_md"}, default=str, ensure_ascii=False)
    assert "Laura" not in sin_reporte and "Guadalajara" not in sin_reporte
    assert "[PER_1]" in espia.recibido[0]  # el guardrail ve el texto anonimizado


async def test_el_nombre_se_reinserta_al_final_en_el_reporte():
    c, _ = construir()
    r = await ejecutar(ENTRADA, c)
    assert "Paciente: Laura Mendoza" in r["reporte_md"]
    assert "[PER_1]" not in r["reporte_md"]


async def test_placeholder_inventado_se_deja_y_se_advierte():
    c, _ = construir(redactar=lambda s, ca, al, n, g=None: ReporteClinico(
        hipotesis=[HipotesisRedactada(codigo="6A70", justificacion="Según [PER_9] hay tristeza.")]))
    r = await ejecutar(ENTRADA, c)
    assert "[PER_9]" in r["reporte_md"]
    assert any("[PER_9]" in a for a in r["advertencias"])


async def test_entrada_vacia_es_error_sin_llamar_a_nada():
    c, espia = construir()
    r = await ejecutar("   ", c)
    assert r["estado_final"] == "error" and "vacía" in r["razon"]
    assert sum(espia.llamadas.values()) == 0


async def test_guardrail_bajo_el_umbral_termina_fuera_de_alcance_sin_llamar_a_nodos_posteriores():
    c, espia = construir(guardrail=lambda t: 0.1)
    r = await ejecutar("Receta de pan amasado", c)
    assert r["estado_final"] == "fuera_de_alcance"
    assert r["rondas_busqueda_cie11"] == 0 and r["reporte_md"] == ""
    assert espia.llamadas["extraer"] == espia.llamadas["busqueda_cie11"] == espia.llamadas["redactar"] == 0


async def test_falla_del_guardrail_detiene_el_flujo_y_no_deja_pasar():
    def guardrail(texto):
        raise FlujoDetenido("Decisions API caída")

    c, espia = construir(guardrail=guardrail)
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "error" and "Decisions API caída" in r["razon"]
    assert espia.llamadas["extraer"] == 0


async def test_extractor_sin_sintomas_detiene_el_flujo():
    sin_sintomas = lambda t: {"cognitivos": [], "emocionales": [], "conductuales": [], "afectacion_social": []}
    c, espia = construir(extraer=sin_sintomas)
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "error" and "síntomas" in r["razon"]
    assert espia.llamadas["busqueda_cie11"] == 0


async def test_falla_del_agente_detiene_el_flujo():
    async def agente(sintomas):
        raise FlujoDetenido("El agente alcanzó el tope de 12 pasos")

    c, espia = construir(busqueda_cie11=agente)
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "error" and "tope" in r["razon"]
    assert espia.llamadas["redactar"] == 0


async def test_ninguna_hipotesis_con_codigo_detiene_el_flujo():
    async def agente(sintomas):
        return mensajes_sin_resultados()

    c, espia = construir(busqueda_cie11=agente)
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "error" and "ninguna hipótesis" in r["razon"].lower()
    assert espia.llamadas["redactar"] == 0


async def test_si_las_tools_fallan_la_razon_lo_dice():
    async def agente(sintomas):
        return mensajes_con_error()

    c, _ = construir(busqueda_cie11=agente)
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "error" and "error" in r["razon"].lower()


async def test_el_reporte_con_solo_codigos_inventados_detiene_el_flujo():
    c, _ = construir(redactar=lambda s, ca, al, n, g=None: ReporteClinico(
        hipotesis=[HipotesisRedactada(codigo="9Z99", justificacion="inventada")]))
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "error" and "hipótesis" in r["razon"].lower()


async def test_una_excepcion_inesperada_se_reporta_como_error_y_no_se_propaga():
    def extraer(texto):
        raise RuntimeError("429 rate limit")

    c, _ = construir(extraer=extraer)
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "error" and "RuntimeError" in r["razon"] and "429" in r["razon"]


async def test_cuando_no_hay_hipotesis_la_razon_dice_que_hizo_el_agente():
    async def agente(sintomas):
        return mensajes_sin_resultados()

    c, _ = construir(busqueda_cie11=agente)
    r = await ejecutar(ENTRADA, c)
    assert "1 ronda" in r["razon"] and "icd11_buscar_codigo_mms" in r["razon"]
    assert "No hay categoría para ese término" in r["razon"]  # último mensaje del agente


FOTO = "/tmp/vineta.jpg"


async def test_una_foto_se_lee_con_ocr_y_el_texto_leido_se_anonimiza_antes_de_cualquier_servicio_externo():
    espia = Espia()
    c, _ = construir(espia, ocr=lambda ruta: ENTRADA)
    r = await ejecutar(FOTO, c)
    assert r["estado_final"] == "ok", r["razon"]
    assert r["texto_ocr"] == ENTRADA
    assert "[PER_1]" in r["texto_anon"]
    externo = " ".join(espia.recibido)
    assert "Laura" not in externo and "Mendoza" not in externo and "Guadalajara" not in externo
    assert "Laura Mendoza" in r["reporte_md"]
    assert "ocr" in r["latencias"]


async def test_con_texto_no_se_usa_el_ocr_y_texto_ocr_queda_vacio():
    def ocr(ruta):
        raise AssertionError("no debe llamarse con texto")

    c, _ = construir(ocr=ocr)
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "ok"
    assert r["texto_ocr"] is None


async def test_si_el_ocr_falla_el_flujo_se_detiene_sin_llamar_a_nada_mas():
    def ocr(ruta):
        raise FlujoDetenido("OCR no disponible")

    c, espia = construir(ocr=ocr)
    r = await ejecutar(FOTO, c)
    assert r["estado_final"] == "error" and "OCR no disponible" in r["razon"]
    assert espia.llamadas == {"guardrail": 0, "extraer": 0, "busqueda_cie11": 0, "redactar": 0}


async def test_un_archivo_sin_ocr_configurado_se_explica_en_vez_de_tratarse_como_texto():
    c, espia = construir()
    r = await ejecutar(FOTO, c)
    assert r["estado_final"] == "error" and "OCR" in r["razon"]
    assert espia.llamadas["guardrail"] == 0


async def test_ocr_que_devuelve_texto_no_clinico_termina_fuera_de_alcance():
    c, _ = construir(ocr=lambda ruta: "Receta de pan amasado", guardrail=lambda t: 0.1)
    r = await ejecutar(FOTO, c)
    assert r["estado_final"] == "fuera_de_alcance"
    assert r["texto_ocr"] == "Receta de pan amasado"


GUIAS = [{"titulo": "Guía de depresión", "url": "https://www.apa.org/depression-guideline", "cita": "Resumen.", "tipo": "apa"}]


async def test_las_guias_llegan_al_reporte_y_al_resultado():
    c, espia = construir(guias=lambda candidatos, sintomas: GUIAS)
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "ok" and r["guias"] == GUIAS
    assert "https://www.apa.org/depression-guideline" in r["reporte_md"]
    assert "guias" in r["latencias"]


async def test_la_busqueda_de_guias_solo_recibe_candidatos_sin_datos_del_paciente():
    recibido = []
    c, _ = construir(guias=lambda candidatos, sintomas: recibido.append(json.dumps(candidatos, ensure_ascii=False)) or [])
    await ejecutar(ENTRADA, c)
    assert recibido and "Laura" not in recibido[0] and "Guadalajara" not in recibido[0]


async def test_si_la_busqueda_de_guias_falla_el_reporte_sale_sin_guias_y_con_advertencia():
    def guias(candidatos, sintomas):
        raise FlujoDetenido("OpenRouter respondió 402")

    c, _ = construir(guias=guias)
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "ok" and r["guias"] == []
    assert any("402" in a for a in r["advertencias"])
    assert "Guías clínicas" not in r["reporte_md"]


async def test_sin_componente_de_guias_el_flujo_no_cambia():
    c, _ = construir()
    r = await ejecutar(ENTRADA, c)
    assert r["estado_final"] == "ok" and r["guias"] == [] and "Guías clínicas" not in r["reporte_md"]
    assert "guias" not in r["latencias"]


async def test_el_redactor_recibe_las_guias_con_id_y_las_pruebas_respaldadas_llevan_su_liga():
    guias = [{"id": "G1", "titulo": "Evaluación", "url": "https://www.apa.org/e", "cita": "", "tipo": "imss",
              "extracto": "Se recomienda el PHQ-9 para medir severidad."}]

    def redactar(s, ca, al, n, g=None):
        redactar.recibidas = g
        return ReporteClinico(
            hipotesis=[HipotesisRedactada(codigo="6A70", justificacion="Tristeza.")],
            pruebas=[PruebaSugerida(nombre="PHQ-9", motivo="Severidad", fuente_id="G1", cita_textual="el PHQ-9"),
                     PruebaSugerida(nombre="Inventada", motivo="x", fuente_id="G1", cita_textual="no está en la guía")])

    c, _ = construir(guias=lambda candidatos, sintomas: guias, redactar=redactar)
    r = await ejecutar(ENTRADA, c)
    assert [x["id"] for x in redactar.recibidas] == ["G1"]
    assert "[Evaluación](https://www.apa.org/e)" in r["reporte_md"]
    assert any("Inventada" in a for a in r["advertencias"])
