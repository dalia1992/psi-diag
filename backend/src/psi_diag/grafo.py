"""Workflow guardrail -> extraer -> búsqueda CIE-11 -> guías clínicas -> reporte, y ejecutar() con anonimización previa."""
import asyncio
import re
import time
from contextlib import aclosing, contextmanager
from dataclasses import dataclass
from datetime import date
from typing import AsyncIterator, Awaitable, Callable

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .errores import FlujoDetenido
from .esquemas import ReporteClinico, SintomasPaciente
from .guardrail import GuardrailError, pasa_guardrail
from .ocr import OcrError, es_archivo
from .pii import MapaPII, anonimizar
from .progreso import registrar_emisor
from .reporte import construir_datos, render_markdown, separar_advertencias, validar_hipotesis, validar_pruebas
from .traduccion import PASOS, detalle_legible
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
    reporte_datos: dict
    advertencias: list
    advertencias_tecnicas: list


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
            frases, tecnicas = separar_advertencias([("guias_no_disponibles", str(e))])
            return {"guias": [], "advertencias": frases, "advertencias_tecnicas": tecnicas}

    def nodo_reporte(estado: Estado) -> dict:
        with _cronometro(metricas, "reporte"):
            reporte = c.redactar(
                estado["sintomas"], estado["candidatos"], estado["alternativas"], estado["notas_busqueda_cie11"],
                estado.get("guias") or [],
            )
        hipotesis, avisos = validar_hipotesis(reporte, estado["candidatos"])
        if not hipotesis:
            raise FlujoDetenido("El reporte no contiene hipótesis con código obtenido de las tools")
        pruebas, avisos_pruebas = validar_pruebas(reporte.pruebas, estado.get("guias") or [])
        frases, tecnicas = separar_advertencias(avisos + avisos_pruebas)
        markdown = render_markdown(
            estado["sintomas"], hipotesis, reporte, estado["alternativas"], c.fecha(), estado.get("guias"), pruebas
        )
        datos = construir_datos(
            estado["sintomas"], hipotesis, reporte, estado["alternativas"], c.fecha(), estado.get("guias"), pruebas
        )
        return {
            "reporte_md": markdown, "reporte_datos": datos,
            "advertencias": list(dict.fromkeys(estado.get("advertencias", []) + frases)),
            "advertencias_tecnicas": estado.get("advertencias_tecnicas", []) + tecnicas,
        }

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


RAZON_GENERICA = "No se pudo completar el análisis. Puedes intentarlo de nuevo."
RAZON_FUERA_DE_ALCANCE = "Este texto no parece ser un caso de psicología clínica. Ψ-DIAG apoya a profesionales de la psicología con notas clínicas de pacientes; revisa lo que escribiste e inténtalo de nuevo."
RAZON_CIE11 = "No se pudo consultar la CIE-11 en este momento. Espera un minuto e inténtalo de nuevo; si sigue igual, avisa a quien administra la app."
RAZON_SATURADO = "Los servicios de análisis están saturados. Espera un minuto e inténtalo de nuevo."
RAZON_VERIFICACION = "No se pudo verificar que el texto sea un caso clínico. Inténtalo de nuevo en un momento."
_RAZONES_AMIGABLES = (  # (inicio del mensaje de FlujoDetenido, frase para la persona usuaria)
    ("La entrada está vacía", "Escribe o sube la descripción del caso para poder analizarlo."),
    ("No se identificaron síntomas", "No se identificaron síntomas en el texto; describe con más detalle lo que presenta la persona."),
    ("Ninguna hipótesis", "No se encontraron diagnósticos de la CIE-11 para este caso. Puedes intentarlo de nuevo."),
    ("El reporte no contiene hipótesis", "No se pudo redactar un reporte con diagnósticos confiables. Puedes intentarlo de nuevo."),
    ("La entrada es un archivo", "La lectura de archivos no está disponible por ahora. Escribe el texto del caso directamente."),
    ("No se pudo conectar al MCP", RAZON_CIE11),
    ("El MCP no expone", RAZON_CIE11),
    ("El agente alcanzó el tope", RAZON_CIE11),
)
_SATURACION = re.compile(r"\b(429|503)\b")
_NODO_A_PASO = {"guardrail": "verificacion", "extraer": "sintomas", "busqueda_cie11": "cie11", "guias": "guias", "reporte": "reporte"}
_PASO_SIGUIENTE = {"verificacion": "sintomas", "sintomas": "cie11", "cie11": "guias", "guias": "reporte"}
_TITULOS = {p.id: p.titulo for p in PASOS}


def _razon_amigable_error(error: Exception, en_lectura: bool) -> str:
    """Frase sin nombres técnicos para un error; el mensaje original queda solo en `razon`."""
    if isinstance(error, OcrError) or (en_lectura and isinstance(error, FlujoDetenido)):
        return "No se pudo leer el archivo. Prueba con otra foto o PDF, o escribe el texto directamente."
    if isinstance(error, FlujoDetenido):
        mensaje = str(error)
        for inicio, frase in _RAZONES_AMIGABLES:
            if mensaje.startswith(inicio):
                return frase
    if _SATURACION.search(str(error)) or getattr(error, "status_code", None) in (429, 503):
        return RAZON_SATURADO
    if isinstance(error, GuardrailError):
        return RAZON_VERIFICACION
    return RAZON_GENERICA


def _paso(paso_id: str, estado: str, datos: dict | None = None) -> dict:
    evento = {"tipo": "paso", "id": paso_id, "titulo": _TITULOS[paso_id], "estado": estado}
    if estado == "listo":
        evento["detalle"] = detalle_legible(paso_id, datos or {})
    return evento


async def ejecutar_eventos(entrada: str, c: Componentes) -> AsyncIterator[dict]:
    """Igual que `ejecutar`, pero va emitiendo el avance: eventos `paso` (en_curso/listo) y al final un único
    evento `resultado`. Los eventos solo llevan texto anonimizado; los nombres se reinsertan solo en el resultado final.
    La lectura, la anonimización y los nodos síncronos corren en hilos para no bloquear el flujo de eventos."""
    entrada = str(entrada)
    resultado = {
        "estado_final": "error", "razon": "", "razon_amigable": "", "texto_anon": "", "prob_clinico": None, "sintomas": None,
        "candidatos": [], "alternativas": [], "traza_tools": [], "rondas_busqueda_cie11": 0, "reporte_md": "", "reporte": None,
        "advertencias": [], "advertencias_tecnicas": [], "latencias": {}, "texto_ocr": None, "guias": [],
    }
    if not entrada or not entrada.strip():
        resultado["razon"] = "La entrada está vacía"
        resultado["razon_amigable"] = _razon_amigable_error(FlujoDetenido(resultado["razon"]), False)
        yield {"tipo": "resultado", "resultado": resultado}
        return

    mapa, metricas = MapaPII(), {}
    final: dict = {}
    en_lectura = False
    try:
        texto = entrada
        if es_archivo(entrada):
            if c.ocr is None:
                raise FlujoDetenido("La entrada es un archivo (foto o PDF), pero no hay un componente OCR configurado")
            en_lectura = True
            yield _paso("lectura", "en_curso")

            def leer() -> str:
                with _cronometro(metricas, "ocr"):
                    return c.ocr(entrada.strip())

            texto = resultado["texto_ocr"] = await asyncio.to_thread(leer)
            en_lectura = False
            yield _paso("lectura", "listo", {"texto_ocr": texto})

        yield _paso("proteccion", "en_curso")

        def proteger() -> str:
            with _cronometro(metricas, "anonimizar"):
                return anonimizar(texto, c.ner, mapa)

        resultado["texto_anon"] = await asyncio.to_thread(proteger)
        yield _paso("proteccion", "listo", {"texto_anon": resultado["texto_anon"]})

        yield _paso("verificacion", "en_curso")
        # El grafo corre en una tarea aparte y vuelca sus cambios en la misma cola donde los pasos dejan sus `detalle`
        # (desde hilos, de ahí call_soon_threadsafe): así el avance dentro de un paso sale mientras el paso corre.
        cola: asyncio.Queue = asyncio.Queue()
        bucle = asyncio.get_running_loop()
        registrar_emisor(lambda evento: bucle.call_soon_threadsafe(cola.put_nowait, ("detalle", evento)))

        async def bombear() -> None:
            try:
                flujo = construir_workflow(c, metricas).astream({"texto_anon": resultado["texto_anon"]}, stream_mode="updates")
                async with aclosing(flujo):
                    async for cambio in flujo:
                        await cola.put(("cambio", cambio))
                await cola.put(("fin", None))
            except Exception as e:  # noqa: BLE001  se vuelve a levantar abajo, en el generador
                await cola.put(("error", e))

        tarea = asyncio.ensure_future(bombear())
        try:
            while True:
                clase, valor = await cola.get()
                if clase == "detalle":
                    yield valor
                elif clase == "error":
                    raise valor
                elif clase == "fin":
                    break
                else:
                    for nodo, datos in valor.items():
                        final.update(datos)
                        paso_id = _NODO_A_PASO[nodo]
                        yield _paso(paso_id, "listo", final)
                        if paso_id in _PASO_SIGUIENTE and not (paso_id == "verificacion" and not final.get("continuar")):
                            yield _paso(_PASO_SIGUIENTE[paso_id], "en_curso")
        finally:
            if not tarea.done():
                tarea.cancel()
            await asyncio.gather(tarea, return_exceptions=True)
    except Exception as e:
        resultado["razon"] = str(e) if isinstance(e, FlujoDetenido) else f"Falla inesperada ({type(e).__name__}): {e}"
        resultado["razon_amigable"] = _razon_amigable_error(e, en_lectura)
        resultado["latencias"] = dict(metricas)
        yield {"tipo": "resultado", "resultado": resultado}
        return
    resultado["latencias"] = dict(metricas)

    resultado["prob_clinico"] = final.get("prob_clinico")
    if not final.get("continuar"):
        resultado["estado_final"] = "fuera_de_alcance"
        resultado["razon"] = (
            f"Probabilidad de contexto clínico {final.get('prob_clinico')} por debajo del umbral {c.umbral}"
        )
        resultado["razon_amigable"] = RAZON_FUERA_DE_ALCANCE
        yield {"tipo": "resultado", "resultado": resultado}
        return

    reporte_md, desconocidos = mapa.reinsertar(final["reporte_md"])
    reporte, desconocidos_datos = mapa.reinsertar_datos(final["reporte_datos"])
    sin_valor = desconocidos + [d for d in dict.fromkeys(desconocidos_datos) if d not in desconocidos]
    sin_valor_frases, sin_valor_tecnicas = separar_advertencias([("dato_sin_restablecer", p) for p in sin_valor])
    resultado.update(
        estado_final="ok",
        sintomas=final["sintomas"],
        candidatos=final["candidatos"],
        alternativas=final["alternativas"],
        guias=final.get("guias", []),
        traza_tools=final["traza_tools"],
        rondas_busqueda_cie11=final["rondas_busqueda_cie11"],
        reporte_md=reporte_md,
        reporte=reporte,
        advertencias=list(dict.fromkeys(final.get("advertencias", []) + sin_valor_frases)),
        advertencias_tecnicas=final.get("advertencias_tecnicas", []) + sin_valor_tecnicas,
    )
    yield {"tipo": "resultado", "resultado": resultado}


async def proteger_eventos(entrada: str, c: Componentes) -> AsyncIterator[dict]:
    """Primera mitad del flujo, para que la persona confirme antes de que algo llegue a los modelos de análisis: lee el archivo
    (si lo hay) y oculta los datos personales. Emite los pasos `lectura` y `proteccion` y termina con un evento `confirmar`
    ({texto_original, texto_protegido}); no consulta ningún modelo de análisis. Ante un fallo termina con un `resultado` de error."""
    entrada = str(entrada)
    resultado = {"estado_final": "error", "razon": "", "razon_amigable": ""}
    if not entrada.strip():
        resultado["razon"] = "La entrada está vacía"
        resultado["razon_amigable"] = _razon_amigable_error(FlujoDetenido(resultado["razon"]), False)
        yield {"tipo": "resultado", "resultado": resultado}
        return
    mapa, metricas = MapaPII(), {}
    en_lectura = False
    try:
        texto = entrada
        if es_archivo(entrada):
            if c.ocr is None:
                raise FlujoDetenido("La entrada es un archivo (foto o PDF), pero no hay un componente OCR configurado")
            en_lectura = True
            yield _paso("lectura", "en_curso")

            def leer() -> str:
                with _cronometro(metricas, "ocr"):
                    return c.ocr(entrada.strip())

            texto = await asyncio.to_thread(leer)
            en_lectura = False
            yield _paso("lectura", "listo", {"texto_ocr": texto})

        yield _paso("proteccion", "en_curso")
        protegido = await asyncio.to_thread(lambda: anonimizar(texto, c.ner, mapa))
        yield _paso("proteccion", "listo", {"texto_anon": protegido})
        yield {"tipo": "confirmar", "texto_original": texto, "texto_protegido": protegido}
    except Exception as e:
        resultado["razon"] = str(e) if isinstance(e, FlujoDetenido) else f"Falla inesperada ({type(e).__name__}): {e}"
        resultado["razon_amigable"] = _razon_amigable_error(e, en_lectura)
        yield {"tipo": "resultado", "resultado": resultado}


async def ejecutar(entrada: str, c: Componentes) -> dict:
    """Si la entrada es la ruta de una foto o un PDF la lee con OCR; anonimiza (fuera del grafo, para que el original no quede en las trazas),
    corre el grafo y reinserta los nombres. `texto_ocr` devuelve el texto leído para que se revise."""
    resultado: dict = {}
    async for evento in ejecutar_eventos(entrada, c):
        if evento["tipo"] == "resultado":
            resultado = evento["resultado"]
    return resultado
