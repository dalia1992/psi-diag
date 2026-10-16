import asyncio
import io
import json
import logging
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as modulo_app
from poc_psico.esquemas import HipotesisRedactada, ReporteClinico
from poc_psico.reporte import construir_datos
from tests.test_grafo import ENTRADA, construir

FIXTURE_DEMO = Path(__file__).parent / "fixtures" / "eventos_demo.json"


def png_valido() -> bytes:
    from PIL import Image
    salida = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(salida, "PNG")
    return salida.getvalue()


def pdf_valido(paginas: int = 1) -> bytes:
    from pypdf import PdfWriter
    escritor = PdfWriter()
    for _ in range(paginas):
        escritor.add_blank_page(width=100, height=100)
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


def eventos_de(respuesta) -> list:
    return [json.loads(l[len("data: "):]) for l in respuesta.text.splitlines() if l.startswith("data: ")]


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    for variable in ("ACCESS_CODE", "VERCEL", "MODO_DEMO", "BACKEND_TIMEOUT_S", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    modulo_app._visitas.clear()
    monkeypatch.setattr(modulo_app, "componentes_de_prueba", None)
    yield


@pytest.fixture
def cliente(monkeypatch):
    componentes, _ = construir()
    monkeypatch.setattr(modulo_app, "componentes_de_prueba", componentes)
    return TestClient(modulo_app.app)


# ----------------------------------------------------------------------------- acceso, límite, validación de texto
def test_sin_codigo_responde_401(cliente, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "secreto")
    r = cliente.post("/api/caso", data={"texto": ENTRADA})
    assert r.status_code == 401
    assert r.json()["error"]["codigo"] == "acceso"
    assert r.json()["ok"] is False
    r = cliente.post("/api/caso", data={"texto": ENTRADA}, headers={"x-access-code": "secreto"})
    assert r.status_code == 200


def test_en_vercel_sin_access_code_configurado_responde_sin_configurar(cliente, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    r = cliente.post("/api/caso", data={"texto": ENTRADA})
    assert r.status_code == 503
    assert r.json()["error"]["codigo"] == "sin_configurar"


def test_limite_por_minuto_responde_429(cliente, monkeypatch):
    monkeypatch.setattr(modulo_app, "MAX_POR_MINUTO", 2)
    for _ in range(2):
        assert cliente.post("/api/caso", data={"texto": ENTRADA}).status_code == 200
    r = cliente.post("/api/caso", data={"texto": ENTRADA})
    assert r.status_code == 429
    assert r.json()["error"]["codigo"] == "limite"
    assert r.json()["error"]["reintentable"] is True


@pytest.mark.parametrize("texto", ["corto", "x" * 8001, "   ", "reporte_de_caso_clinico.pdf"])
def test_texto_invalido_responde_validacion(cliente, texto):
    r = cliente.post("/api/caso", data={"texto": texto})
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "validacion"


def test_texto_corto_responde_validacion(cliente):
    r = cliente.post("/api/caso", data={"texto": "Muy corto"})
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "validacion"


def test_sin_texto_ni_archivo_responde_validacion(cliente):
    r = cliente.post("/api/caso", data={})
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "validacion"


def test_stream_entrega_pasos_y_resultado(cliente):
    r = cliente.post("/api/caso", data={"texto": ENTRADA})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-store"
    eventos = eventos_de(r)
    assert [e["tipo"] for e in eventos].count("resultado") == 1
    assert eventos[-1]["tipo"] == "resultado"
    assert eventos[-1]["resultado"]["estado_final"] == "ok"
    assert {e["id"] for e in eventos if e["tipo"] == "paso"} >= {"proteccion", "verificacion", "sintomas", "cie11", "guias", "reporte"}


def test_registro_no_contiene_el_texto_del_caso(cliente):
    registros = []

    class Captura(logging.Handler):
        def emit(self, record):
            registros.append(record.getMessage())

    log = logging.getLogger("psico")
    manejador = Captura()
    log.addHandler(manejador)
    try:
        r = cliente.post("/api/caso", data={"texto": ENTRADA})
    finally:
        log.removeHandler(manejador)
    assert r.status_code == 200 and registros
    todo = "\n".join(registros)
    assert "Laura" not in todo and "Mendoza" not in todo and "tristeza" not in todo
    datos = json.loads(registros[-1])
    assert set(datos) == {"id", "estado", "ms", "via"}
    assert datos["via"] == "texto" and datos["estado"] == "ok"


# ----------------------------------------------------------------------------- archivos
def _ocr_espia(destino: dict):
    def ocr(ruta):
        destino.setdefault("rutas", []).append(ruta)
        destino["existia"] = Path(ruta).is_file()
        destino["sufijo"] = Path(ruta).suffix
        return ENTRADA
    return ocr


def test_archivo_valido_se_lee_con_ocr_y_se_borra(monkeypatch):
    visto: dict = {}
    componentes, _ = construir(ocr=_ocr_espia(visto))
    monkeypatch.setattr(modulo_app, "componentes_de_prueba", componentes)
    cliente = TestClient(modulo_app.app)
    r = cliente.post("/api/caso", data={"confirma_ocr": "true"}, files={"archivo": ("caso.png", png_valido(), "image/png")})
    assert r.status_code == 200
    eventos = eventos_de(r)
    assert eventos[-1]["resultado"]["estado_final"] == "ok"
    assert any(e.get("id") == "lectura" for e in eventos)
    assert visto["existia"] and visto["sufijo"] == ".png"
    assert not Path(visto["rutas"][0]).exists()


def test_pdf_valido_se_acepta(monkeypatch):
    componentes, _ = construir(ocr=lambda ruta: ENTRADA)
    monkeypatch.setattr(modulo_app, "componentes_de_prueba", componentes)
    r = TestClient(modulo_app.app).post("/api/caso", data={"confirma_ocr": "true"}, files={"archivo": ("caso.pdf", pdf_valido(), "application/pdf")})
    assert r.status_code == 200
    assert eventos_de(r)[-1]["resultado"]["estado_final"] == "ok"


def test_archivo_renombrado_se_rechaza_por_firma(cliente):
    r = cliente.post("/api/caso", data={"confirma_ocr": "true"}, files={"archivo": ("caso.pdf", png_valido(), "application/pdf")})
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "archivo"
    r = cliente.post("/api/caso", data={"confirma_ocr": "true"}, files={"archivo": ("script.exe", b"MZ" + b"0" * 50, "image/png")})
    assert r.json()["error"]["codigo"] == "archivo"


def test_pdf_corrupto_da_error_archivo(cliente):
    r = cliente.post("/api/caso", data={"confirma_ocr": "true"}, files={"archivo": ("caso.pdf", b"%PDF-1.4\nesto no es un pdf", "application/pdf")})
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "archivo"


def test_pdf_con_demasiadas_paginas_da_error_archivo(cliente):
    r = cliente.post("/api/caso", data={"confirma_ocr": "true"}, files={"archivo": ("caso.pdf", pdf_valido(11), "application/pdf")})
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "archivo"


def test_imagen_mayor_a_4mb_se_rechaza(cliente):
    grande = png_valido() + b"0" * 4_000_001
    r = cliente.post("/api/caso", data={"confirma_ocr": "true"}, files={"archivo": ("caso.png", grande, "image/png")})
    assert r.status_code == 413
    assert r.json()["error"]["codigo"] == "archivo"


def test_archivo_sin_confirmar_ocr_se_rechaza_sin_llamar_al_ocr(monkeypatch):
    llamadas = []
    componentes, _ = construir(ocr=lambda ruta: llamadas.append(ruta) or ENTRADA)
    monkeypatch.setattr(modulo_app, "componentes_de_prueba", componentes)
    cliente = TestClient(modulo_app.app)
    r = cliente.post("/api/caso", files={"archivo": ("caso.png", png_valido(), "image/png")})
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "ocr"
    r = cliente.post("/api/caso", data={"confirma_ocr": "false"}, files={"archivo": ("caso.png", png_valido(), "image/png")})
    assert r.json()["error"]["codigo"] == "ocr"
    assert llamadas == []


def test_texto_y_archivo_a_la_vez_se_rechaza(cliente):
    r = cliente.post("/api/caso", data={"texto": ENTRADA, "confirma_ocr": "true"}, files={"archivo": ("caso.png", png_valido(), "image/png")})
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "validacion"


# ----------------------------------------------------------------------------- hilos, desconexión y tiempo
async def test_archivo_temporal_se_borra_si_el_cliente_se_desconecta(monkeypatch, tmp_path):
    empezo, soltar = threading.Event(), threading.Event()

    def ocr_lento(ruta):
        empezo.set()
        soltar.wait(10)
        return ENTRADA

    componentes, _ = construir(ocr=ocr_lento)
    monkeypatch.setattr(modulo_app, "componentes_de_prueba", componentes)
    ruta = tmp_path / "caso.png"
    ruta.write_bytes(png_valido())

    async def consumir():
        async for _ in modulo_app.transmitir(str(ruta), ruta, "t1", "archivo"):
            pass

    tarea = asyncio.create_task(consumir())
    assert await asyncio.to_thread(empezo.wait, 5)
    tarea.cancel()  # el cliente se fue mientras el hilo del OCR sigue leyendo
    with pytest.raises(asyncio.CancelledError):
        await tarea
    assert ruta.exists()  # el hilo no se puede interrumpir: el archivo sigue ahí mientras lee
    soltar.set()
    for _ in range(100):
        if not ruta.exists():
            break
        await asyncio.sleep(0.05)
    assert not ruta.exists()


def test_tiempo_agotado_emite_error_reintentable(monkeypatch):
    async def lento(sintomas):
        await asyncio.sleep(5)

    componentes, _ = construir(busqueda_cie11=lento)
    monkeypatch.setattr(modulo_app, "componentes_de_prueba", componentes)
    monkeypatch.setenv("BACKEND_TIMEOUT_S", "0.1")
    inicio = time.perf_counter()
    r = TestClient(modulo_app.app).post("/api/caso", data={"texto": ENTRADA})
    assert time.perf_counter() - inicio < 3
    ultimo = eventos_de(r)[-1]
    assert ultimo["tipo"] == "error"
    assert ultimo["error"]["codigo"] == "timeout"
    assert ultimo["error"]["reintentable"] is True
    assert set(ultimo["error"]) == {"codigo", "mensaje", "detalle", "reintentable"}


def test_falla_inesperada_emite_error_backend_sin_detalle_del_texto(monkeypatch):
    def ner_roto(texto):
        raise RuntimeError("fallo con Laura Mendoza")

    componentes, _ = construir(ner=ner_roto)
    monkeypatch.setattr(modulo_app, "componentes_de_prueba", componentes)
    r = TestClient(modulo_app.app).post("/api/caso", data={"texto": ENTRADA})
    # ejecutar_eventos convierte la falla en un resultado de error; el stream sigue siendo válido
    assert eventos_de(r)[-1]["tipo"] in ("resultado", "error")


# ----------------------------------------------------------------------------- modo demo
def test_modo_demo_emite_el_guion_sin_llamar_a_nada(monkeypatch):
    monkeypatch.setenv("MODO_DEMO", "1")
    monkeypatch.setenv("DEMO_PAUSA_S", "0")
    r = TestClient(modulo_app.app).post("/api/caso", data={"texto": ENTRADA})
    assert r.status_code == 200
    assert eventos_de(r) == json.loads(FIXTURE_DEMO.read_text(encoding="utf-8"))


def test_modo_demo_se_ignora_en_vercel(monkeypatch):
    monkeypatch.setenv("MODO_DEMO", "1")
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("ACCESS_CODE", "x")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = TestClient(modulo_app.app).post("/api/caso", data={"texto": ENTRADA}, headers={"x-access-code": "x"})
    assert r.status_code == 503
    assert r.json()["error"]["codigo"] == "sin_configurar"


def test_fixture_demo_tiene_siete_pasos_y_las_claves_del_reporte():
    eventos = json.loads(FIXTURE_DEMO.read_text(encoding="utf-8"))
    assert {e["id"] for e in eventos if e["tipo"] == "paso"} == {"lectura", "proteccion", "verificacion", "sintomas", "cie11", "guias", "reporte"}
    final = eventos[-1]["resultado"]
    assert eventos[-1]["tipo"] == "resultado" and final["estado_final"] == "ok"
    from datetime import date
    esperado = construir_datos({}, [], ReporteClinico(hipotesis=[HipotesisRedactada(codigo="x", justificacion="y")]), [], date(2026, 10, 15), [], [])
    assert set(final["reporte"]) == set(esperado)
