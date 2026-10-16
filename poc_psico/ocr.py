"""OCR de notas manuscritas (foto o PDF) con Mistral OCR vía OpenRouter (el archivo sale a esos servicios sin anonimizar)."""
import base64
import io
import pathlib
import re
import time

import requests
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .errores import FlujoDetenido
from .peticiones import URL_OPENROUTER, post_openrouter
from .reintentos import con_reintentos_503

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png"}
EXTENSIONES = EXTENSIONES_IMAGEN | {".pdf"}
# El plugin file-parser solo parsea PDF (un JPEG directo responde 200 sin texto). El modelo de chat solo acompaña
# la petición: su respuesta se ignora y max_tokens bajo evita esperar su generación (spike 2026-10-14).
MODELO_ACOMPANANTE = "openai/gpt-4o-mini"
LADO_MAXIMO_MISTRAL = 2000
MAX_PAGINAS_PDF = 10


class OcrError(FlujoDetenido):
    """No se pudo leer el archivo; el flujo no continúa con texto inventado o incompleto."""


def es_archivo(entrada) -> bool:
    """True si la entrada es la ruta de una foto o un PDF y no una viñeta en texto."""
    texto = str(entrada).strip()
    return bool(texto) and "\n" not in texto and len(texto) < 500 and pathlib.Path(texto).suffix.lower() in EXTENSIONES


def _exigir_archivo(ruta: pathlib.Path) -> None:
    if not ruta.is_file():
        raise OcrError(f"El archivo no existe: {ruta}")


def _base64(datos: bytes) -> str:
    return base64.b64encode(datos).decode()


def _cargar(ruta: pathlib.Path, lado: int) -> Image.Image:
    _exigir_archivo(ruta)
    try:
        with Image.open(ruta) as original:
            imagen = original.convert("RGB")  # descarta la transparencia de los PNG
    except (UnidentifiedImageError, OSError) as e:
        raise OcrError(f"No se pudo abrir {ruta.name} como imagen: {e}") from e
    imagen.thumbnail((lado, lado))
    return imagen


def _codificar(imagen: Image.Image, formato: str, **opciones) -> str:
    salida = io.BytesIO()
    imagen.save(salida, formato, **opciones)
    return _base64(salida.getvalue())


def _saturado(error: Exception) -> bool:
    """503, 429 o el 400 "rate limited" que el motor de parseo responde de forma intermitente (reintentos 1, 2 y 4 s)."""
    codigo = getattr(error, "status_code", None)
    return codigo in (429, 503) or (codigo == 400 and "rate limit" in str(error).lower())


def _texto_de_anotaciones(respuesta: dict) -> str:
    anotaciones = respuesta["choices"][0]["message"].get("annotations") or []
    partes = [
        parte.get("text", "")
        for a in anotaciones if a.get("type") == "file"
        for parte in a["file"].get("content", []) if parte.get("type") == "text"
    ]
    return re.sub(r"</?file\b[^>]*>", "", "\n".join(partes)).strip()


def _pdf_base64(ruta: pathlib.Path) -> str:
    """Un PDF se envía tal cual; una foto se convierte a un PDF de una página (el plugin no lee un JPEG directo)."""
    if ruta.suffix.lower() != ".pdf":
        return _codificar(_cargar(ruta, LADO_MAXIMO_MISTRAL), "PDF", resolution=150)
    _exigir_archivo(ruta)
    contenido = ruta.read_bytes()
    try:
        paginas = len(PdfReader(io.BytesIO(contenido)).pages)
    except (PyPdfError, ValueError, OSError) as e:
        raise OcrError(f"{ruta.name} no es un PDF válido o está protegido: {e}") from e
    if paginas > MAX_PAGINAS_PDF:
        raise OcrError(f"{ruta.name} tiene {paginas} páginas: el máximo es {MAX_PAGINAS_PDF}")
    return _base64(contenido)


def leer_archivo_mistral(
    ruta, api_key, post=requests.post, url=URL_OPENROUTER, modelo=MODELO_ACOMPANANTE, timeout=120, esperar=time.sleep
) -> str:
    """Transcribe la foto o el PDF con Mistral OCR vía OpenRouter y lee las anotaciones de la respuesta."""
    if not api_key:
        raise OcrError("Falta OPENROUTER_API_KEY para usar Mistral OCR")
    pdf = _pdf_base64(pathlib.Path(ruta))
    payload = {
        "model": modelo,
        "max_tokens": 16,
        "temperature": 0,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Responde solo OK."},
            {"type": "file", "file": {"filename": "vineta.pdf", "file_data": "data:application/pdf;base64," + pdf}},
        ]}],
        "plugins": [{"id": "file-parser", "pdf": {"engine": "mistral-ocr"}}],
    }

    def llamar():
        return post_openrouter(
            post, url, payload, api_key, timeout, error=OcrError, sin_conexion="No se pudo conectar con OpenRouter",
            respondio="OpenRouter respondió {codigo}",
        )

    r = con_reintentos_503(llamar, esperar=esperar, reintentable=_saturado)
    try:
        texto = _texto_de_anotaciones(r.json())
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise OcrError("OpenRouter devolvió un formato inesperado de respuesta") from e
    if not texto:
        raise OcrError("No se pudo leer texto en el archivo: Mistral OCR no devolvió texto")
    return texto
