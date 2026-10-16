from fastapi.testclient import TestClient

from app import app


def test_health_sin_clave(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ACCESS_CODE", raising=False)
    cliente = TestClient(app)

    respuesta = cliente.get("/api/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "configurado": False, "requiere_codigo": False}
