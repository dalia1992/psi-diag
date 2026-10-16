"""Mensajes de ejemplo de una corrida del agente, con la forma real del MCP."""
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

BASE = "http://id.who.int/icd/release/11/2024-01/mms/"


def bloque(obj):
    return [{"type": "text", "text": json.dumps(obj, ensure_ascii=False)}]


MMS_DEPRESION = {
    "resultados_mms": [
        {
            "codigo_oficial": "6A70",
            "titulo": "Trastorno depresivo de episodio único",
            "uri_api": BASE + "1001",
            "capitulo": "06",
            "uri_navegable": "https://icd.who.int/browse/2024-01/mms/es#1001",
        },
        {
            "codigo_oficial": "6A71",
            "titulo": "Trastorno depresivo recurrente",
            "uri_api": BASE + "1002",
            "capitulo": "06",
            "uri_navegable": "https://icd.who.int/browse/2024-01/mms/es#1002",
        },
    ]
}

CRITERIOS_6A70 = {
    "uri": BASE + "1001",
    "titulo": "Trastorno depresivo de episodio único",
    "definicion": "Episodio depresivo único de al menos dos semanas.",
    "inclusiones": ["Depresión mayor de episodio único"],
    "exclusiones": [],
}


def _llamada(nombre, args, id_):
    return AIMessage(content="", tool_calls=[{"name": nombre, "args": args, "id": id_}])


def mensajes_exitosos():
    return [
        HumanMessage(content="{}"),
        _llamada("icd11_buscar_codigo_mms", {"query": {"termino": "trastorno depresivo"}}, "c1"),
        ToolMessage(content=bloque(MMS_DEPRESION), name="icd11_buscar_codigo_mms", tool_call_id="c1"),
        _llamada("icd11_obtener_criterios_clinicos", {"query": {"uri_entidad": BASE + "1001"}}, "c2"),
        ToolMessage(content=bloque(CRITERIOS_6A70), name="icd11_obtener_criterios_clinicos", tool_call_id="c2"),
        AIMessage(content="Hallazgos: 6A70 es la más compatible; hay ambigüedad con 6A71 (recurrente)."),
    ]


def mensajes_con_error():
    return [
        HumanMessage(content="{}"),
        _llamada("icd11_buscar_codigo_mms", {"query": {"termino": "x"}}, "c1"),
        ToolMessage(content="Connection refused", name="icd11_buscar_codigo_mms", tool_call_id="c1", status="error"),
        AIMessage(content="No pude consultar la CIE-11."),
    ]


def mensajes_sin_resultados():
    return [
        HumanMessage(content="{}"),
        _llamada("icd11_buscar_codigo_mms", {"query": {"termino": "zzz"}}, "c1"),
        ToolMessage(content=bloque({"resultados_mms": []}), name="icd11_buscar_codigo_mms", tool_call_id="c1"),
        AIMessage(content="No hay categoría para ese término."),
    ]


class RespuestaFalsa:
    """Respuesta HTTP de prueba. Si `cuerpo` es una excepción, .json() la lanza."""

    def __init__(self, status=200, cuerpo=None, texto=None):
        self.status_code, self._cuerpo = status, cuerpo
        sin_cuerpo = cuerpo is None or isinstance(cuerpo, Exception)
        self.text = texto if texto is not None else ("" if sin_cuerpo else json.dumps(cuerpo))

    def json(self):
        if isinstance(self._cuerpo, Exception):
            raise self._cuerpo
        return self._cuerpo
