import os

from fastapi import FastAPI

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/health")
def salud() -> dict:
    """La pantalla consulta aquí si hay clave configurada y si pide código. No revela secretos."""
    return {
        "ok": True,
        "configurado": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
        "requiere_codigo": bool(os.getenv("ACCESS_CODE", "").strip()),
    }
