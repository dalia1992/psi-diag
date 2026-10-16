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
    assert set(datos) == {"id", "estado", "ms", "via", "pasos_ms"}
    assert datos["via"] == "texto" and datos["estado"] == "ok"
    assert all(isinstance(v, int) for v in datos["pasos_ms"].values())
    assert set(datos["pasos_ms"]) <= set(modulo_app.PASOS_MEDIDOS)


def test_pasos_ms_solo_acepta_nombres_fijos_y_numeros():
    sucio = {"guardrail": 1.2345, "busqueda_cie11": 2, "Laura Mendoza": 3.0, "extraer": "Laura", "reporte": True}
    assert modulo_app.pasos_ms(sucio) == {"guardrail": 1234, "busqueda_cie11": 2000}
    assert modulo_app.pasos_ms(None) == {}


def test_latencias_no_llegan_al_navegador(cliente):
    r = cliente.post("/api/caso", data={"texto": ENTRADA})
    assert "latencias" not in eventos_de(r)[-1]["resultado"]


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


def test_falla_inesperada_no_filtra_el_texto_ni_el_mensaje_de_la_excepcion(monkeypatch):
    registros = []

    class Captura(logging.Handler):
        def emit(self, record):
            registros.append(record.getMessage())

    secreto = "fallo con Laura Mendoza en Guadalajara"

    def ner_roto(texto):
        raise RuntimeError(secreto)

    async def agente_roto(sintomas):
        raise RuntimeError(secreto)

    for componentes, _ in (construir(ner=ner_roto), construir(busqueda_cie11=agente_roto)):
        monkeypatch.setattr(modulo_app, "componentes_de_prueba", componentes)
        modulo_app._visitas.clear()
        manejador = Captura()
        log = logging.getLogger("psico")
        log.addHandler(manejador)
        try:
            r = TestClient(modulo_app.app).post("/api/caso", data={"texto": ENTRADA})
        finally:
            log.removeHandler(manejador)
        eventos = eventos_de(r)
        assert eventos[-1]["tipo"] in ("resultado", "error")
        assert registros
        todo_log = "\n".join(registros)
        assert "Laura" not in todo_log and "Mendoza" not in todo_log and "fallo con" not in todo_log
        for e in eventos:
            visibles = []
            if e["tipo"] == "resultado":
                visibles = [e["resultado"]["razon_amigable"]]
            elif e["tipo"] == "error":
                visibles = [e["error"]["mensaje"], e["error"]["detalle"]]
            for v in visibles:
                assert "Laura" not in v and "Mendoza" not in v and "fallo con" not in v
        registros.clear()


def test_intentos_con_codigo_incorrecto_terminan_en_429(cliente, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "secreto")
    monkeypatch.setattr(modulo_app, "MAX_POR_MINUTO", 100)
    modulo_app._fallos.clear()
    codigos = [cliente.post("/api/caso", data={"texto": ENTRADA}, headers={"x-access-code": f"mal{i}"}).status_code for i in range(7)]
    assert codigos[:5] == [401] * 5 and codigos[5:] == [429, 429]


def test_codigo_correcto_antes_del_umbral_sigue_funcionando(cliente, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "secreto")
    modulo_app._fallos.clear()
    for i in range(4):
        assert cliente.post("/api/caso", data={"texto": ENTRADA}, headers={"x-access-code": "mal"}).status_code == 401
    assert cliente.post("/api/caso", data={"texto": ENTRADA}, headers={"x-access-code": "secreto"}).status_code == 200


def test_los_intentos_incorrectos_cuentan_para_el_limite_general(cliente, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "secreto")
    monkeypatch.setattr(modulo_app, "MAX_POR_MINUTO", 2)
    modulo_app._fallos.clear()
    codigos = [cliente.post("/api/caso", data={"texto": ENTRADA}, headers={"x-access-code": "mal"}).status_code for _ in range(3)]
    assert codigos == [401, 401, 429]


def test_respaldo_borra_el_archivo_si_el_generador_nunca_arranca(cliente, monkeypatch):
    rutas = []

    async def generador_muerto(entrada, ruta, id_solicitud, via, activo=None, fin=None):
        rutas.append(ruta)
        assert ruta.exists()
        return
        yield  # pragma: no cover  (generador vacío que no borra nada)

    monkeypatch.setattr(modulo_app, "transmitir", generador_muerto)
    r = cliente.post("/api/caso", data={"confirma_ocr": "true"}, files={"archivo": ("caso.png", png_valido(), "image/png")})
    assert r.status_code == 200 and len(rutas) == 1
    assert not rutas[0].exists()


async def test_formulario_se_cierra_en_toda_ruta(monkeypatch):
    from starlette.datastructures import FormData
    cerrados = []
    original = FormData.close

    async def cerrar(self):
        cerrados.append(1)
        await original(self)

    monkeypatch.setattr(FormData, "close", cerrar)
    componentes, _ = construir()
    monkeypatch.setattr(modulo_app, "componentes_de_prueba", componentes)
    c = TestClient(modulo_app.app)
    c.post("/api/caso", data={"texto": ENTRADA})
    c.post("/api/caso", data={"texto": "corto"})
    c.post("/api/caso", files={"archivo": ("caso.png", png_valido(), "image/png")})
    assert len(cerrados) == 3


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


# ----------------------------------------------------------------------------- lista blanca del resultado
def _resultado_interno(**sobre):
    base = {
        "estado_final": "ok", "razon": "Falló icd11_buscar_codigo_mms en https://cie11-mcp-server.example/sse", "razon_amigable": "Listo.",
        "texto_anon": "[PER_1] triste", "prob_clinico": 0.9, "sintomas": {"a": 1}, "candidatos": [{"codigo": "6A70"}],
        "alternativas": [], "traza_tools": [{"herramienta": "icd11_buscar_fundacion"}], "rondas_busqueda_cie11": 2,
        "reporte_md": "# md", "reporte": {"fecha": "2026-10-15"}, "advertencias": ["aviso"], "latencias": {"ocr": 1.0},
        "texto_ocr": "texto leído", "guias": [{"url": "https://guias.example/x"}],
    }
    base.update(sobre)
    return base


def _con_resultado(monkeypatch, resultado):
    async def falso(entrada, c):
        yield {"tipo": "resultado", "resultado": resultado}

    monkeypatch.setattr("poc_psico.grafo.ejecutar_eventos", falso)
    componentes, _ = construir()
    monkeypatch.setattr(modulo_app, "componentes_de_prueba", componentes)
    return TestClient(modulo_app.app).post("/api/caso", data={"texto": ENTRADA})


def test_resultado_al_cliente_solo_tiene_campos_permitidos(monkeypatch):
    r = _con_resultado(monkeypatch, _resultado_interno())
    for prohibido in ("icd11_", "cie11-mcp-server", "guias.example", "traza_tools", "latencias", "prob_clinico", "candidatos", "texto_anon", "reporte_md", "rondas_busqueda"):
        assert prohibido not in r.text
    assert set(eventos_de(r)[-1]["resultado"]) <= {"estado_final", "razon_amigable", "reporte", "advertencias", "texto_ocr"}


def test_resultado_ok_conserva_reporte_y_advertencias(monkeypatch):
    resultado = eventos_de(_con_resultado(monkeypatch, _resultado_interno()))[-1]["resultado"]
    assert resultado["reporte"] == {"fecha": "2026-10-15"} and resultado["advertencias"] == ["aviso"]


def test_resultado_de_error_conserva_razon_amigable(monkeypatch):
    resultado = eventos_de(_con_resultado(monkeypatch, _resultado_interno(estado_final="error", razon_amigable="No se pudo completar.", reporte=None)))[-1]["resultado"]
    assert resultado["estado_final"] == "error" and resultado["razon_amigable"] == "No se pudo completar."
    assert "razon" not in resultado
