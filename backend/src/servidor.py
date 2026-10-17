"""API del MVP de apoyo al psicodiagnóstico (FastAPI en Vercel).

POST /api/caso recibe el caso (texto o foto/PDF) y responde un stream de eventos (SSE) con el avance y el resultado.
Antes de procesar: código de acceso, límite por visitante y validación de la entrada.
En los registros solo quedan id, estado, tiempo y vía (texto|archivo): nunca el caso, el texto leído ni los eventos."""
from __future__ import annotations

import asyncio
import dataclasses
import hmac
import io
import json
import logging
import os
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from errores_api import ErrorApi, cuerpo_error, limpiar_texto, respuesta_error
from psi_diag.errores import FlujoDetenido

BACKEND = "langchain"
MAX_POR_MINUTO = int(os.getenv("MAX_POR_MINUTO", "8"))   # consultas por minuto y por visitante
MIN_TEXTO, MAX_TEXTO = 20, 8000
MAX_TEXTO_LEIDO = 40_000   # el texto que salió del OCR de un archivo (hasta 10 páginas) y ya confirmó la persona
MAX_BYTES_ARCHIVO = 4_000_000
MAX_BYTES_TOTAL = 4_200_000   # suma de todos los archivos de una solicitud: Vercel rechaza cuerpos de más de 4.5 MB
MAX_ARCHIVOS = 10             # hasta 10 imágenes (notas en varias hojas) o un solo PDF
MAX_PAGINAS_PDF = 10
PING_S = 15
MAX_BYTES_REPORTE = 200_000   # cuerpo máximo de POST /api/exportar
CLAVES_REPORTE = ("caso", "sintomas", "hipotesis", "aviso")   # lo mínimo para aceptar el JSON como reporte
FORMATOS_EXPORTAR = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}
FIRMAS = {".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",), ".png": (b"\x89PNG",), ".pdf": (b"%PDF-",)}
RAIZ = Path(__file__).resolve().parents[2]   # raíz del repositorio (servidor.py está en backend/src/)
FIXTURE_DEMO = RAIZ / "backend" / "tests" / "fixtures" / "eventos_demo.json"

log = logging.getLogger("psico")
# Las líneas salen por stdout: en los registros de Vercel lo que sale por stderr se marca como «error».
if not any(getattr(h, "_psico", False) for h in log.handlers):
    _salida = logging.StreamHandler(sys.stdout)
    _salida._psico = True
    _salida.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_salida)
log.setLevel(logging.INFO)
log.propagate = False
for _nombre in ("httpx", "httpcore", "httpx2", "httpcore2"):  # anotan en INFO cada URL que llaman
    logging.getLogger(_nombre).setLevel(logging.WARNING)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Para pruebas: si no es None, se usa en lugar de armar los componentes reales (sin red).
componentes_de_prueba = None


# ----------------------------------------------------------------------------- utilidades
def registrar(**campos: Any) -> None:
    """Una línea JSON por solicitud. Nunca incluyas aquí el caso, el texto leído ni los eventos."""
    log.info(json.dumps(campos, ensure_ascii=False))


def responder(cuerpo: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(cuerpo, status_code=status, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def milisegundos(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)


def ip_de(request: Request) -> str:
    """IP del visitante. En Vercel llega en x-real-ip / x-forwarded-for."""
    directa = request.headers.get("x-real-ip")
    if directa:
        return directa.strip()
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "desconocida"


def en_vercel() -> bool:
    return bool(os.getenv("VERCEL"))


def modo_demo() -> bool:
    return os.getenv("MODO_DEMO") == "1" and not en_vercel()


# ----------------------------------------------------------------------------- 1. código de acceso
MAX_FALLOS_ACCESO = 5   # una vez superado, el visitante queda bloqueado (aun con el código correcto) hasta 60 s: es aceptable
_fallos: dict[str, deque] = defaultdict(deque)   # intentos fallidos de código por visitante, última hora de 60 s


def _fallos_recientes(visitante: str) -> deque:
    ahora = time.monotonic()
    marcas = _fallos[visitante]
    while marcas and ahora - marcas[0] > 60:
        marcas.popleft()
    if len(_fallos) > 2000:
        for clave in [k for k, v in _fallos.items() if not v or ahora - v[-1] > 60]:
            del _fallos[clave]
    return marcas


def revisar_acceso(request: Request) -> None:
    esperado = os.getenv("ACCESS_CODE", "").strip()
    if not esperado:
        if en_vercel():  # en producción nunca queda abierto por olvido
            raise ErrorApi("sin_configurar", "Falta la variable de entorno ACCESS_CODE en Vercel.", 503, "define ACCESS_CODE y vuelve a desplegar")
        return
    visitante = ip_de(request)
    fallos = _fallos_recientes(visitante)
    if len(fallos) >= MAX_FALLOS_ACCESO:  # frena la fuerza bruta del código compartido
        raise ErrorApi("limite", "Demasiados intentos con un código incorrecto. Espera un momento.", 429,
                       f"máximo {MAX_FALLOS_ACCESO} intentos fallidos por minuto", True)
    recibido = request.headers.get("x-access-code", "").strip()
    if not hmac.compare_digest(recibido.encode(), esperado.encode()):
        fallos.append(time.monotonic())
        raise ErrorApi("acceso", "El código de acceso no es correcto.", 401, "falta o no coincide x-access-code")


# ----------------------------------------------------------------------------- 2. límite por visitante
# De mejor esfuerzo: la memoria es de cada instancia de la función. Frena errores (un bucle, un botón pulsado mil veces).
_visitas: dict[str, deque] = defaultdict(deque)


def limitar(visitante: str) -> None:
    ahora = time.monotonic()
    marcas = _visitas[visitante]
    while marcas and ahora - marcas[0] > 60:
        marcas.popleft()
    if len(marcas) >= MAX_POR_MINUTO:
        raise ErrorApi("limite", "Hay demasiadas solicitudes seguidas. Espera un momento y vuelve a intentar.", 429,
                       f"máximo {MAX_POR_MINUTO} por minuto", True)
    marcas.append(ahora)
    if len(_visitas) > 2000:
        for clave in [k for k, v in _visitas.items() if not v or ahora - v[-1] > 60]:
            del _visitas[clave]


# ----------------------------------------------------------------------------- 3. validación de la entrada
def _validar_archivo(nombre: str, datos: bytes) -> str:
    """Devuelve la extensión si el archivo es aceptable: tamaño, extensión, firma de bytes y que abra de verdad."""
    if len(datos) > MAX_BYTES_ARCHIVO:
        raise ErrorApi("archivo", "El archivo es demasiado grande (máximo 4 MB).", 413, f"{len(datos)} bytes")
    extension = Path(nombre or "").suffix.lower()
    if extension not in FIRMAS:
        raise ErrorApi("archivo", "Solo se aceptan fotos JPG o PNG y archivos PDF.", 400, f"extensión {extension or 'ausente'}")
    if not datos.startswith(FIRMAS[extension]):
        raise ErrorApi("archivo", "El contenido del archivo no corresponde a su extensión.", 400, "firma de bytes distinta")
    try:
        if extension == ".pdf":
            from pypdf import PdfReader
            lector = PdfReader(io.BytesIO(datos))
            if lector.is_encrypted:
                raise ErrorApi("archivo", "El PDF está protegido con contraseña.", 400, "pdf cifrado")
            paginas = len(lector.pages)
        else:
            from PIL import Image
            from psi_diag.ocr import ERRORES_BOMBA, bomba_como_error, dimensiones_aceptables, MENSAJE_IMAGEN_GRANDE
            try:
                with bomba_como_error(), Image.open(io.BytesIO(datos)) as imagen:
                    ancho, alto = imagen.size   # solo el encabezado: una imagen enorme no se decodifica nunca
                    if not dimensiones_aceptables(ancho, alto):
                        raise ErrorApi("archivo", MENSAJE_IMAGEN_GRANDE, 400, f"imagen de {ancho}x{alto} px")
                    imagen.verify()
            except ERRORES_BOMBA:
                raise ErrorApi("archivo", MENSAJE_IMAGEN_GRANDE, 400, "imagen con demasiados píxeles") from None
            paginas = 1
    except ErrorApi:
        raise
    except Exception:  # noqa: BLE001  cualquier fallo al abrirlo = archivo dañado
        raise ErrorApi("archivo", "No se pudo abrir el archivo; parece dañado.", 400, "archivo corrupto") from None
    if paginas > MAX_PAGINAS_PDF:
        raise ErrorApi("archivo", f"El PDF tiene más de {MAX_PAGINAS_PDF} páginas.", 400, f"{paginas} páginas")
    return extension


async def leer_entrada(request: Request) -> tuple[str, str | None, bytes | None, str]:
    """Devuelve (via, texto, bytes del archivo, extensión del archivo) ya validados."""
    declarado = request.headers.get("content-length", "")
    if declarado.isdigit() and int(declarado) > MAX_BYTES_TOTAL + 250_000:
        raise ErrorApi("archivo", "Los archivos son demasiado grandes (máximo 4 MB en total).", 413, "cuerpo mayor a 4 MB")
    try:
        formulario = await request.form(max_files=MAX_ARCHIVOS + 1, max_fields=10)
    except Exception:  # noqa: BLE001
        raise ErrorApi("validacion", "La solicitud no es válida.", 400, "no es multipart/form-data") from None
    try:
        return await _entrada_de(formulario)
    finally:
        await formulario.close()   # libera ya el archivo subido (datos personales), sin esperar al recolector


def _valores(formulario, campo: str) -> list:
    if hasattr(formulario, "getlist"):
        return formulario.getlist(campo)
    return [formulario[campo]] if campo in formulario else []


async def _entrada_de(formulario) -> tuple[str, str | None, bytes | None, str]:
    texto = formulario.get("texto")
    archivos = [a for campo in ("archivos", "archivo") for a in _valores(formulario, campo) if hasattr(a, "read")]
    tiene_texto = isinstance(texto, str) and texto.strip() != ""
    if tiene_texto and archivos:
        raise ErrorApi("validacion", "Envía el texto del caso o un archivo, no ambos.", 400, "texto y archivo a la vez")
    if archivos:
        if str(formulario.get("confirma_ocr", "")).strip().lower() != "true":
            raise ErrorApi("ocr", "Confirma que aceptas que el archivo se lea con servicios externos (OpenRouter y Mistral).", 400, "falta confirma_ocr=true")
        if len(archivos) > MAX_ARCHIVOS:
            raise ErrorApi("archivo", f"Puedes subir hasta {MAX_ARCHIVOS} imágenes o un PDF.", 400, f"{len(archivos)} archivos")
        contenidos, total = [], 0
        for archivo in archivos:
            datos = await archivo.read(MAX_BYTES_ARCHIVO + 1)
            total += len(datos)
            if total > MAX_BYTES_TOTAL:
                raise ErrorApi("archivo", "Los archivos son demasiado grandes (máximo 4 MB en total).", 413, f"{total} bytes")
            contenidos.append((archivo.filename or "", datos))
        extensiones = [await asyncio.to_thread(_validar_archivo, nombre, datos) for nombre, datos in contenidos]   # pypdf y Pillow son síncronos
        if len(contenidos) == 1:
            return "archivo", None, contenidos[0][1], extensiones[0]
        if ".pdf" in extensiones:
            raise ErrorApi("archivo", "Sube un solo PDF o varias imágenes, sin mezclarlos.", 400, "varios archivos con un PDF")
        from psi_diag.ocr import OcrError, imagenes_a_pdf
        try:   # las hojas viajan como un solo PDF, una página por imagen y en el orden en que se eligieron
            unido = await asyncio.to_thread(imagenes_a_pdf, [(n or f"imagen {i + 1}", d) for i, (n, d) in enumerate(contenidos)])
        except OcrError as e:
            raise ErrorApi("archivo", str(e).split(": ", 1)[-1], 400, "no se pudieron unir las imágenes") from None
        return "archivo", None, unido, ".pdf"
    if not tiene_texto:
        raise ErrorApi("validacion", "Escribe el caso o sube un archivo.", 400, "falta texto o archivo")
    maximo = MAX_TEXTO_LEIDO if str(formulario.get("leido", "")).strip().lower() == "true" else MAX_TEXTO
    limpio = limpiar_texto(texto, maximo + 1)
    if not MIN_TEXTO <= len(limpio) <= maximo:
        raise ErrorApi("validacion", f"El texto debe tener entre {MIN_TEXTO} y {maximo} caracteres.", 400, f"{len(limpio)} caracteres")
    from psi_diag.ocr import es_archivo
    if es_archivo(limpio):  # un texto que parece una ruta haría que el flujo intentara leer un archivo del servidor
        raise ErrorApi("validacion", "Describe el caso con palabras; el texto no puede ser solo un nombre de archivo.", 400, "texto con forma de ruta")
    return "texto", limpio, None, ""


# ----------------------------------------------------------------------------- 4. flujo
CAMPOS_RESULTADO_CLIENTE = ("estado_final", "razon_amigable", "reporte", "advertencias")   # el texto del OCR va solo en el paso «lectura»


def resultado_para_cliente(resultado: dict) -> dict:
    """Lista blanca de lo que ve el navegador. `razon` (mensajes de excepciones, nombres de tools, URLs), la traza,
    las latencias, los candidatos, etc. se quedan en el servidor: ninguna pantalla los necesita."""
    return {campo: resultado[campo] for campo in CAMPOS_RESULTADO_CLIENTE if campo in resultado}


PASOS_MEDIDOS = ("ocr", "anonimizar", "guardrail", "extraer", "busqueda_cie11", "guias", "reporte")


def pasos_ms(latencias) -> dict:
    """Milisegundos por paso para el registro: solo nombres fijos y números (nunca texto del caso)."""
    if not isinstance(latencias, dict):
        return {}
    return {n: int(latencias[n] * 1000) for n in PASOS_MEDIDOS
            if isinstance(latencias.get(n), (int, float)) and not isinstance(latencias.get(n), bool)}


def evento_para_cliente(evento: dict) -> dict:
    if evento.get("tipo") == "resultado":
        return {**evento, "resultado": resultado_para_cliente(evento.get("resultado") or {})}
    return evento


def evento_sse(evento: dict) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"


async def resolver_componentes():
    if componentes_de_prueba is not None:
        return componentes_de_prueba
    from componentes import obtener_componentes
    return await obtener_componentes()


def instancia_fria() -> bool:
    """True si esta instancia todavía tiene que cargar el modelo NER y conectarse a la CIE-11 (primera consulta tras dormir)."""
    if componentes_de_prueba is not None:
        return False
    from componentes import componentes_listos
    return not componentes_listos()


def evento_conexion(estado: str) -> dict:
    from psi_diag.grafo import _paso
    return _paso("conexion", estado)


def _soltar_archivo(ruta: Path | None, activo: threading.Event, fin: threading.Event) -> None:
    """Borra el archivo temporal. Un hilo de OCR no se puede interrumpir: si sigue leyendo, se borra al terminar."""
    if ruta is None:
        return

    def borrar() -> None:
        ruta.unlink(missing_ok=True)

    if activo.is_set() and not fin.is_set():
        def esperar_y_borrar() -> None:
            fin.wait()
            borrar()
        threading.Thread(target=esperar_y_borrar, daemon=True).start()
    else:
        borrar()


async def transmitir(entrada: str, ruta: Path | None, id_solicitud: str, via: str,
                     activo: threading.Event | None = None, fin: threading.Event | None = None,
                     generador=None) -> AsyncIterator[str]:
    """Genera el stream SSE. El archivo temporal (`ruta`) se borra siempre, incluso si el cliente se desconecta.
    `generador(entrada, componentes)` produce los eventos: por omisión el flujo completo; `proteger_eventos` es la primera mitad."""
    from psi_diag.grafo import ejecutar_eventos
    generador = generador or ejecutar_eventos

    inicio = time.perf_counter()
    activo, fin = activo or threading.Event(), fin or threading.Event()
    estado = "error"
    tiempos: dict = {}
    siguiente: asyncio.Future | None = None
    flujo = None
    try:
        try:
            limite = float(os.getenv("BACKEND_TIMEOUT_S", "280"))
        except ValueError:
            limite = 280.0
        deadline = time.monotonic() + limite
        try:
            fria = instancia_fria()
            if fria:   # el arranque en frío tarda: se avisa para que la pantalla no parezca detenida
                yield evento_sse(evento_conexion("en_curso"))
            try:
                c = await asyncio.wait_for(resolver_componentes(), timeout=limite)
            except FlujoDetenido:   # p. ej. el servidor de la CIE-11 no respondió al arrancar: se puede reintentar
                raise ErrorApi("backend", "El servicio de consulta de la CIE-11 no respondió. Puedes intentarlo de nuevo en un momento.",
                               503, "servicio de consulta no disponible", True) from None
            if fria:
                yield evento_sse(evento_conexion("listo"))
            if c.ocr is not None:
                original = c.ocr

                def ocr_vigilado(r: str) -> str:
                    activo.set()
                    try:
                        return original(r)
                    finally:
                        fin.set()
                c = dataclasses.replace(c, ocr=ocr_vigilado)
            flujo = generador(entrada, c)
            while True:
                siguiente = asyncio.ensure_future(flujo.__anext__())
                while not siguiente.done():
                    restante = deadline - time.monotonic()
                    if restante <= 0:
                        raise asyncio.TimeoutError
                    await asyncio.wait({siguiente}, timeout=min(PING_S, restante))
                    if not siguiente.done() and deadline - time.monotonic() > 0:
                        yield ": ping\n\n"
                try:
                    evento = siguiente.result()
                except StopAsyncIteration:
                    break
                if evento.get("tipo") == "resultado":
                    estado = evento["resultado"].get("estado_final", "error")
                    tiempos = pasos_ms(evento["resultado"].get("latencias"))
                elif evento.get("tipo") == "confirmar":
                    estado = "confirmar"
                yield evento_sse(evento_para_cliente(evento))
        except asyncio.TimeoutError:
            error = ErrorApi("timeout", "El análisis tardó demasiado. Puedes intentarlo de nuevo.", 504, f"sin respuesta en {limite:g} s", True)
            estado = "timeout"
            yield evento_sse({"tipo": "error", "error": cuerpo_error(error)})
        except ErrorApi as e:
            estado = e.codigo
            yield evento_sse({"tipo": "error", "error": cuerpo_error(e)})
        except Exception as e:  # noqa: BLE001  nunca se manda un traceback ni el mensaje de la excepción (podría llevar texto del caso)
            estado = "backend"
            error = ErrorApi("backend", "Error inesperado al procesar el caso.", 500, type(e).__name__)
            yield evento_sse({"tipo": "error", "error": cuerpo_error(error)})
    finally:
        if siguiente is not None and not siguiente.done():
            siguiente.cancel()
        if flujo is not None and siguiente is not None and siguiente.done():
            try:
                await flujo.aclose()
            except BaseException:  # noqa: BLE001  se está cerrando; lo único que importa es borrar el archivo
                pass
        _soltar_archivo(ruta, activo, fin)
        registrar(id=id_solicitud, estado=estado, ms=milisegundos(inicio), via=via, pasos_ms=tiempos)


async def transmitir_demo(id_solicitud: str, via: str) -> AsyncIterator[str]:
    inicio = time.perf_counter()
    try:
        pausa = float(os.getenv("DEMO_PAUSA_S", "0.4"))
    except ValueError:
        pausa = 0.4
    eventos = json.loads(FIXTURE_DEMO.read_text(encoding="utf-8"))
    try:
        for evento in eventos:
            yield evento_sse(evento_para_cliente(evento))
            if pausa > 0:
                await asyncio.sleep(pausa)
    finally:
        registrar(id=id_solicitud, estado="demo", ms=milisegundos(inicio), via=via)


async def transmitir_demo_proteccion(id_solicitud: str, via: str) -> AsyncIterator[str]:
    """Demo de la primera mitad: los pasos de lectura y protección del caso de demostración y la pantalla de confirmación."""
    inicio = time.perf_counter()
    try:
        pausa = float(os.getenv("DEMO_PAUSA_S", "0.4"))
    except ValueError:
        pausa = 0.4
    eventos = json.loads(FIXTURE_DEMO.read_text(encoding="utf-8"))
    pasos = [e for e in eventos if e.get("tipo") == "paso" and e.get("id") in ("lectura", "proteccion")]
    lectura = next((e["detalle"]["lineas"] for e in pasos if e["id"] == "lectura" and e.get("estado") == "listo"), [])
    protegido = next((e["detalle"]["lineas"] for e in pasos if e["id"] == "proteccion" and e.get("estado") == "listo"), [])
    cierre = {"tipo": "confirmar", "texto_original": "\n".join(map(str, lectura)), "texto_protegido": "\n".join(map(str, protegido[-1:]))}
    try:
        for evento in [*pasos, cierre]:
            yield evento_sse(evento)
            if pausa > 0:
                await asyncio.sleep(pausa)
    finally:
        registrar(id=id_solicitud, estado="demo", ms=milisegundos(inicio), via=via)


# ----------------------------------------------------------------------------- rutas
@app.get("/api/health")
def salud() -> dict:
    """La pantalla consulta aquí si hay clave configurada y si pide código. No revela secretos."""
    return {
        "ok": True,
        "configurado": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
        "requiere_codigo": bool(os.getenv("ACCESS_CODE", "").strip()),
    }


@app.get("/api/calentar")
async def calentar():
    """La pantalla lo llama al abrirse, sin esperar la respuesta: arma el modelo NER y la conexión a la CIE-11 en esta
    instancia para que el primer caso no pague el arranque en frío. Responde cuando termina (en Vercel una instancia
    puede congelarse al responder, así que no se deja trabajo en segundo plano). No procesa nada ni usa el LLM."""
    cabeceras = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if modo_demo() or (componentes_de_prueba is None and not os.getenv("OPENROUTER_API_KEY", "").strip()):
        return responder({"listo": False}, 200)
    inicio = time.perf_counter()
    try:
        await asyncio.wait_for(resolver_componentes(), timeout=120)
        estado = "ok"
    except Exception as e:  # noqa: BLE001  el arranque se reintenta con la primera consulta real
        estado = type(e).__name__
    registrar(id=uuid.uuid4().hex[:8], estado=estado, ms=milisegundos(inicio), via="calentar")
    return responder({"listo": estado == "ok"}, 200)


@app.post("/api/acceso")
async def acceso(request: Request):
    """Comprueba el código de acceso sin procesar nada ni llamar a ningún servicio: la pantalla de inicio lo usa para avisar
    de un código incorrecto antes de que se suba un caso. Comparte con /api/caso el límite de uso y el tope de intentos fallidos."""
    inicio = time.perf_counter()
    id_solicitud = uuid.uuid4().hex[:8]
    estado = "ok"
    try:
        limitar(ip_de(request))
        revisar_acceso(request)
        return responder({"ok": True})
    except ErrorApi as e:
        estado = e.codigo
        return responder(respuesta_error(e, id_solicitud, BACKEND), e.status)
    finally:
        registrar(id=id_solicitud, estado=estado, ms=milisegundos(inicio), via="acceso")


async def _atender(request: Request, generador=None, demo=None):
    """Valida la solicitud y responde el stream. `generador` y `demo` eligen qué mitad del flujo corre (por omisión, el flujo completo)."""
    inicio = time.perf_counter()
    id_solicitud = uuid.uuid4().hex[:8]
    via = "desconocida"
    ruta: Path | None = None
    try:
        limitar(ip_de(request))   # primero el límite: así también cuentan los intentos con código incorrecto
        revisar_acceso(request)
        via, texto, datos, extension = await leer_entrada(request)
        cabeceras = {"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"}
        if modo_demo():
            return StreamingResponse((demo or transmitir_demo)(id_solicitud, via), media_type="text/event-stream", headers=cabeceras)
        if componentes_de_prueba is None and not os.getenv("OPENROUTER_API_KEY", "").strip():
            raise ErrorApi("sin_configurar", "Falta la variable de entorno OPENROUTER_API_KEY en Vercel.", 503,
                           "define OPENROUTER_API_KEY y vuelve a desplegar")
        if datos is not None:
            descriptor, nombre = tempfile.mkstemp(suffix=extension, prefix="caso_")
            ruta = Path(nombre)
            with os.fdopen(descriptor, "wb") as destino:
                destino.write(datos)
            entrada = str(ruta)
        else:
            entrada = texto
        activo, fin = threading.Event(), threading.Event()
        # Respaldo: si el cliente se va antes de que el generador arranque, su `finally` no corre; esto borra el archivo
        # (idempotente, y respeta al hilo del OCR si sigue leyendo).
        respaldo = BackgroundTask(_soltar_archivo, ruta, activo, fin)
        return StreamingResponse(transmitir(entrada, ruta, id_solicitud, via, activo, fin, *([generador] if generador else [])), media_type="text/event-stream",
                                 headers=cabeceras, background=respaldo)
    except ErrorApi as e:
        if ruta is not None:
            ruta.unlink(missing_ok=True)
        registrar(id=id_solicitud, estado=e.codigo, ms=milisegundos(inicio), via=via)
        return responder(respuesta_error(e, id_solicitud, BACKEND), e.status)
    except Exception as e:  # noqa: BLE001
        if ruta is not None:
            ruta.unlink(missing_ok=True)
        registrar(id=id_solicitud, estado="backend", ms=milisegundos(inicio), via=via, error=type(e).__name__)
        return responder(respuesta_error(ErrorApi("backend", "Error inesperado en la función.", 500, type(e).__name__), id_solicitud, BACKEND), 500)


@app.post("/api/caso")
async def caso(request: Request):
    return await _atender(request)


@app.post("/api/proteger")
async def proteger(request: Request):
    """Primera mitad del análisis: lee el archivo (si lo hay) y oculta los datos personales, y devuelve el texto original y el
    protegido para que la persona confirme antes de que algo llegue a los modelos de análisis."""
    from psi_diag.grafo import proteger_eventos
    return await _atender(request, proteger_eventos, transmitir_demo_proteccion)


# ----------------------------------------------------------------------------- exportación
async def leer_reporte(request: Request) -> dict:
    """Cuerpo JSON del reporte: tope de tamaño (aun sin Content-Length), objeto con las claves mínimas."""
    declarado = request.headers.get("content-length", "")
    if declarado.isdigit() and int(declarado) > MAX_BYTES_REPORTE:
        raise ErrorApi("validacion", "El reporte es demasiado grande para exportarlo.", 413, f"más de {MAX_BYTES_REPORTE} bytes")
    partes, total = [], 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > MAX_BYTES_REPORTE:
            raise ErrorApi("validacion", "El reporte es demasiado grande para exportarlo.", 413, f"más de {MAX_BYTES_REPORTE} bytes")
        partes.append(trozo)
    try:
        reporte = json.loads(b"".join(partes))
    except ValueError:
        raise ErrorApi("validacion", "El reporte no es un JSON válido.", 400, "cuerpo no es JSON") from None
    if not isinstance(reporte, dict) or any(clave not in reporte for clave in CLAVES_REPORTE):
        raise ErrorApi("validacion", "El reporte no tiene la forma esperada.", 400, "faltan claves del reporte")
    return reporte


@app.post("/api/exportar/{formato}")
async def exportar(formato: str, request: Request):
    inicio = time.perf_counter()
    id_solicitud = uuid.uuid4().hex[:8]
    estado = "ok"
    try:
        limitar(ip_de(request))
        revisar_acceso(request)
        if formato not in FORMATOS_EXPORTAR:
            raise ErrorApi("validacion", "Formato no disponible: usa docx o pdf.", 404, "formato no reconocido")
        reporte = await leer_reporte(request)
        from exportar.comun import fecha_iso   # importación diferida: reportlab y python-docx pesan en el arranque
        if formato == "docx":
            from exportar.docx import generar_docx as generar
        else:
            from exportar.pdf import generar_pdf as generar
        datos = await asyncio.to_thread(generar, reporte)
        cabeceras = {
            "Content-Disposition": f'attachment; filename="reporte-{fecha_iso(reporte)}.{formato}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        }
        return Response(datos, media_type=FORMATOS_EXPORTAR[formato], headers=cabeceras)
    except ErrorApi as e:
        estado = e.codigo
        return responder(respuesta_error(e, id_solicitud, BACKEND), e.status)
    except Exception as e:  # noqa: BLE001  el mensaje de la excepción podría traer texto del reporte: no se registra
        estado = "backend"
        return responder(respuesta_error(ErrorApi("backend", "No se pudo generar el archivo.", 500, type(e).__name__), id_solicitud, BACKEND), 500)
    finally:
        registrar(id=id_solicitud, formato=formato if formato in FORMATOS_EXPORTAR else "otro", ms=milisegundos(inicio), estado=estado)


# ----------------------------------------------------------------------------- pantalla (solo en local)
# En Vercel, public/ lo sirve la plataforma con las cabeceras de vercel.json. En local se sirve igual, con esas mismas
# cabeceras, para que la CSP se pruebe tal como quedará en producción.
if not en_vercel():
    from starlette.staticfiles import StaticFiles

    _VERCEL_JSON = RAIZ / "vercel.json"

    @app.middleware("http")
    async def cabeceras_locales(request: Request, call_next):
        respuesta = await call_next(request)
        if not request.url.path.startswith("/api/"):
            # Solo en local: que el navegador revise siempre si hay una versión nueva de la página (sin esto puede enseñar una copia vieja).
            respuesta.headers["Cache-Control"] = "no-cache"
            try:
                reglas = json.loads(_VERCEL_JSON.read_text(encoding="utf-8")).get("headers", [])
                for regla in reglas:
                    for cabecera in regla.get("headers", []):
                        respuesta.headers[cabecera["key"]] = cabecera["value"]
            except (OSError, ValueError, KeyError):
                pass
        return respuesta

    app.mount("/", StaticFiles(directory=RAIZ / "public", html=True), name="pantalla")
