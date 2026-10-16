"""Arma los `Componentes` del flujo con los mismos valores que el notebook del PoC (celdas 1.1, 2.1 y 3.1).

Todo se importa y se construye de forma perezosa y una sola vez por instancia de la función: así `/api/health`
responde al instante y el costo de cargar LangChain, el modelo NER y las tools MCP se paga en la primera consulta."""
import asyncio
import os
from pathlib import Path

UMBRAL_GUARDRAIL = 0.5
MAX_RONDAS = 5
BUSCAR_GUIAS = True
AGENT_MCP_URL_PREDETERMINADA = "https://cie11-mcp-server.orangerock-5a17ced7.eastus.azurecontainerapps.io/sse"
DIRECTORIO_NER = Path(__file__).resolve().parents[1] / "models" / "ner"

_componentes = None
_candado: asyncio.Lock | None = None


def cabeceras_openrouter() -> dict:
    """Cabeceras de atribución para OpenRouter. HTTP-Referer solo si se define APP_URL (opcional)."""
    cabeceras = {"X-Title": "MVP Psicodiagnostico"}
    url_app = os.getenv("APP_URL", "").strip()
    if url_app:
        cabeceras["HTTP-Referer"] = url_app
    return cabeceras


def crear_llm(clave: str):
    """Modelo de chat vía OpenRouter, con la preferencia de privacidad (`provider.data_collection = deny`)."""
    from langchain_openai import ChatOpenAI

    from psi_diag.peticiones import PRIVACIDAD_OPENROUTER

    return ChatOpenAI(
        model=os.getenv("MODEL_ID", "anthropic/claude-haiku-5.5"),
        api_key=clave,
        base_url="https://openrouter.ai/api/v1",
        temperature=0,
        max_tokens=4096,
        timeout=120,
        max_retries=3,
        default_headers=cabeceras_openrouter(),
        extra_body={"provider": dict(PRIVACIDAD_OPENROUTER)},
    )


def _clave() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip()


async def _construir():
    from psi_diag.agente import PROMPT_AGENTE, TOOLS_BASE, cargar_tools, construir_agente, correr_agente
    from psi_diag.grafo import Componentes
    from psi_diag.guardrail import consultar_decisions
    from psi_diag.guias import buscar_guias, crear_decisor_fuentes, crear_decisor_jev
    from psi_diag.ner_onnx import con_pasada_auxiliar, crear_ner_onnx
    from psi_diag.nodos import crear_extractor, crear_redactor
    from psi_diag.ocr import leer_archivo_mistral

    clave = _clave()
    llm = crear_llm(clave)
    url_mcp = os.getenv("AGENT_MCP_URL", AGENT_MCP_URL_PREDETERMINADA)
    tools = await cargar_tools(url_mcp, TOOLS_BASE)
    agente = construir_agente(llm, tools, PROMPT_AGENTE, MAX_RONDAS)
    ner = await asyncio.to_thread(lambda: con_pasada_auxiliar(crear_ner_onnx(DIRECTORIO_NER)))

    async def _agente(sintomas):
        return await correr_agente(agente, sintomas, MAX_RONDAS)

    def _ocr(ruta):  # Mistral OCR vía OpenRouter: el archivo sale a OpenRouter y Mistral antes de anonimizar
        return leer_archivo_mistral(ruta, clave)

    def _guardrail(texto):
        return consultar_decisions(texto, clave)

    decidir_fuentes = crear_decisor_jev(clave, respaldo=crear_decisor_fuentes(llm))

    def _guias(candidatos, sintomas):
        return buscar_guias(candidatos, sintomas, clave, decidir_fuentes)

    return Componentes(
        ner=ner,
        guardrail=_guardrail,
        extraer=crear_extractor(llm),
        busqueda_cie11=_agente,
        redactar=crear_redactor(llm),
        umbral=UMBRAL_GUARDRAIL,
        ocr=_ocr,
        guias=_guias if BUSCAR_GUIAS else None,
    )


async def obtener_componentes():
    """Devuelve los componentes de esta instancia; los arma en la primera llamada."""
    global _componentes, _candado
    if _componentes is not None:
        return _componentes
    if _candado is None:
        _candado = asyncio.Lock()
    async with _candado:
        if _componentes is None:
            _componentes = await _construir()
    return _componentes
