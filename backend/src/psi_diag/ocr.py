"""OCR de notas manuscritas (foto o PDF) con Mistral OCR vía OpenRouter (el archivo sale a esos servicios sin anonimizar)."""
import base64
import io
import pathlib
import re
import time
import warnings
from contextlib import contextmanager

import requests
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .errores import FlujoDetenido
from .peticiones import PRIVACIDAD_OPENROUTER, URL_OPENROUTER, post_openrouter
from .reintentos import con_reintentos_503

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png"}
EXTENSIONES = EXTENSIONES_IMAGEN | {".pdf"}
# El plugin file-parser solo parsea PDF (un JPEG directo responde 200 sin texto). El modelo de chat solo acompaña
# la petición: su respuesta se ignora y max_tokens bajo evita esperar su generación (spike 2026-10-14).
MODELO_ACOMPANANTE = "mistralai/mistral-nemo"
LADO_MAXIMO_MISTRAL = 2000
MAX_PAGINAS_PDF = 10
# Tope de tamaño de una imagen (se lee del encabezado, sin decodificarla): una foto de 12000×12000 px cabe en pocos KB
# comprimida y ocuparía casi 1 GB al decodificarla, en una instancia que comparte memoria con otras solicitudes.
MAX_PIXELES = 40_000_000
MAX_LADO = 8000
Image.MAX_IMAGE_PIXELS = MAX_PIXELES   # Pillow avisa por encima de este valor y falla por encima del doble
MENSAJE_IMAGEN_GRANDE = "La imagen es demasiado grande (máximo 40 megapíxeles y 8000 píxeles por lado). Reduce su tamaño e inténtalo de nuevo."


class OcrError(FlujoDetenido):
    """No se pudo leer el archivo; el flujo no continúa con texto inventado o incompleto."""


def dimensiones_aceptables(ancho: int, alto: int) -> bool:
    return ancho * alto <= MAX_PIXELES and max(ancho, alto) <= MAX_LADO


@contextmanager
def bomba_como_error():
    """Dentro del bloque, el aviso de «posible bomba de descompresión» de Pillow es una excepción (no solo un aviso)."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        yield


ERRORES_BOMBA = (Image.DecompressionBombError, Image.DecompressionBombWarning)


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
    return _abrir(ruta, ruta.name, lado)


def _abrir(origen, nombre: str, lado: int) -> Image.Image:
    """Abre la imagen (ruta o flujo de bytes), la pasa a RGB y la reduce a `lado` píxeles como máximo."""
    try:
        with bomba_como_error(), Image.open(origen) as original:
            if not dimensiones_aceptables(*original.size):   # solo el encabezado: nada se ha decodificado todavía
                raise OcrError(f"{nombre}: {MENSAJE_IMAGEN_GRANDE}")
            if original.format == "JPEG":
                original.draft("RGB", (lado, lado))   # el decodificador JPEG reduce por 2, 4 u 8 mientras lee
            imagen = original.convert("RGB")  # descarta la transparencia de los PNG
    except ERRORES_BOMBA as e:
        raise OcrError(f"{nombre}: {MENSAJE_IMAGEN_GRANDE}") from e
    except (UnidentifiedImageError, OSError) as e:
        raise OcrError(f"No se pudo abrir {nombre} como imagen: {e}") from e
    imagen.thumbnail((lado, lado))
    return imagen


def imagenes_a_pdf(imagenes: list) -> bytes:
    """Une varias fotos, en el orden dado, en un solo PDF con una página por foto. `imagenes` es [(nombre, bytes)]; cada foto
    se reduce a LADO_MAXIMO_MISTRAL como al leer una sola, así que diez fotos no ocupan diez veces su tamaño en memoria."""
    if not imagenes:
        raise OcrError("No hay imágenes que unir")
    paginas = [_abrir(io.BytesIO(datos), nombre, LADO_MAXIMO_MISTRAL) for nombre, datos in imagenes]
    salida = io.BytesIO()
    paginas[0].save(salida, "PDF", save_all=True, append_images=paginas[1:], resolution=150)
    return salida.getvalue()


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
        "provider": dict(PRIVACIDAD_OPENROUTER),
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
