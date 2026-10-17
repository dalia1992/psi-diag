# MVP psicodiagnóstico

Herramienta de apoyo al psicodiagnóstico (fase 1). Una persona describe un caso (texto, foto o PDF); la app lo anonimiza,
busca criterios en la CIE-11 y en guías clínicas, y produce un reporte con hipótesis diagnósticas que se puede descargar
en Word o PDF. Es un apoyo para la o el profesional: no sustituye su criterio. Backend FastAPI (`backend/src/servidor.py`) que reutiliza el
flujo del PoC (paquete `backend/src/psi_diag/`), pantalla web estática en `public/`, pensada para desplegarse en Vercel.

## Correr en local

1. Crea un entorno virtual **fuera de Google Drive** (si usas otra ruta, cámbiala en los comandos siguientes) e instala las dependencias:

```bash
uv venv ~/.venvs/mvp_psico --python 3.12
```

```bash
uv pip install --python ~/.venvs/mvp_psico/bin/python -r backend/requirements-dev.txt
```

2. Crea un archivo de entorno en `~/.config/mvp_psico/env` (fuera del repositorio) con `OPENROUTER_API_KEY` y `ACCESS_CODE`
   (usa un código distinto al de producción). Nunca subas claves a git; `.env.example` es solo una plantilla.
3. Arranca:

```bash
~/.venvs/mvp_psico/bin/uvicorn app:app --port 8000 --env-file ~/.config/mvp_psico/env
```

(desde la raíz del repositorio; `app.py` de la raíz es solo la entrada y carga `backend/src/servidor.py`)

y abre http://localhost:8000 (`uvicorn` está en el entorno virtual: si no lo tienes activado, usa la ruta completa de arriba). Sin servicios de pago, para ver solo la interfaz con un caso de demostración: arranca con `MODO_DEMO=1`
(solo funciona fuera de Vercel).

Variables de entorno: `OPENROUTER_API_KEY` (obligatoria), `ACCESS_CODE` (obligatoria en Vercel), y opcionales `MODEL_ID`,
`MAX_POR_MINUTO`, `BACKEND_TIMEOUT_S`, `AGENT_MCP_URL`. Detalle en [DESPLIEGUE.md](DESPLIEGUE.md).

## Pruebas

```bash
cd backend && ~/.venvs/mvp_psico/bin/python -m pytest -q
```

```bash
node --test public/sse.test.mjs
```

Prueba de punta a punta contra un servidor en marcha: `~/.venvs/mvp_psico/bin/python backend/scripts/probar_caso.py URL --texto "..." --env-file ARCHIVO`.

## Estructura

```
app.py                 entrada en la raíz (Vercel y `uvicorn app:app`); carga backend/src/servidor.py
backend/
  src/
    servidor.py        API (/api/health, /api/calentar, /api/proteger y /api/caso por SSE, /api/exportar/{docx|pdf}); en local también sirve public/
    componentes.py, errores_api.py   armado de componentes y errores de la API
    psi_diag/          flujo de análisis (OCR, anonimización, extracción, CIE-11, guías, reporte)
    exportar/          generación de Word y PDF
  models/ner/          modelo ONNX de anonimización (partido en dos)
  assets/fonts/        fuentes del PDF
  tests/  scripts/     pruebas; utilidades (exportar el modelo, preparar fuentes, probar_caso.py)
  requirements-dev.txt, pytest.ini
public/                pantalla web (HTML, JS, CSS, fuentes): la raíz web, que Vercel sirve desde su CDN
docs/                  diseño y plan
vercel.json, .vercelignore, .python-version, requirements.txt   configuración de despliegue
```

## Límites conocidos

- Nombres en minúsculas o poco comunes dentro de texto libre pueden escapar de la anonimización; la cifra 23/23 se midió sobre un conjunto pequeño de ajuste, sin conjunto de prueba aparte, y no es una tasa general (detalle abajo).
- La fuente Nunito no tiene la Ψ ni emoji; se usan imágenes o alternativas.
- Al subir foto o PDF, el archivo **original** se envía antes de anonimizar a OpenRouter y Mistral (OCR y modelo auxiliar; OpenRouter puede ejecutar ese modelo auxiliar con otro proveedor de alojamiento); la pantalla lo avisa y pide confirmación. Las llamadas de chat, OCR y búsqueda de guías piden a OpenRouter `provider.data_collection = deny` (no la Decisions API); es una petición, no una garantía.
- Vercel Hobby es solo para uso personal no comercial; con casos reales de otras colegas hace falta el plan Pro.
- La primera solicitud tras un rato sin uso puede ser lenta; un caso completo tarda de 1 a 3 minutos (corte a los 280 s).

## Despliegue

Guía paso a paso en [DESPLIEGUE.md](DESPLIEGUE.md).

## NER de anonimización (ONNX)

`backend/src/psi_diag/ner_onnx.py` ejecuta `mrm8488/bert-spanish-cased-finetuned-ner` (int8, ~110 MB) con onnxruntime, sin torch.
El modelo se versiona partido en `backend/models/ner/model_int8.onnx.part1`/`.part2` (GitHub rechaza archivos > 100 MB) y se
reensambla en memoria; se regenera con `backend/scripts/exportar_ner_onnx.py`. Los textos largos se procesan por trozos de 1000 caracteres.

**Límite conocido:** el modelo distingue mayúsculas. `con_pasada_auxiliar` repite el NER con las palabras en formato "Título"
(acepta solo PER/LOC) y cubre nombres en MAYÚSCULAS o minúsculas de los casos de ajuste (23/23), pero un nombre en minúsculas
sin contexto claro (p. ej. un apodo solo) aún puede escapar. Por eso el texto anonimizado debe seguir revisándose antes de enviarse a un LLM externo (la pantalla lo muestra en «Protección de datos personales → Ver qué encontró»).

**La cifra 23/23 no es una tasa general:** se midió sobre el conjunto pequeño con el que se ajustó el método (10 textos sintéticos, 23 datos personales) y no hay un conjunto de prueba aparte. No debe leerse como «detecta el 100 %»: nombres en minúsculas o poco comunes pueden escapar, y por eso hay que revisar el texto anonimizado.
