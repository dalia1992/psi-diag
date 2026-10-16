"""Parseo de los mensajes del agente: resultados de tools, candidatos, rondas y errores."""
import json
import re

HERRAMIENTA_MMS = "icd11_buscar_codigo_mms"
HERRAMIENTA_CRITERIOS = "icd11_obtener_criterios_clinicos"


def _sin_html(texto):
    return re.sub(r"</?em[^>]*>", "", texto) if isinstance(texto, str) else texto


def parsear_contenido(contenido):
    """El contenido de una tool llega como lista de bloques, como cadena JSON o como texto plano."""
    if isinstance(contenido, list):
        textos = [b["text"] for b in contenido if isinstance(b, dict) and "text" in b]
        contenido = textos[0] if len(textos) == 1 else "\n".join(textos)
    if isinstance(contenido, str):
        try:
            return json.loads(contenido)
        except json.JSONDecodeError:
            return {"texto": contenido}
    return contenido


def extraer_traza(mensajes) -> list:
    llamadas, traza = {}, []
    for m in mensajes:
        if m.type == "ai":
            for tc in getattr(m, "tool_calls", None) or []:
                llamadas[tc.get("id")] = {"herramienta": tc.get("name"), "input": tc.get("args", {})}
        elif m.type == "tool":
            llamada = llamadas.get(getattr(m, "tool_call_id", None), {"herramienta": m.name, "input": None})
            traza.append(
                {
                    "herramienta": llamada["herramienta"] or m.name,
                    "input": llamada["input"],
                    "resultado": parsear_contenido(m.content),
                    "error": getattr(m, "status", None) == "error",
                }
            )
    return traza


def _id_final(uri) -> str:
    """Identificador de la entidad sin esquema, host ni versión: '1563440232/unspecified' o '1001'."""
    texto = str(uri).rstrip("/")
    m = re.search(r"/(?:mms|entity)/(.+)$", texto)
    return m.group(1) if m else texto.split("/")[-1]


def _url_navegable(item) -> str:
    """Liga del navegador OMS a la entidad. Para residuales (.Y/.Z) el MCP devuelve '#unspecified'/'#other'
    sin id, que abre la página general: se reconstruye con el id del padre desde uri_api."""
    url = item.get("uri_navegable")
    if not url:
        return url
    base, _, fragmento = url.partition("#")
    if fragmento in ("unspecified", "other") and item.get("uri_api"):
        return f"{base}#{_id_final(item['uri_api']).replace('/', '%2F')}"
    return url


def _resultados(traza, herramienta) -> list:
    """Resultados (dict) de las llamadas exitosas a una herramienta."""
    return [
        p["resultado"] for p in traza
        if p["herramienta"] == herramienta and not p["error"] and isinstance(p["resultado"], dict)
    ]


def ensamblar_candidatos(traza, max_alternativas: int = 10):
    """Candidato = entidad con código MMS y criterios consultados. Alternativa = código MMS sin criterios."""
    mms = {
        _id_final(item["uri_api"]): item
        for resultado in _resultados(traza, HERRAMIENTA_MMS)
        for item in resultado.get("resultados_mms") or []
        if item.get("codigo_oficial") and item.get("uri_api")
    }
    criterios = {_id_final(r["uri"]): r for r in _resultados(traza, HERRAMIENTA_CRITERIOS) if r.get("uri")}

    candidatos, codigos = [], set()
    for clave, c in criterios.items():
        item = mms.get(clave)
        if item is None or item["codigo_oficial"] in codigos:
            continue
        codigos.add(item["codigo_oficial"])
        candidatos.append(
            {
                "codigo": item["codigo_oficial"],
                "titulo": _sin_html(c.get("titulo") or item.get("titulo")),
                "url": _url_navegable(item),
                "definicion": c.get("definicion") or "",
                "inclusiones": c.get("inclusiones") or [],
                "exclusiones": c.get("exclusiones") or [],
            }
        )

    alternativas = [
        {"codigo": i["codigo_oficial"], "titulo": _sin_html(i.get("titulo")), "url": _url_navegable(i)}
        for clave, i in mms.items()
        if clave not in criterios and i["codigo_oficial"] not in codigos
    ]
    return candidatos, alternativas[:max_alternativas]


def contar_rondas(mensajes) -> int:
    return sum(1 for m in mensajes if m.type == "ai" and getattr(m, "tool_calls", None))


def contar_errores(mensajes) -> int:
    return sum(1 for m in mensajes if m.type == "tool" and getattr(m, "status", None) == "error")


def texto_final(mensajes) -> str:
    for m in reversed(mensajes):
        if m.type == "ai":
            contenido = m.content
            if isinstance(contenido, list):
                return "".join(b.get("text", "") for b in contenido if isinstance(b, dict))
            return str(contenido)
    return ""


def resumen_traza(traza) -> str:
    """Resumen para diagnosticar por qué no hubo candidatos: códigos MMS recibidos y criterios consultados."""
    n_mms = sum(len(r.get("resultados_mms") or []) for r in _resultados(traza, HERRAMIENTA_MMS))
    ids = [_id_final(r["uri"]) for r in _resultados(traza, HERRAMIENTA_CRITERIOS) if r.get("uri")]
    return f"{n_mms} código(s) MMS recibidos; criterios consultados: {ids}"
