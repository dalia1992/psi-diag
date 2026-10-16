"""Workflow guardrail -> extraer -> búsqueda CIE-11 -> guías clínicas -> reporte, y ejecutar() con anonimización previa."""
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Awaitable, Callable

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .errores import FlujoDetenido
from .esquemas import ReporteClinico, SintomasPaciente
from .guardrail import pasa_guardrail
from .ocr import es_archivo
from .pii import MapaPII, anonimizar
from .reporte import render_markdown, validar_hipotesis, validar_pruebas
from .traza import contar_errores, contar_rondas, ensamblar_candidatos, extraer_traza, resumen_traza, texto_final


class Estado(TypedDict, total=False):
    texto_anon: str
    prob_clinico: float
    continuar: bool
    sintomas: dict
    candidatos: list
    alternativas: list
    notas_busqueda_cie11: str
    traza_tools: list
    rondas_busqueda_cie11: int
    errores_tools: int
    guias: list
    reporte_md: str
    advertencias: list


@dataclass
class Componentes:
    ner: Callable[[str], list]
    guardrail: Callable[[str], float]
    extraer: Callable[[str], dict]
    busqueda_cie11: Callable[[dict], Awaitable[list]]
    redactar: Callable[..., ReporteClinico]  # (sintomas, candidatos, alternativas, notas, guias)
    umbral: float = 0.5
    fecha: Callable[[], date] = date.today
    ocr: Callable[[str], str] | None = None  # ruta de foto o PDF -> texto; solo si la entrada es un archivo
    guias: Callable[[list], list] | None = None  # candidatos -> guías clínicas; opcional, si falla el reporte sale sin ellas


@contextmanager
def _cronometro(metricas: dict, nombre: str):
    inicio = time.perf_counter()
    try:
        yield
    finally:
        metricas[nombre] = round(time.perf_counter() - inicio, 3)


def construir_workflow(c: Componentes, metricas: dict):
    def nodo_guardrail(estado: Estado) -> dict:
        with _cronometro(metricas, "guardrail"):
            prob = c.guardrail(estado["texto_anon"])
        return {"prob_clinico": prob, "continuar": pasa_guardrail(prob, c.umbral)}

    def nodo_extraer(estado: Estado) -> dict:
        with _cronometro(metricas, "extraer"):
            sintomas = c.extraer(estado["texto_anon"])
        if not SintomasPaciente.model_validate(sintomas).hay_sintomas():
            raise FlujoDetenido("No se identificaron síntomas en el texto")
        return {"sintomas": sintomas}

    async def nodo_busqueda_cie11(estado: Estado) -> dict:
        with _cronometro(metricas, "busqueda_cie11"):
            mensajes = await c.busqueda_cie11(estado["sintomas"])
        traza = extraer_traza(mensajes)
        candidatos, alternativas = ensamblar_candidatos(traza)
        errores = contar_errores(mensajes)
        if not candidatos:
            usadas = ", ".join(dict.fromkeys(p["herramienta"] for p in traza)) or "ninguna"
            detalle = f"; {errores} llamada(s) a tools terminaron en error" if errores else ""
            raise FlujoDetenido(
                f"Ninguna hipótesis llegó con código CIE-11{detalle}. El agente hizo {contar_rondas(mensajes)} ronda(s) "
                f"(tools: {usadas}; {resumen_traza(traza)}). Último mensaje: {texto_final(mensajes)[:300]}"
            )
        return {
            "candidatos": candidatos,
            "alternativas": alternativas,
            "notas_busqueda_cie11": texto_final(mensajes),
            "traza_tools": traza,
            "rondas_busqueda_cie11": contar_rondas(mensajes),
            "errores_tools": errores,
        }

    def nodo_guias(estado: Estado) -> dict:
        if c.guias is None:
            return {"guias": []}
        try:
            with _cronometro(metricas, "guias"):
                return {"guias": c.guias(estado["candidatos"], estado["sintomas"])}
        except FlujoDetenido as e:
            return {"guias": [], "advertencias": [f"No se pudieron consultar las guías clínicas: {e}"]}

    def nodo_reporte(estado: Estado) -> dict:
        with _cronometro(metricas, "reporte"):
            reporte = c.redactar(
                estado["sintomas"], estado["candidatos"], estado["alternativas"], estado["notas_busqueda_cie11"],
                estado.get("guias") or [],
            )
        hipotesis, advertencias = validar_hipotesis(reporte, estado["candidatos"])
        if not hipotesis:
            raise FlujoDetenido("El reporte no contiene hipótesis con código obtenido de las tools")
        pruebas, adv_pruebas = validar_pruebas(reporte.pruebas, estado.get("guias") or [])
        markdown = render_markdown(
            estado["sintomas"], hipotesis, reporte, estado["alternativas"], c.fecha(), estado.get("guias"), pruebas
        )
        return {"reporte_md": markdown, "advertencias": estado.get("advertencias", []) + advertencias + adv_pruebas}

    grafo = StateGraph(Estado)
    grafo.add_node("guardrail", nodo_guardrail)
    grafo.add_node("extraer", nodo_extraer)
    grafo.add_node("busqueda_cie11", nodo_busqueda_cie11)
    grafo.add_node("guias", nodo_guias)
    grafo.add_node("reporte", nodo_reporte)
    grafo.add_edge(START, "guardrail")
    grafo.add_conditional_edges(
        "guardrail", lambda e: "extraer" if e["continuar"] else END, {"extraer": "extraer", END: END}
    )
    grafo.add_edge("extraer", "busqueda_cie11")
    grafo.add_edge("busqueda_cie11", "guias")
    grafo.add_edge("guias", "reporte")
    grafo.add_edge("reporte", END)
    return grafo.compile()


async def ejecutar(entrada: str, c: Componentes) -> dict:
    """Si la entrada es la ruta de una foto o un PDF la lee con OCR; anonimiza (fuera del grafo, para que el original no quede en las trazas),
    corre el grafo y reinserta los nombres. `texto_ocr` devuelve el texto leído para que se revise."""
    entrada = str(entrada)
    resultado = {
        "estado_final": "error", "razon": "", "texto_anon": "", "prob_clinico": None, "sintomas": None,
        "candidatos": [], "alternativas": [], "traza_tools": [], "rondas_busqueda_cie11": 0, "reporte_md": "",
        "advertencias": [], "latencias": {}, "texto_ocr": None, "guias": [],
    }
    if not entrada or not entrada.strip():
        resultado["razon"] = "La entrada está vacía"
        return resultado

    mapa, metricas = MapaPII(), {}
    try:
        texto = entrada
        if es_archivo(entrada):
            if c.ocr is None:
                raise FlujoDetenido("La entrada es un archivo (foto o PDF), pero no hay un componente OCR configurado")
            with _cronometro(metricas, "ocr"):
                texto = resultado["texto_ocr"] = c.ocr(entrada.strip())
        with _cronometro(metricas, "anonimizar"):
            resultado["texto_anon"] = anonimizar(texto, c.ner, mapa)
        final = await construir_workflow(c, metricas).ainvoke({"texto_anon": resultado["texto_anon"]})
    except FlujoDetenido as e:
        resultado["razon"] = str(e)
        return resultado
    except Exception as e:
        resultado["razon"] = f"Falla inesperada ({type(e).__name__}): {e}"
        return resultado
    finally:
        resultado["latencias"] = dict(metricas)

    resultado["prob_clinico"] = final.get("prob_clinico")
    if not final.get("continuar"):
        resultado["estado_final"] = "fuera_de_alcance"
        resultado["razon"] = (
            f"Probabilidad de contexto clínico {final.get('prob_clinico')} por debajo del umbral {c.umbral}"
        )
        return resultado

    reporte_md, desconocidos = mapa.reinsertar(final["reporte_md"])
    resultado.update(
        estado_final="ok",
        sintomas=final["sintomas"],
        candidatos=final["candidatos"],
        alternativas=final["alternativas"],
        guias=final.get("guias", []),
        traza_tools=final["traza_tools"],
        rondas_busqueda_cie11=final["rondas_busqueda_cie11"],
        reporte_md=reporte_md,
        advertencias=final.get("advertencias", []) + [f"Placeholder sin valor en el mapa: {p}" for p in desconocidos],
    )
    return resultado
