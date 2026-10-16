import json
import pathlib

import pytest

from poc_psico.esquemas import SintomasPaciente
from poc_psico.traza import (
    contar_errores,
    contar_rondas,
    ensamblar_candidatos,
    extraer_traza,
    parsear_contenido,
    texto_final,
)
from tests.helpers import BASE, CRITERIOS_6A70, MMS_DEPRESION, bloque, mensajes_con_error, mensajes_exitosos, mensajes_sin_resultados

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_parsear_contenido_acepta_bloques_cadena_texto_y_dict():
    assert parsear_contenido(bloque({"a": 1})) == {"a": 1}
    assert parsear_contenido('{"a": 1}') == {"a": 1}
    assert parsear_contenido("Connection refused") == {"texto": "Connection refused"}
    assert parsear_contenido({"a": 1}) == {"a": 1}


def test_extraer_traza_une_llamada_y_resultado():
    traza = extraer_traza(mensajes_exitosos())
    assert [p["herramienta"] for p in traza] == ["icd11_buscar_codigo_mms", "icd11_obtener_criterios_clinicos"]
    assert traza[0]["input"] == {"query": {"termino": "trastorno depresivo"}}
    assert traza[0]["resultado"]["resultados_mms"][0]["codigo_oficial"] == "6A70"
    assert traza[0]["error"] is False


def test_candidatos_solo_con_codigo_y_criterios_alternativas_el_resto():
    candidatos, alternativas = ensamblar_candidatos(extraer_traza(mensajes_exitosos()))
    assert candidatos == [
        {
            "codigo": "6A70",
            "titulo": "Trastorno depresivo de episodio único",
            "url": "https://icd.who.int/browse/2024-01/mms/es#1001",
            "definicion": "Episodio depresivo único de al menos dos semanas.",
            "inclusiones": ["Depresión mayor de episodio único"],
            "exclusiones": [],
        }
    ]
    assert alternativas == [
        {
            "codigo": "6A71",
            "titulo": "Trastorno depresivo recurrente",
            "url": "https://icd.who.int/browse/2024-01/mms/es#1002",
        }
    ]


def test_busqueda_vacia_no_es_error_y_no_da_candidatos():
    traza = extraer_traza(mensajes_sin_resultados())
    assert traza[0]["error"] is False
    assert ensamblar_candidatos(traza) == ([], [])


def test_error_de_tool_se_marca_y_no_da_candidatos():
    mensajes = mensajes_con_error()
    traza = extraer_traza(mensajes)
    assert traza[0]["error"] is True
    assert ensamblar_candidatos(traza) == ([], [])
    assert contar_errores(mensajes) == 1


def test_criterios_sin_codigo_mms_no_son_candidatos():
    traza = [
        {"herramienta": "icd11_obtener_criterios_clinicos", "input": {}, "error": False,
         "resultado": {**CRITERIOS_6A70, "uri": BASE + "9999"}},
    ]
    assert ensamblar_candidatos(traza) == ([], [])


def test_une_criterios_y_mms_por_el_id_final_aunque_cambie_el_prefijo_de_la_uri():
    criterios = {**CRITERIOS_6A70, "uri": "https://id.who.int/icd/release/11/2025-01/mms/1001/"}
    traza = [
        {"herramienta": "icd11_buscar_codigo_mms", "input": {}, "error": False, "resultado": MMS_DEPRESION},
        {"herramienta": "icd11_obtener_criterios_clinicos", "input": {}, "error": False, "resultado": criterios},
    ]
    candidatos, _ = ensamblar_candidatos(traza)
    assert [c["codigo"] for c in candidatos] == ["6A70"]


def test_contar_rondas_y_texto_final():
    mensajes = mensajes_exitosos()
    assert contar_rondas(mensajes) == 2
    assert texto_final(mensajes).startswith("Hallazgos")


def test_texto_final_con_bloques():
    from langchain_core.messages import AIMessage

    assert texto_final([AIMessage(content=[{"type": "text", "text": "hola"}])]) == "hola"


def test_sintomas_hay_sintomas():
    assert SintomasPaciente().hay_sintomas() is False
    assert SintomasPaciente(emocionales=["tristeza"]).hay_sintomas() is True


@pytest.mark.skipif(not (FIXTURES / "mms_depresion.json").exists(), reason="falta el fixture del spike (Task 4)")
def test_fixtures_reales_producen_al_menos_un_candidato():
    def cargar(nombre):
        return json.loads((FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"))

    mms, criterios = cargar("mms_depresion"), cargar("criterios_depresion")
    traza = [
        {"herramienta": "icd11_buscar_codigo_mms", "input": mms["args"], "error": False,
         "resultado": parsear_contenido(mms["content"])},
        {"herramienta": "icd11_obtener_criterios_clinicos", "input": criterios["args"], "error": False,
         "resultado": parsear_contenido(criterios["content"])},
    ]
    candidatos, _ = ensamblar_candidatos(traza)
    assert len(candidatos) == 1
    assert candidatos[0]["codigo"] and candidatos[0]["url"].startswith("http")


def test_uris_con_sufijo_no_colisionan_entre_si():
    """Caso real del MCP: .../mms/1563440232 y .../mms/1563440232/unspecified son entidades distintas."""
    mms = {"resultados_mms": [
        {"codigo_oficial": "6A7", "titulo": "Grupo", "uri_api": BASE + "1563440232", "uri_navegable": "https://x/1"},
        {"codigo_oficial": "6A7Z", "titulo": "Sin especificación", "uri_api": BASE + "1563440232/unspecified", "uri_navegable": "https://x/2"},
        {"codigo_oficial": "6A72", "titulo": "Distímico", "uri_api": BASE + "810797047", "uri_navegable": "https://x/3"},
        {"codigo_oficial": "6A71.Z", "titulo": "Recurrente sin especificación", "uri_api": BASE + "1194756772/unspecified", "uri_navegable": "https://x/4"},
    ]}
    criterios = {"uri": BASE + "1563440232/unspecified", "titulo": "Sin especificación", "definicion": "d",
                 "inclusiones": [], "exclusiones": []}
    traza = [
        {"herramienta": "icd11_buscar_codigo_mms", "input": {}, "error": False, "resultado": mms},
        {"herramienta": "icd11_obtener_criterios_clinicos", "input": {}, "error": False, "resultado": criterios},
    ]
    candidatos, alternativas = ensamblar_candidatos(traza)
    assert [c["codigo"] for c in candidatos] == ["6A7Z"]
    assert sorted(a["codigo"] for a in alternativas) == ["6A7", "6A71.Z", "6A72"]


def test_resumen_traza_explica_por_que_no_hay_candidatos():
    from poc_psico.traza import resumen_traza

    traza = [
        {"herramienta": "icd11_buscar_codigo_mms", "input": {}, "error": False, "resultado": MMS_DEPRESION},
        {"herramienta": "icd11_obtener_criterios_clinicos", "input": {}, "error": False,
         "resultado": {**CRITERIOS_6A70, "uri": "http://id.who.int/icd/entity/777"}},
    ]
    texto = resumen_traza(traza)
    assert "2 código(s) MMS recibidos" in texto
    assert "criterios consultados: ['777']" in texto


def test_ligas_residuales_apuntan_a_la_entidad_no_a_la_pagina_general():
    from poc_psico.traza import _url_navegable

    base = "https://icd.who.int/browse/2026-01/mms/es"
    sin_especificar = {"uri_api": "http://id.who.int/icd/release/11/2024-01/mms/1563440232/unspecified", "uri_navegable": f"{base}#unspecified"}
    otro = {"uri_api": "http://id.who.int/icd/release/11/2024-01/mms/1563440232/other", "uri_navegable": f"{base}#other"}
    normal = {"uri_api": "http://id.who.int/icd/release/11/2024-01/mms/810797047", "uri_navegable": f"{base}#810797047"}
    assert _url_navegable(sin_especificar) == f"{base}#1563440232%2Funspecified"
    assert _url_navegable(otro) == f"{base}#1563440232%2Fother"
    assert _url_navegable(normal) == f"{base}#810797047"
