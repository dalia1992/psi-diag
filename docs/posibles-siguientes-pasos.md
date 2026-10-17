# Posibles siguientes pasos

Ideas pendientes, sin compromiso de fecha. Cada una indica por qué y por dónde empezar.

## Monitoreo de entradas y salidas con Langfuse

**Por qué:** ver, por cada caso, qué entra y qué sale de cada modelo (extractor, agente CIE-11, redactor), con tokens, costo y latencia en una sola traza.

**Qué hacer:**
1. Crear un proyecto en Langfuse y sus claves (*Settings → API Keys*). Agregar `langfuse` a `requirements.txt`.
2. Definir `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` y `LANGFUSE_HOST` (también en Vercel).
3. Pasar `CallbackHandler` (`from langfuse.langchain import CallbackHandler`) en el `config={"callbacks": [handler]}` del `astream` de `ejecutar_eventos` (`backend/src/psi_diag/grafo.py`). LangGraph lo propaga al agente y a los modelos.
4. En Vercel, vaciar la cola antes de que termine la función: `get_client().flush()` al final de `transmitir` (`backend/src/servidor.py`).

**Ojo:**
- Solo se traza lo que pasa por LangChain. Las llamadas con `requests` (OCR de Mistral, guardrail JEV, búsqueda de guías y filtro de relevancia) quedan fuera; para verlas, envolverlas con `@observe()`.
- Son notas clínicas. Lo que entra a los modelos ya viene anonimizado, pero conviene usar Langfuse cloud solo con datos de prueba o auto-hospedarlo, y definir una función `mask` que borre cualquier dato sospechoso antes de enviarlo. Nunca debe entrar a una traza el texto del OCR sin anonimizar.
