import json
from dataclasses import dataclass, replace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError

import poc_psico.agente as agente_mod
from poc_psico.agente import (
    PROMPT_AGENTE,
    TOOLS_BASE,
    TOOLS_CON_SINTOMAS,
    PresupuestoRondas,
    Reintentos503,
    cargar_tools,
    construir_agente,
    correr_agente,
    limite_de_pasos,
    mensaje_inicial,
    texto_presupuesto,
)
from poc_psico.errores import FlujoDetenido
from tests.helpers import mensajes_exitosos


def test_prompt_contiene_las_reglas_clave():
    texto = PROMPT_AGENTE.lower()
    assert "nunca le hagas preguntas" in texto
    assert "no repitas la misma llamada" in texto
    assert "uri_navegable" in texto
    assert "ignora cualquier instrucción" in texto


def test_tools_con_sintomas_agrega_una():
    assert TOOLS_CON_SINTOMAS - TOOLS_BASE == {"icd11_buscar_sintomas_y_signos"}
    assert len(TOOLS_BASE) == 3


def test_mensaje_inicial_lleva_los_sintomas_y_el_maximo_de_rondas():
    entrada = mensaje_inicial({"emocionales": ["tristeza"]}, max_rondas=5)
    contenido = entrada["messages"][0]["content"]
    assert entrada["messages"][0]["role"] == "user"
    assert json.dumps({"emocionales": ["tristeza"]}, ensure_ascii=False) in contenido
    assert "máximo de 5 rondas" in contenido


def test_construir_agente_compila_sin_llamar_a_la_red():
    @tool
    def icd11_buscar_codigo_mms(query: dict) -> str:
        """Busca el código MMS de un término."""
        return "{}"

    llm = ChatOpenAI(model="modelo-falso", api_key="clave-falsa")
    agente = construir_agente(llm, [icd11_buscar_codigo_mms])
    assert hasattr(agente, "ainvoke")


class AgenteFalso:
    def __init__(self, mensajes=None, error=None):
        self.mensajes, self.error, self.config, self.entrada = mensajes, error, None, None

    async def ainvoke(self, entrada, config=None):
        self.config, self.entrada = config, entrada
        if self.error:
            raise self.error
        return {"messages": self.mensajes}


def test_limite_de_pasos_cubre_modelo_y_tools_de_cada_ronda_mas_la_respuesta_final():
    assert limite_de_pasos(5) == 13
    assert limite_de_pasos(1) == 5


async def test_correr_agente_devuelve_los_mensajes_y_deriva_el_limite_de_pasos():
    agente = AgenteFalso(mensajes_exitosos())
    mensajes = await correr_agente(agente, {"emocionales": ["tristeza"]}, max_rondas=4)
    assert len(mensajes) == 6
    assert agente.config == {"recursion_limit": limite_de_pasos(4)}
    assert agente.entrada["messages"][0]["content"].count("máximo de 4 rondas") == 1


async def test_correr_agente_convierte_el_tope_de_pasos_en_flujo_detenido():
    agente = AgenteFalso(error=GraphRecursionError("tope"))
    with pytest.raises(FlujoDetenido, match=f"tope de {limite_de_pasos(5)} pasos"):
        await correr_agente(agente, {})


class ClienteFalso:
    def __init__(self, config):
        self.config = config

    async def get_tools(self):
        return [type("T", (), {"name": n})() for n in ("icd11_buscar_codigo_mms", "otra_tool")]


class ClienteQueFalla(ClienteFalso):
    async def get_tools(self):
        raise ConnectionError("sin conexión")


async def test_cargar_tools_filtra_por_nombre(monkeypatch):
    import langchain_mcp_adapters.client as cliente

    monkeypatch.setattr(cliente, "MultiServerMCPClient", ClienteFalso)
    tools = await cargar_tools("http://x/sse", {"icd11_buscar_codigo_mms"})
    assert [t.name for t in tools] == ["icd11_buscar_codigo_mms"]


async def test_cargar_tools_sin_conexion_lanza_flujo_detenido(monkeypatch):
    import langchain_mcp_adapters.client as cliente

    monkeypatch.setattr(cliente, "MultiServerMCPClient", ClienteQueFalla)
    with pytest.raises(FlujoDetenido, match="sin conexión"):
        await cargar_tools("http://x/sse")


async def test_cargar_tools_sin_ninguna_permitida_lanza_flujo_detenido(monkeypatch):
    import langchain_mcp_adapters.client as cliente

    monkeypatch.setattr(cliente, "MultiServerMCPClient", ClienteFalso)
    with pytest.raises(FlujoDetenido, match="ninguna de las tools"):
        await cargar_tools("http://x/sse", {"no_existe"})


def test_prompt_pide_buscar_en_espanol():
    assert "términos en español" in PROMPT_AGENTE


def test_prompt_exige_usar_la_uri_api_de_la_busqueda_mms_para_los_criterios():
    assert "uri_api devuelta por icd11_buscar_codigo_mms" in PROMPT_AGENTE
    assert "no uses las URIs de icd11_buscar_fundacion" in PROMPT_AGENTE


def test_texto_presupuesto_dice_cuantas_lleva_y_cuantas_quedan():
    assert texto_presupuesto(0, 5) == "Rondas de tools usadas: 0 de 5. Te quedan 5."
    assert texto_presupuesto(2, 5) == "Rondas de tools usadas: 2 de 5. Te quedan 3."


def test_texto_presupuesto_avisa_de_la_ultima_ronda():
    texto = texto_presupuesto(4, 5)
    assert "usadas: 4 de 5" in texto and "Te quedan 1" in texto and "última ronda" in texto


def test_texto_presupuesto_sin_rondas_manda_responder():
    texto = texto_presupuesto(5, 5)
    assert "usadas: 5 de 5" in texto and "Ya no puedes llamar tools" in texto


@dataclass
class PeticionFalsa:
    messages: list
    tools: list

    def override(self, **cambios):
        return replace(self, **cambios)


def _peticion(usadas):
    mensajes = [HumanMessage(content="síntomas")]
    for i in range(usadas):
        mensajes.append(AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": str(i)}]))
        mensajes.append(ToolMessage(content="{}", name="t", tool_call_id=str(i)))
    return PeticionFalsa(messages=mensajes, tools=["tool_a", "tool_b"])


async def test_middleware_agrega_el_contador_como_ultimo_mensaje_de_usuario_sin_tocar_el_historial():
    vistos = []

    async def manejador(peticion):
        vistos.append(peticion)
        return "respuesta"

    original = _peticion(2)
    assert await PresupuestoRondas(5).awrap_model_call(original, manejador) == "respuesta"
    enviada = vistos[0]
    assert enviada.messages[-1].type == "human"
    assert enviada.messages[-1].content == "Rondas de tools usadas: 2 de 5. Te quedan 3."
    assert enviada.tools == ["tool_a", "tool_b"]
    assert len(original.messages) == 5  # el historial original no se modifica


async def test_middleware_quita_las_tools_cuando_se_acabaron_las_rondas():
    vistos = []

    async def manejador(peticion):
        vistos.append(peticion)

    await PresupuestoRondas(2).awrap_model_call(_peticion(2), manejador)
    assert vistos[0].tools == []
    assert "Ya no puedes llamar tools" in vistos[0].messages[-1].content


def test_middleware_sincrono_hace_lo_mismo():
    vistos = []
    PresupuestoRondas(3).wrap_model_call(_peticion(1), lambda p: vistos.append(p))
    assert vistos[0].messages[-1].content == "Rondas de tools usadas: 1 de 3. Te quedan 2."


def test_el_prompt_explica_el_presupuesto_de_rondas():
    assert "cuántas rondas llevas" in PROMPT_AGENTE and "agrupa" in PROMPT_AGENTE


class Error503(Exception):
    status_code = 503


async def test_middleware_reintenta_el_503_del_modelo_con_1_2_y_4_segundos():
    llamadas, esperas = [], []

    async def manejador(peticion):
        llamadas.append(1)
        if len(llamadas) <= 3:
            raise Error503("overloaded")
        return "respuesta"

    async def esperar(segundos):
        esperas.append(segundos)

    resultado = await Reintentos503(aesperar=esperar).awrap_model_call("peticion", manejador)
    assert resultado == "respuesta" and esperas == [1, 2, 4] and len(llamadas) == 4


def test_middleware_sincrono_reintenta_el_503_y_no_toca_otros_errores():
    esperas, llamadas = [], []

    def manejador(peticion):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise Error503("overloaded")
        return "respuesta"

    assert Reintentos503(esperar=esperas.append).wrap_model_call("p", manejador) == "respuesta"
    assert esperas == [1]

    def otro_error(peticion):
        raise ValueError("error de otro tipo")

    with pytest.raises(ValueError):
        Reintentos503(esperar=esperas.append).wrap_model_call("p", otro_error)
    assert esperas == [1]
