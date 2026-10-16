import pytest
import requests

from poc_psico.errores import FlujoDetenido
from poc_psico.guias import (
    DecisionFuentes,
    _dominio_permitido,
    buscar_guias,
    consulta_desde_candidatos,
    crear_decisor_fuentes,
    crear_decisor_jev,
    solo_dominios,
)
from tests.helpers import RespuestaFalsa

CANDIDATOS = [
    {"codigo": "6A70", "titulo": "Trastorno depresivo de episodio único", "url": "https://icd.who.int/x"},
    {"codigo": "6B00", "titulo": "Trastorno de ansiedad generalizada", "url": "https://icd.who.int/y"},
]
SINTOMAS = {"emocionales": ["tristeza"], "datos_faltantes": ["duración", "severidad"]}


def cita(url, titulo="Guía", contenido="Resumen de la guía."):
    return {"type": "url_citation", "url_citation": {"url": url, "title": titulo, "content": contenido}}


def respuesta_con(*anotaciones):
    return RespuestaFalsa(cuerpo={"choices": [{"message": {"content": "ok", "annotations": list(anotaciones)}}]})


class PostFalso:
    """Una respuesta por búsqueda, en orden; si se pasa una sola, se repite."""

    def __init__(self, *respuestas):
        self.respuestas, self.llamadas = list(respuestas), []
        self.repetir = len(respuestas) == 1

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.llamadas.append({"url": url, "json": json, "headers": headers})
        r = self.respuestas[0] if self.repetir else self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    @property
    def dominios(self):
        return [c["json"]["plugins"][0]["include_domains"][0] for c in self.llamadas]


class Decisor:
    """Decisor falso: devuelve las fuentes indicadas y registra lo que recibió."""

    def __init__(self, fuentes=(), error=None):
        self.fuentes, self.error, self.recibido = list(fuentes), error, []

    def __call__(self, candidatos, sintomas, guias_imss):
        self.recibido.append((candidatos, sintomas, guias_imss))
        if self.error:
            raise self.error
        return DecisionFuentes(fuentes=self.fuentes, razon="porque sí")


IMSS = cita("https://www.imss.gob.mx/guiasclinicas/161GER.pdf", "GPC IMSS", "Escala de Hamilton y Beck para depresión.")
APA = cita("https://www.apa.org/depression-guideline", "Guía APA")
OMS = cita("https://www.who.int/publications/mhgap", "mhGAP")


def buscar(post, decisor=None, **kw):
    return buscar_guias(CANDIDATOS, SINTOMAS, "clave", decisor or Decisor(), post=post, **kw)


def test_la_consulta_usa_solo_titulos_de_la_cie11():
    q = consulta_desde_candidatos(CANDIDATOS)
    assert "Trastorno depresivo de episodio único" in q and "Trastorno de ansiedad generalizada" in q
    assert "6A70" not in q


def test_la_consulta_se_limita_a_los_primeros_candidatos():
    muchos = [{"codigo": f"X{i}", "titulo": f"Entidad {i}"} for i in range(10)]
    q = consulta_desde_candidatos(muchos, maximo=3)
    assert "Entidad 2" in q and "Entidad 3" not in q


@pytest.mark.parametrize("url,esperado", [
    ("https://www.apa.org/depression-guideline", True),
    ("https://apa.org/x", True),
    ("https://psychiatry.apa.org/y", True),
    ("https://apa.org.evil.com/x", False),
    ("https://notapa.org/x", False),
    ("https://example.com/apa.org", False),
    ("no es una url", False),
])
def test_dominio_permitido_acepta_el_dominio_y_sus_subdominios(url, esperado):
    assert _dominio_permitido(url, ["apa.org"]) is esperado
    assert bool(solo_dominios([cita(url)], ["apa.org"])) is esperado


def test_la_cita_se_limpia_de_encabezados_markdown_y_puntos_suspensivos():
    guias = solo_dominios([cita("https://www.apa.org/g", contenido="## GUÍA\n\n...\n\nRecomienda terapia.")], ["apa.org"])
    assert guias[0]["cita"] == "GUÍA Recomienda terapia."


def test_titulo_url_y_cita_recortada():
    largo = "x" * 1000
    guias = solo_dominios([cita("https://www.apa.org/g", "Guía de depresión", largo)], ["apa.org"])
    assert guias[0]["titulo"] == "Guía de depresión" and 0 < len(guias[0]["cita"]) <= 300


def test_siempre_busca_primero_en_el_imss_y_si_el_decisor_no_pide_mas_no_busca_en_otro_lado():
    post = PostFalso(respuesta_con(IMSS))
    decisor = Decisor([])
    guias = buscar(post, decisor)
    assert post.dominios == ["imss.gob.mx"] and [g["tipo"] for g in guias] == ["imss"]
    assert len(decisor.recibido) == 1


def test_el_decisor_recibe_candidatos_sintomas_y_lo_que_devolvio_el_imss():
    post = PostFalso(respuesta_con(IMSS))
    decisor = Decisor([])
    buscar(post, decisor)
    candidatos, sintomas, guias_imss = decisor.recibido[0]
    assert candidatos == CANDIDATOS and sintomas == SINTOMAS
    assert guias_imss[0]["titulo"] == "GPC IMSS"


def test_las_fuentes_adicionales_que_pide_el_decisor_se_buscan_en_su_dominio_con_apa_unificada():
    post = PostFalso(respuesta_con(IMSS), respuesta_con(APA), respuesta_con(OMS))
    guias = buscar(post, Decisor(["oms", "apa"]))
    assert post.dominios == ["imss.gob.mx", "apa.org", "who.int"]  # orden fijo: apa antes que oms
    assert [g["tipo"] for g in guias] == ["imss", "apa", "oms"]
    texto_apa = str(post.llamadas[1]["json"]["messages"]).lower()
    assert "evaluación" in texto_apa and "incomplet" in texto_apa and "intervenc" in texto_apa


def test_ignora_fuentes_invalidas_o_repetidas_aunque_el_decisor_se_salte_el_esquema():
    from types import SimpleNamespace

    post = PostFalso(respuesta_con(IMSS), respuesta_con(APA))
    crudo = lambda c, s, g: SimpleNamespace(fuentes=["apa", "apa", "imss", "bing"], razon="x")  # noqa: E731
    guias = buscar_guias(CANDIDATOS, SINTOMAS, "clave", crudo, post=post)
    assert post.dominios == ["imss.gob.mx", "apa.org"] and len(guias) == 2


def test_una_decision_fuera_del_esquema_deja_solo_las_guias_del_imss():
    class LLMInvalido:
        def with_structured_output(self, esquema, method=None):
            return EstructuradoFalso(ValueError("el modelo devolvió una fuente inválida"))

    post = PostFalso(respuesta_con(IMSS))
    guias = buscar_guias(CANDIDATOS, SINTOMAS, "clave", crear_decisor_fuentes(LLMInvalido()), post=post)
    assert [g["tipo"] for g in guias] == ["imss"]


def test_si_el_decisor_falla_se_conservan_las_guias_del_imss():
    post = PostFalso(respuesta_con(IMSS))
    guias = buscar(post, Decisor(error=RuntimeError("caído")))
    assert [g["tipo"] for g in guias] == ["imss"] and post.dominios == ["imss.gob.mx"]


def test_las_busquedas_restringen_el_dominio_y_ninguna_lleva_codigos_ni_datos_del_paciente():
    post = PostFalso(respuesta_con(IMSS), respuesta_con(APA), respuesta_con(OMS))
    buscar(post, Decisor(["apa", "oms"]))
    for llamada in post.llamadas:
        plugin = llamada["json"]["plugins"][0]
        assert plugin["id"] == "web" and plugin["engine"] == "exa" and "exclude_domains" not in plugin
        assert "6A70" not in str(llamada["json"]["messages"]) and "tristeza" not in str(llamada["json"]["messages"])
        assert llamada["json"]["max_tokens"] >= 2000
        assert llamada["headers"]["Authorization"] == "Bearer clave"
    assert "Trastorno depresivo" in str(post.llamadas[0]["json"]["messages"])


def test_las_busquedas_de_apa_y_oms_prefieren_espanol_con_ingles_de_respaldo():
    post = PostFalso(respuesta_con(IMSS), respuesta_con(APA), respuesta_con(OMS))
    buscar(post, Decisor(["apa", "oms"]))
    for i in (1, 2):
        mensaje = str(post.llamadas[i]["json"]["messages"])
        assert "español" in mensaje and "inglés" in mensaje


def test_cada_busqueda_descarta_ligas_de_otros_dominios_aunque_el_servidor_las_devuelva():
    post = PostFalso(respuesta_con(IMSS, cita("https://www.who.int/x")))
    guias = buscar(post, Decisor())
    assert [g["url"] for g in guias] == [IMSS["url_citation"]["url"]]


def test_una_liga_repetida_entre_busquedas_se_conserva_solo_una_vez():
    post = PostFalso(respuesta_con(IMSS), respuesta_con(IMSS, APA))
    guias = buscar(post, Decisor(["apa"]))
    assert [(g["tipo"], g["id"]) for g in guias] == [("imss", "G1"), ("apa", "G2")]


def test_cada_guia_trae_id_secuencial_y_extracto_largo_ademas_de_la_cita_corta():
    largo = "Beck Depression Inventory. " * 200
    post = PostFalso(respuesta_con(cita("https://www.imss.gob.mx/a", "A", largo)),
                     respuesta_con(cita("https://www.apa.org/b", "B", "texto corto")))
    guias = buscar(post, Decisor(["apa"]))
    assert [g["id"] for g in guias] == ["G1", "G2"]
    assert 300 < len(guias[0]["extracto"]) <= 2500 and len(guias[0]["cita"]) <= 300
    assert guias[1]["extracto"] == "texto corto"


def test_las_guias_adicionales_conservan_el_motivo_del_decisor():
    post = PostFalso(respuesta_con(IMSS), respuesta_con(APA))
    guias = buscar(post, Decisor(["apa"]))
    assert "motivo" not in guias[0] and guias[1]["motivo"] == "porque sí"


def test_sin_anotaciones_devuelve_lista_vacia():
    assert buscar(PostFalso(respuesta_con())) == []


def test_sin_candidatos_no_llama_a_la_red_ni_al_decisor():
    post, decisor = PostFalso(), Decisor()
    assert buscar_guias([], SINTOMAS, "clave", decisor, post=post) == []
    assert post.llamadas == [] and decisor.recibido == []


def test_sin_clave_falla():
    with pytest.raises(FlujoDetenido, match="OPENROUTER_API_KEY"):
        buscar_guias(CANDIDATOS, SINTOMAS, "", Decisor(), post=PostFalso())


def test_error_http_levanta_flujo_detenido():
    with pytest.raises(FlujoDetenido, match="402"):
        buscar(PostFalso(RespuestaFalsa(402, texto="sin créditos")))


def test_error_de_red_levanta_flujo_detenido():
    with pytest.raises(FlujoDetenido, match="conectar"):
        buscar(PostFalso(requests.ConnectionError("caído")))


def test_formato_inesperado_levanta_flujo_detenido():
    with pytest.raises(FlujoDetenido, match="formato"):
        buscar(PostFalso(RespuestaFalsa(cuerpo={"otra": 1})))


def test_si_falla_una_busqueda_adicional_falla_todo_para_no_dar_guias_a_medias():
    post = PostFalso(respuesta_con(IMSS), RespuestaFalsa(402, texto="sin créditos"))
    with pytest.raises(FlujoDetenido, match="402"):
        buscar(post, Decisor(["apa"]))


def test_reintenta_un_503_y_luego_responde():
    post = PostFalso(RespuestaFalsa(503, texto="overload"), respuesta_con(IMSS))
    esperas = []
    guias = buscar(post, esperar=esperas.append)
    assert len(guias) == 1 and esperas == [1]


# ---- decisor con LLM

class EstructuradoFalso:
    def __init__(self, resultado):
        self.resultado, self.llamadas = resultado, []

    def invoke(self, mensajes):
        self.llamadas.append(mensajes)
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado


class LLMFalso:
    def __init__(self, resultado):
        self.estructurado, self.esquema = EstructuradoFalso(resultado), None

    def with_structured_output(self, esquema, method=None):
        self.esquema = esquema
        return self.estructurado


def test_el_decisor_usa_salida_estructurada_y_solo_envia_titulos_datos_faltantes_y_extractos_del_imss():
    llm = LLMFalso(DecisionFuentes(fuentes=["apa"], razon="faltan guías de evaluación"))
    guias_imss = [{"id": "G1", "titulo": "GPC IMSS", "url": "https://www.imss.gob.mx/x", "extracto": "E" * 900}]
    sintomas = {"emocionales": ["tristeza"], "datos_faltantes": ["duración"], "paciente_ref": "[PER_1]", "edad": 34}
    decision = crear_decisor_fuentes(llm)(CANDIDATOS, sintomas, guias_imss)
    assert decision.fuentes == ["apa"] and llm.esquema is DecisionFuentes
    enviado = str(llm.estructurado.llamadas[0])
    assert "Trastorno depresivo" in enviado and "duración" in enviado and "GPC IMSS" in enviado
    assert "[PER_1]" not in enviado and "tristeza" not in enviado and "6A70" not in enviado
    assert "https://www.imss.gob.mx" not in enviado and "E" * 900 not in enviado
    assert "datos" in llm.estructurado.llamadas[0][0][1]  # el prompt indica que el texto web son datos


def test_el_esquema_solo_admite_fuentes_apa_u_oms():
    with pytest.raises(Exception):
        DecisionFuentes(fuentes=["imss"], razon="x")


# ---- decisor JEV (Decisions API)

def respuesta_jev(eleccion, probs=None, confianza=0.9):
    probs = probs or {eleccion: 0.9}
    return RespuestaFalsa(cuerpo={"answers": {"fuente": {"type": "choice", "choice": eleccion, "probabilities": probs,
                                                         "confidence": confianza}}})


GUIAS_IMSS = [{"id": "G1", "titulo": "GPC IMSS depresión", "url": "https://www.imss.gob.mx/x", "extracto": "E" * 900}]
SINTOMAS_PII = {"emocionales": ["tristeza"], "datos_faltantes": ["duración", "[PER_1] no dijo su edad"], "edad": 34}


@pytest.mark.parametrize("eleccion,fuentes", [("apa", ["apa"]), ("oms", ["oms"]), ("ambas", ["apa", "oms"]), ("ninguna", [])])
def test_jev_traduce_la_opcion_elegida_a_fuentes(eleccion, fuentes):
    decidir = crear_decisor_jev("clave", post=PostFalso(respuesta_jev(eleccion)))
    assert decidir(CANDIDATOS, SINTOMAS, GUIAS_IMSS).fuentes == fuentes


def test_jev_envia_modelo_pregunta_choice_con_las_cuatro_opciones_y_un_estado_sin_datos_del_paciente():
    post = PostFalso(respuesta_jev("apa"))
    crear_decisor_jev("clave", post=post)(CANDIDATOS, SINTOMAS_PII, GUIAS_IMSS)
    llamada = post.llamadas[0]
    assert llamada["url"].endswith("/api/alpha/decisions") and llamada["headers"]["Authorization"] == "Bearer clave"
    cuerpo = llamada["json"]
    assert cuerpo["model"].startswith("typesafe/jev")
    pregunta = cuerpo["questions"]["fuente"]
    assert pregunta["type"] == "choice" and set(pregunta["criteria"]) == {"apa", "oms", "ambas", "ninguna"}
    estado = cuerpo["state"]
    assert "Trastorno depresivo de episodio único" in estado and "duración" in estado and "GPC IMSS depresión" in estado
    assert "[PER_1]" not in estado and "tristeza" not in estado and "6A70" not in estado
    assert "https://www.imss.gob.mx" not in estado and "E" * 400 not in estado


def test_jev_deja_en_la_razon_la_opcion_sus_probabilidades_y_la_confianza():
    decidir = crear_decisor_jev("clave", post=PostFalso(respuesta_jev("apa", {"apa": 0.95, "oms": 0.04, "ninguna": 0.01, "ambas": 0}, 0.92)))
    razon = decidir(CANDIDATOS, SINTOMAS, GUIAS_IMSS).razon
    assert "apa" in razon and "0.95" in razon and "0.92" in razon


def test_jev_reintenta_un_503():
    esperas = []
    decidir = crear_decisor_jev("clave", post=PostFalso(RespuestaFalsa(503, texto="overload"), respuesta_jev("oms")), esperar=esperas.append)
    assert decidir(CANDIDATOS, SINTOMAS, GUIAS_IMSS).fuentes == ["oms"] and esperas == [1]


@pytest.mark.parametrize("respuesta", [
    RespuestaFalsa(500, texto="caído"),
    RespuestaFalsa(cuerpo={"otra": 1}),
    respuesta_jev("bing"),
    requests.ConnectionError("sin red"),
])
def test_si_jev_falla_sin_respaldo_levanta_flujo_detenido(respuesta):
    with pytest.raises(FlujoDetenido):
        crear_decisor_jev("clave", post=PostFalso(respuesta))(CANDIDATOS, SINTOMAS, GUIAS_IMSS)


def test_si_jev_falla_se_usa_el_decisor_de_respaldo():
    respaldo = Decisor(["oms"])
    decidir = crear_decisor_jev("clave", post=PostFalso(RespuestaFalsa(500, texto="caído")), respaldo=respaldo)
    assert decidir(CANDIDATOS, SINTOMAS, GUIAS_IMSS).fuentes == ["oms"] and len(respaldo.recibido) == 1


def test_si_jev_responde_no_se_llama_al_respaldo():
    respaldo = Decisor(["oms"])
    crear_decisor_jev("clave", post=PostFalso(respuesta_jev("ninguna")), respaldo=respaldo)(CANDIDATOS, SINTOMAS, GUIAS_IMSS)
    assert respaldo.recibido == []


def test_buscar_guias_con_jev_busca_en_las_fuentes_elegidas():
    busqueda = PostFalso(respuesta_con(IMSS), respuesta_con(APA), respuesta_con(OMS))
    decidir = crear_decisor_jev("clave", post=PostFalso(respuesta_jev("ambas")))
    guias = buscar_guias(CANDIDATOS, SINTOMAS, "clave", decidir, post=busqueda)
    assert [g["tipo"] for g in guias] == ["imss", "apa", "oms"] and "jev" in guias[1]["motivo"].lower()
