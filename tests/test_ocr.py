import base64
import io

import pytest
import requests
from PIL import Image

from poc_psico.errores import FlujoDetenido
from poc_psico.ocr import MAX_PAGINAS_PDF, OcrError, es_archivo, leer_archivo_mistral
from tests.helpers import RespuestaFalsa


@pytest.fixture
def foto(tmp_path):
    ruta = tmp_path / "vineta.jpg"
    Image.new("RGB", (3000, 2000), "white").save(ruta)
    return ruta


def test_es_archivo_reconoce_rutas_de_foto_o_pdf_y_no_texto_clinico():
    assert es_archivo("/tmp/vineta.JPG")
    assert es_archivo("vineta.png")
    assert es_archivo("/tmp/nota.PDF")
    assert not es_archivo("Lucía, 28 años. Refiere ansiedad.")
    assert not es_archivo("Refiere ansiedad.\nFoto: nota.jpg")
    assert not es_archivo("")


def test_ocr_error_es_un_flujo_detenido():
    assert issubclass(OcrError, FlujoDetenido)


# Mistral OCR vía OpenRouter (plugin file-parser; solo parsea PDF, así que la foto se convierte)


def anotada(texto):
    contenido = [{"type": "text", "text": f'<file name="vineta.pdf">\n{texto}\n</file>'}]
    anotacion = {"type": "file", "file": {"name": "vineta.pdf", "content": contenido}}
    return RespuestaFalsa(200, {"choices": [{"message": {"content": "OK", "annotations": [anotacion]}}]})


def test_mistral_envia_la_foto_como_pdf_con_el_plugin_y_devuelve_el_texto_sin_la_etiqueta_file(foto):
    visto = {}

    def post(url, json, headers, timeout):
        visto.update(url=url, json=json, headers=headers)
        return anotada("Lucía 28 años")

    assert leer_archivo_mistral(foto, "clave-falsa", post=post) == "Lucía 28 años"
    assert visto["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert visto["headers"]["Authorization"] == "Bearer clave-falsa"
    assert visto["json"]["plugins"] == [{"id": "file-parser", "pdf": {"engine": "mistral-ocr"}}]
    assert visto["json"]["max_tokens"] <= 16
    parte = visto["json"]["messages"][0]["content"][1]["file"]
    assert parte["file_data"].startswith("data:application/pdf;base64,")
    assert base64.b64decode(parte["file_data"].split(",", 1)[1]).startswith(b"%PDF")


def test_mistral_sin_clave_detiene_el_flujo_sin_llamar(foto):
    def post(*a, **k):
        raise AssertionError("no debe llamar")

    with pytest.raises(OcrError, match="OPENROUTER_API_KEY"):
        leer_archivo_mistral(foto, "", post=post)


def test_mistral_reintenta_cuando_el_motor_de_parseo_esta_saturado(foto):
    respuestas = [RespuestaFalsa(400, texto="Failed to parse the file: The document parsing engine is currently rate limited."),
                  anotada("hola")]
    esperas = []
    assert leer_archivo_mistral(foto, "k", post=lambda *a, **k: respuestas.pop(0), esperar=esperas.append) == "hola"
    assert esperas == [1]


def test_mistral_si_la_saturacion_persiste_se_detiene_con_el_motivo(foto):
    saturado = RespuestaFalsa(400, texto="engine is currently rate limited")
    esperas = []
    with pytest.raises(OcrError, match="rate limited"):
        leer_archivo_mistral(foto, "k", post=lambda *a, **k: saturado, esperar=esperas.append)
    assert esperas == [1, 2, 4]


@pytest.mark.parametrize("status", [401, 402, 500])
def test_mistral_otros_errores_http_no_se_reintentan_y_dicen_el_codigo(foto, status):
    llamadas = []

    def post(*a, **k):
        llamadas.append(1)
        return RespuestaFalsa(status, texto="error")

    with pytest.raises(OcrError, match=str(status)):
        leer_archivo_mistral(foto, "k", post=post, esperar=lambda s: None)
    assert len(llamadas) == 1


def test_mistral_sin_texto_en_las_anotaciones_detiene_el_flujo_y_no_inventa(foto):
    sin_anotaciones = RespuestaFalsa(200, {"choices": [{"message": {"content": "OK"}}]})
    with pytest.raises(OcrError, match="No se pudo leer texto"):
        leer_archivo_mistral(foto, "k", post=lambda *a, **k: sin_anotaciones)


def test_mistral_error_de_red_detiene_el_flujo(foto):
    def post(*a, **k):
        raise requests.ConnectionError("sin red")

    with pytest.raises(OcrError, match="OpenRouter"):
        leer_archivo_mistral(foto, "k", post=post)


def test_mistral_con_archivo_que_no_es_archivo_detiene_el_flujo(tmp_path):
    ruta = tmp_path / "roto.jpg"
    ruta.write_text("no es imagen")
    with pytest.raises(OcrError, match="imagen"):
        leer_archivo_mistral(ruta, "k", post=lambda *a, **k: anotada("x"))


def test_mistral_con_archivo_inexistente_detiene_el_flujo(tmp_path):
    with pytest.raises(OcrError, match="no existe"):
        leer_archivo_mistral(tmp_path / "nada.jpg", "k", post=lambda *a, **k: anotada("x"))


def test_mistral_acepta_png_con_transparencia(tmp_path):
    ruta = tmp_path / "nota.png"
    Image.new("RGBA", (200, 100), (255, 255, 255, 0)).save(ruta)
    assert leer_archivo_mistral(ruta, "k", post=lambda *a, **k: anotada("hola")) == "hola"


@pytest.fixture
def pdf(tmp_path):
    ruta = tmp_path / "vineta.pdf"
    Image.new("RGB", (300, 200), "white").save(ruta, "PDF")
    return ruta


def test_mistral_envia_un_pdf_tal_cual_sin_convertirlo(pdf):
    visto = {}

    def post(url, json, headers, timeout):
        visto.update(json=json)
        return anotada("Lucía 28 años")

    assert leer_archivo_mistral(pdf, "k", post=post) == "Lucía 28 años"
    parte = visto["json"]["messages"][0]["content"][1]["file"]
    assert base64.b64decode(parte["file_data"].split(",", 1)[1]) == pdf.read_bytes()


def test_mistral_con_pdf_inexistente_o_roto_detiene_el_flujo(tmp_path):
    with pytest.raises(OcrError, match="no existe"):
        leer_archivo_mistral(tmp_path / "nada.pdf", "k", post=lambda *a, **k: anotada("x"))
    roto = tmp_path / "roto.pdf"
    roto.write_text("no es un pdf")
    with pytest.raises(OcrError, match="PDF válido"):
        leer_archivo_mistral(roto, "k", post=lambda *a, **k: anotada("x"))


def _pdf_de(paginas, tmp_path):
    ruta = tmp_path / f"{paginas}p.pdf"
    hoja = Image.new("RGB", (100, 100), "white")
    hoja.save(ruta, "PDF", save_all=True, append_images=[hoja] * (paginas - 1))
    return ruta


def test_mistral_acepta_un_pdf_con_el_maximo_de_paginas(tmp_path):
    ruta = _pdf_de(MAX_PAGINAS_PDF, tmp_path)
    assert leer_archivo_mistral(ruta, "k", post=lambda *a, **k: anotada("hola")) == "hola"


def test_mistral_rechaza_un_pdf_con_mas_paginas_que_el_maximo_sin_llamar(tmp_path):
    def post(*a, **k):
        raise AssertionError("no debe llamar")

    with pytest.raises(OcrError, match=f"el máximo es {MAX_PAGINAS_PDF}"):
        leer_archivo_mistral(_pdf_de(MAX_PAGINAS_PDF + 1, tmp_path), "k", post=post)
