import json

import pytest

from poc_psico.esquemas import ReporteClinico, SintomasPaciente
from poc_psico.nodos import crear_extractor, crear_redactor


class EstructuradoFalso:
    def __init__(self, resultado):
        self.resultado, self.llamadas = resultado, []

    def invoke(self, mensajes):
        self.llamadas.append(mensajes)
        return self.resultado


class LLMFalso:
    def __init__(self, resultado):
        self.estructurado = EstructuradoFalso(resultado)
        self.esquema = None
        self.metodo = None

    def with_structured_output(self, esquema, method=None):
        self.esquema, self.metodo = esquema, method
        return self.estructurado


def test_extractor_devuelve_dict_y_usa_function_calling():
    llm = LLMFalso(SintomasPaciente(emocionales=["tristeza"], edad=34))
    extraer = crear_extractor(llm)
    assert extraer("[PER_1] de 34 años")["emocionales"] == ["tristeza"]
    assert llm.esquema is SintomasPaciente and llm.metodo == "function_calling"
    assert llm.estructurado.llamadas[0][1] == ("human", "[PER_1] de 34 años")


def test_redactor_solo_envia_codigo_titulo_y_criterios_no_urls():
    reporte = ReporteClinico(hipotesis=[])
    llm = LLMFalso(reporte)
    redactar = crear_redactor(llm)
    candidatos = [{"codigo": "6A70", "titulo": "T", "url": "https://x/1001", "definicion": "D", "inclusiones": [], "exclusiones": []}]
    salida = redactar({"emocionales": ["tristeza"]}, candidatos, [{"codigo": "6A71", "titulo": "R", "url": "https://x/1002"}], "notas")
    assert salida is reporte
    enviado = llm.estructurado.llamadas[0][1][1]
    assert "6A70" in enviado and "6A71" in enviado and "notas" in enviado
    assert "https://x" not in enviado
    assert json.loads(enviado)["sintomas"]["emocionales"] == ["tristeza"]


class Error503(Exception):
    status_code = 503


class EstructuradoQueSeSatura:
    def __init__(self, resultado, fallos):
        self.resultado, self.fallos, self.llamadas = resultado, fallos, 0

    def invoke(self, mensajes):
        self.llamadas += 1
        if self.llamadas <= self.fallos:
            raise Error503("overloaded")
        return self.resultado


def test_extractor_reintenta_el_503():
    llm = LLMFalso(None)
    llm.estructurado = EstructuradoQueSeSatura(SintomasPaciente(emocionales=["tristeza"]), fallos=2)
    esperas = []
    extraer = crear_extractor(llm, esperar=esperas.append)
    assert extraer("texto")["emocionales"] == ["tristeza"]
    assert esperas == [1, 2]


def test_redactor_reintenta_el_503_y_se_rinde_tras_3_reintentos():
    llm = LLMFalso(None)
    llm.estructurado = EstructuradoQueSeSatura(ReporteClinico(hipotesis=[]), fallos=99)
    esperas = []
    redactar = crear_redactor(llm, esperar=esperas.append)
    with pytest.raises(Error503):
        redactar({}, [], [], "")
    assert esperas == [1, 2, 4] and llm.estructurado.llamadas == 4


# --- Reintento de formato con la caché de LLM activa (celda 1.1 del notebook) ---
import json as _json

from langchain_core.caches import InMemoryCache
from langchain_core.globals import set_llm_cache
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from pydantic import ValidationError


class ModeloQueEntregaLaListaComoTexto(BaseChatModel):
    """Como el modelo real en el fallo observado: `hipotesis` llega como texto, salvo que el reintento le diga qué falló."""

    peticiones: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "falso"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.peticiones.append([m.content for m in messages])
        lista = [{"codigo": "6B43", "justificacion": "Encaja con los criterios."}]
        avisado = "no cumplió el formato" in str(messages[-1].content)
        args = {"hipotesis": lista if avisado else _json.dumps(lista)}
        mensaje = AIMessage(content="", tool_calls=[{"name": "ReporteClinico", "args": args, "id": "t1"}])
        return ChatResult(generations=[ChatGeneration(message=mensaje)])


@pytest.fixture
def con_cache_de_llm():
    set_llm_cache(InMemoryCache())
    yield
    set_llm_cache(None)


def test_el_reintento_de_formato_le_dice_al_modelo_que_fallo_y_asi_no_se_repite_la_respuesta_cacheada(con_cache_de_llm):
    llm = ModeloQueEntregaLaListaComoTexto()
    reporte = crear_redactor(llm, esperar=lambda s: None)({}, [], [], "")
    assert [h.codigo for h in reporte.hipotesis] == ["6B43"]
    assert len(llm.peticiones) == 2  # la segunda es una llamada real, no un acierto de la caché
    aviso = llm.peticiones[1][-1]
    assert "no cumplió el formato" in aviso and "hipotesis" in aviso


def test_si_el_modelo_sigue_fallando_se_hacen_todos_los_intentos_reales_y_se_propaga_el_error(con_cache_de_llm):
    class Terco(ModeloQueEntregaLaListaComoTexto):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.peticiones.append([m.content for m in messages])
            args = {"hipotesis": "texto"}
            mensaje = AIMessage(content="", tool_calls=[{"name": "ReporteClinico", "args": args, "id": "t1"}])
            return ChatResult(generations=[ChatGeneration(message=mensaje)])

    llm = Terco()
    with pytest.raises(ValidationError):
        crear_redactor(llm, esperar=lambda s: None)({}, [], [], "")
    assert len(llm.peticiones) == 3


GUIAS = [{"id": "G1", "titulo": "Evaluación", "url": "https://www.apa.org/e", "cita": "c", "tipo": "evaluacion",
          "extracto": "El PHQ-9 se recomienda para medir la severidad."}]


def test_el_redactor_recibe_id_titulo_y_extracto_de_las_guias_pero_no_sus_urls():
    llm = LLMFalso(ReporteClinico(hipotesis=[]))
    crear_redactor(llm)({}, [], [], "", GUIAS)
    sistema, humano = llm.estructurado.llamadas[0][0][1], llm.estructurado.llamadas[0][1][1]
    enviado = json.loads(humano)["guias"]
    assert enviado == [{"id": "G1", "titulo": "Evaluación", "extracto": "El PHQ-9 se recomienda para medir la severidad."}]
    assert "https://www.apa.org" not in humano
    assert "fuente_id" in llm.estructurado.llamadas[0][0][1] and "datos" in llm.estructurado.llamadas[0][0][1]


def test_sin_guias_el_redactor_no_envia_la_clave_guias():
    llm = LLMFalso(ReporteClinico(hipotesis=[]))
    crear_redactor(llm)({}, [], [], "")
    assert "guias" not in json.loads(llm.estructurado.llamadas[0][1][1])
