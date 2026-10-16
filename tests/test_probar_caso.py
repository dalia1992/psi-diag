"""Pruebas de scripts/probar_caso.py con un servidor SSE local falso (sin red externa)."""
import http.server
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import probar_caso  # noqa: E402

PASO = {"tipo": "paso", "id": "lectura", "titulo": "Lectura", "estado": "listo", "detalle": {"resumen": "Texto leído", "lineas": []}}


def _resultado(estado, hipotesis=1):
    return {"tipo": "resultado", "resultado": {
        "estado_final": estado, "razon_amigable": "motivo" if estado != "ok" else "", "advertencias": ["a"],
        "reporte": {"hipotesis": [{"codigo": f"6A7{i}", "titulo": "t"} for i in range(hipotesis)]} if estado == "ok" else None}}


@pytest.fixture
def servidor():
    cuerpo = {"eventos": [], "recibido": {}}

    class Manejador(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            largo = int(self.headers.get("content-length", 0))
            cuerpo["recibido"] = {"codigo": self.headers.get("x-access-code"), "largo": len(self.rfile.read(largo))}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b": ping\n\n")
            for e in cuerpo["eventos"]:
                self.wfile.write(f"data: {json.dumps(e)}\n\n".encode())

        def log_message(self, *a):
            pass

    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield cuerpo, f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_parsear_sse_ignora_comentarios_y_basura():
    eventos, resto = probar_caso.parsear_sse(': ping\n\ndata: {"a": 1}\n\ndata: no-json\n\ndata: {"b"')
    assert eventos == [{"a": 1}]
    assert resto == 'data: {"b"'


def test_ok_sale_con_cero_e_imprime_resumen(servidor, capsys, tmp_path):
    datos, url = servidor
    datos["eventos"] = [PASO, _resultado("ok", 2)]
    env = tmp_path / "env"
    env.write_text("ACCESS_CODE=secreto-123\n")
    assert probar_caso.main([url, "--texto", "x" * 30, "--env-file", str(env)]) == 0
    salida = capsys.readouterr().out
    assert "lectura" in salida and "estado_final: ok" in salida and "6A70" in salida
    assert "secreto-123" not in salida
    assert datos["recibido"]["codigo"] == "secreto-123"


def test_no_ok_sale_distinto_de_cero(servidor, tmp_path):
    datos, url = servidor
    datos["eventos"] = [_resultado("fuera_de_alcance")]
    assert probar_caso.main([url, "--texto", "x" * 30, "--env-file", str(tmp_path / "no")]) != 0
    assert probar_caso.main([url, "--texto", "x" * 30, "--env-file", str(tmp_path / "no"), "--esperar", "fuera_de_alcance"]) == 0


def test_sin_resultado_o_con_error_falla(servidor, tmp_path):
    datos, url = servidor
    datos["eventos"] = [PASO]
    assert probar_caso.main([url, "--texto", "x" * 30, "--env-file", str(tmp_path / "no")]) != 0
    datos["eventos"] = [{"tipo": "error", "error": {"codigo": "timeout", "mensaje": "tarde"}}]
    assert probar_caso.main([url, "--texto", "x" * 30, "--env-file", str(tmp_path / "no")]) != 0


def test_archivo_se_envia_con_confirmacion(servidor, tmp_path):
    datos, url = servidor
    datos["eventos"] = [_resultado("ok")]
    foto = tmp_path / "f.jpg"
    foto.write_bytes(b"\xff\xd8\xff" + b"0" * 50)
    assert probar_caso.main([url, "--archivo", str(foto), "--confirma-ocr", "--env-file", str(tmp_path / "no")]) == 0
    assert datos["recibido"]["largo"] > 50
