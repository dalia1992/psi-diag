# MVP del asistente de psicodiagnóstico · Plan de implementación (fase 1)

> **Para quien ejecute:** REQUIRED SUB-SKILL: usar superpowers:subagent-driven-development (recomendado) o superpowers:executing-plans. Los pasos usan casillas `- [ ]`.

**Goal:** Publicar una página web (Vercel) donde se escribe o sube un caso, se ve el avance paso a paso y se descarga el reporte en Word y PDF, con el motor del PoC corriendo dentro de una función de Vercel.

**Architecture:** FastAPI (esqueleto del kit `03_langchain`) con el paquete `poc_psico` copiado dentro. `/api/caso` devuelve eventos SSE conforme termina cada etapa del grafo; `/api/exportar/{formato}` convierte el reporte (JSON) a `.docx` o `.pdf`. La anonimización usa NER base en ONNX int8 + reglas. Sin base de datos: nada del caso se guarda.

**Tech Stack:** Python 3.12, FastAPI, LangGraph/LangChain, onnxruntime + tokenizers, python-docx, reportlab, JavaScript plano (sin frameworks), pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-mvp-psicodiagnostico-design.md` (leerla antes de empezar; el plan la cita por sección).

Todas las rutas son relativas a `Módulo 5/mvp_psicodiagnostico/` salvo que se indique otra cosa. El PoC (`../poc_psicodiagnostico/`) **no se modifica**; se copia.

## Global Constraints

- Python 3.12 (`.python-version`); el entorno virtual vive **fuera de Drive**: `export UV_PROJECT_ENVIRONMENT=~/.venvs/mvp_psico`.
- Sin `torch` ni `transformers` en producción (`requirements.txt`); solo en el script de exportación del modelo (se corre con el entorno del PoC, `~/.venvs/poc_psico`).
- Nada de texto del caso, nombres ni reportes en los registros del servidor: solo `id`, `estado`, `ms`, `via` (texto|archivo).
- Cuerpo de petición ≤ 4,5 MB (límite de Vercel): archivo ≤ 4 000 000 bytes; fotos reducidas en el navegador; PDF de hasta 10 páginas.
- `maxDuration` = 300 s (Hobby con Fluid Compute); `BACKEND_TIMEOUT_S` por defecto 280.
- Modelo por defecto `anthropic/claude-haiku-5.5` vía OpenRouter; claves solo en variables de entorno (`OPENROUTER_API_KEY`, `ACCESS_CODE`); `.env` nunca se sube.
- Interfaz: sin `innerHTML` con texto del modelo; CSP del kit (`script-src 'self'; style-src 'self'`) → **sin estilos ni scripts en línea**.
- Textos de interfaz en español clínico cotidiano: nunca «traza», «guardrail», «tool», «viñeta» ni nombres `icd11_*`.
- Aviso «Herramienta de apoyo; no sustituye el criterio clínico» en inicio y al pie del reporte. No se dice «datos sintéticos».
- Nombre de la app: **Ψ-DIAG con IA**, con «IA» resaltada en lavanda (pantalla y encabezado del PDF; Word en texto simple); aparece en encabezado, inicio y `<title>`. La Ψ se dibuja como SVG propio si Nunito no la incluye (verificar en Task 8/9; en Task 8 el PDF registra el SVG con `svglib` o lo rasteriza como imagen si hace falta).
- Paleta B: azul `#2F4B7C`, lavanda `#8E85C2`, menta `#5BB5A2`, fondo `#F7F6FC`. Tipografía Nunito, archivos locales.
- Word: Arial 12 pt, interlineado 1.5. PDF: Nunito incrustada, paleta B, encabezado con el nombre del asistente, pie con aviso y número de página. Sin Markdown descargable.
- Acceso: `ACCESS_CODE` obligatorio en Vercel (si falta, error `sin_configurar`); opcional solo en local.
- Despliegue en Vercel: lo hace la usuaria a mano, guiada (Task 11). **No hacer `git push` ni desplegar.**

## Review Focus

Entradas que el diseño no prueba explícitamente y que más probablemente fallarán; cada una tiene su prueba en la tarea indicada.

1. **Texto largo (hasta 8 000 caracteres) con un nombre pasado el token 512** del NER: no debe quedar sin ocultar. → Task 3.
2. **Archivo inválido**: `.exe` renombrado a `.pdf`, PDF corrupto, imagen > 4 MB, sin la casilla de confirmación del OCR, o texto y archivo a la vez: error claro, sin tocar servicios externos. → Task 7.
3. **Conexión cortada**: la persona cierra la pestaña a mitad, o el tiempo se agota: el servidor deja de trabajar, borra el archivo temporal y la pantalla muestra un error reintentable si el flujo termina sin evento final. → Tasks 7 y 9.
4. **Salida del modelo hostil o rara** (`<script>`, emojis, una palabra de 500 letras, listas vacías, acentos y ñ): ni los exportadores ni la pantalla fallan ni interpretan HTML. → Tasks 8 y 9.
5. **Nombres en minúsculas o en mayúsculas sostenidas** (`juan perez`, `LUCIA HERNANDEZ`): el spike los dejó escapar; se exige al menos que las mayúsculas sostenidas queden ocultas y que las minúsculas se documenten como límite conocido si la pasada auxiliar no las resuelve. → Tasks 2 y 3.

---

### Task 1: Esqueleto del proyecto

**Files:**
- Create: `app.py` (solo `/api/health`), `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.python-version`, `.gitignore`, `.env.example`, `vercel.json`, `README.md` (3 líneas)
- Copy: `../poc_psicodiagnostico/poc_psico/` → `poc_psico/`; `../poc_psicodiagnostico/tests/` → `tests/` (sin `test_notebook.py` ni `test_readme.py`)
- Copy: `../kit_mvp_vercel_v1/03_langchain/proyecto-vercel/{vercel.json,.gitignore,.python-version}` como punto de partida, ajustando `maxDuration` a 300 y añadiendo `"includeFiles": "models/**"`.

**Interfaces:**
- Produces: `GET /api/health` → `{"ok": true, "configurado": bool, "requiere_codigo": bool}`.

- [ ] **Step 1:** `git init`, crear el entorno (`uv venv --python 3.12`; `uv pip install -r requirements-dev.txt`). `requirements.txt` toma las versiones fijadas del kit (`fastapi`, `langchain`, `langchain-core`, `langchain-openai`, `langgraph`, `openai`, `pydantic`) y añade, resolviendo versiones actuales y fijándolas: `langchain-mcp-adapters`, `requests`, `pillow`, `pypdf`, `python-dotenv`, `python-multipart`, `onnxruntime`, `tokenizers`, `numpy`, `python-docx`, `reportlab`. `requirements-dev.txt`: `-r requirements.txt`, `pytest`, `pytest-asyncio`, `httpx`.
- [ ] **Step 2:** Escribir `tests/test_health.py::test_health_sin_clave` (con `TestClient`, sin `OPENROUTER_API_KEY`: `configurado == False`, `ok == True`). Verlo fallar, implementar `app.py` mínimo, verlo pasar.
- [ ] **Step 3:** Correr `pytest -q` completo. Esperado: pasan las pruebas copiadas del PoC (no necesitan red). Si alguna depende del notebook o del README, eliminarla.
- [ ] **Step 4:** Commit (`git add -A && git commit -m "chore: esqueleto del MVP con poc_psico copiado"`). `.env` queda en `.gitignore`.

### Task 2: Anonimización más robusta (`pii.py`)

**Files:** Modify `poc_psico/pii.py`; Test `tests/test_pii.py` (añadir).

**Interfaces:**
- Produces: `fusionar_entidades(entidades: list[dict]) -> list[dict]` (une entidades del mismo `entity_group` cuyo rango se toca o solapa; ordena por `start`); `extender_a_palabra(texto: str, ini: int, fin: int) -> tuple[int, int]` (amplía hasta los límites de palabra, letras y dígitos incluyendo acentos y ñ). `aplicar_entidades` las usa antes de resolver solapes.

- [ ] **Step 1:** Pruebas (nombres exactos):
  - `test_fusiona_fragmentos_contiguos`: entidades `LOC` (0,2) y (2,10) sobre `"Cochabamba"` → una sola `[LOC_1]`.
  - `test_extiende_a_la_palabra`: entidad `PER` sobre `"CIA HERNANDEZ"` dentro de `"Paciente LUCIA HERNANDEZ, 29"` → resultado `"Paciente [PER_1], 29"` (sin «LU» suelto).
  - `test_no_funde_tipos_distintos` y `test_conserva_comportamiento_previo` (las pruebas existentes de `aplicar_entidades` siguen pasando).
- [ ] **Step 2:** Verlas fallar; implementar; verlas pasar junto con todo `tests/test_pii.py`.
- [ ] **Step 3:** Commit.

### Task 3: NER en ONNX (`ner_onnx.py`) y modelo empaquetado

**Files:**
- Create: `poc_psico/ner_onnx.py`, `scripts/exportar_ner_onnx.py`, `models/ner/{model_int8.onnx,tokenizer.json,id2label.json}`, `tests/fixtures/ner_casos.json`, `tests/test_ner_onnx.py`
- Origen del modelo ya aprobado y en caché local: `mrm8488/bert-spanish-cased-finetuned-ner` (Hugging Face). Referencia desechable del spike: `/private/tmp/claude-501/-Users-dalia-Library-CloudStorage-GoogleDrive-daliaf172-gmail-com-Mi-unidad-LLM-solutions-architect-M-dulo-5/0058500c-cf43-4788-9ab9-10138084d2f8/scratchpad/spike/{eval_ner.py,export.py}` (su conjunto de 10 textos con 23 entidades pasa a `ner_casos.json`: lista de `{"texto", "entidades": [[cadena, tipo]]}`).

**Interfaces:**
- Produces: `decodificar_bio(offsets: list[tuple[int, int]], etiquetas: list[str]) -> list[dict]` (cada dict `{"entity_group", "start", "end"}`, ignora offsets `(0,0)`); `trozos(texto: str, max_chars: int = 1000) -> list[tuple[int, str]]` (cortes en espacio; devuelve desplazamiento y fragmento); `crear_ner_onnx(directorio: Path) -> Callable[[str], list[dict]]` — mismo contrato que `Componentes.ner`, ejecuta cada trozo y suma el desplazamiento a los rangos.
- Consumes: `aplicar_entidades` de Task 2.

- [ ] **Step 1:** Pruebas unitarias sin modelo: `test_decodificar_bio_une_tokens_de_una_entidad`, `test_decodificar_bio_separa_dos_entidades_B`, `test_trozos_cubre_todo_el_texto_sin_cortar_palabras`.
- [ ] **Step 2:** Prueba con el modelo real (marcador `@pytest.mark.modelo`, declarar el marcador en `pytest.ini`): `test_ner_cubre_al_menos_20_de_23` — con `ner_casos.json`, una entidad cuenta como cubierta si todos sus caracteres no blancos están dentro de algún rango detectado; aserción `cubiertas >= 20` y `caracteres_de_mas <= 10`.
- [ ] **Step 3 (Review Focus 1):** `test_nombre_despues_del_token_512`: texto de ~3 000 caracteres de relleno clínico sin nombres y `"Su hermana Dayana Torres"` al final; `Dayana` queda oculta.
- [ ] **Step 4:** Escribir `scripts/exportar_ner_onnx.py` (se corre con `~/.venvs/poc_psico/bin/python`, con `HF_HUB_OFFLINE=1`, porque necesita torch): exporta a ONNX (opset 17, ejes dinámicos), cuantiza a int8 y guarda `tokenizer.json` (tokenizer rápido) e `id2label.json` en `models/ner/`. Ejecutarlo; comprobar que `model_int8.onnx` pesa ~110 MB.
- [ ] **Step 5:** Implementar `ner_onnx.py` (`onnxruntime.InferenceSession` con `CPUExecutionProvider`, `tokenizers.Tokenizer` con `return_offsets`, sin importar `torch`/`transformers`). Correr los tests de los pasos 1–3 hasta verde.
- [ ] **Step 6 (Review Focus 5):** `test_mayusculas_sostenidas_quedan_ocultas` (`"Paciente LUCIA HERNANDEZ, 29 años"`). Si falla, añadir `con_pasada_auxiliar(ner)`: ejecuta además el NER sobre el texto con la primera letra de cada palabra en mayúscula (misma longitud) y une rangos; conservarla **solo si** sube las entidades cubiertas y no oculta nada en los dos textos sin nombres de `ner_casos.json`. Si las minúsculas (`juan perez`, `bogotá`) siguen escapando, registrarlo en `README.md` como límite conocido.
- [ ] **Step 7:** Commit (el `.onnx` se versiona; si Git lo rechaza por tamaño, usar Git LFS o excluirlo y documentar el script en `DESPLIEGUE.md` — decidir con la usuaria).

### Task 4: Reporte estructurado

**Files:** Modify `poc_psico/reporte.py`, `poc_psico/pii.py`, `poc_psico/grafo.py`; Test `tests/test_reporte.py`, `tests/test_pii.py`, `tests/test_grafo.py`.

**Interfaces:**
- Produces: `construir_datos(sintomas: dict, hipotesis: list, reporte: ReporteClinico, alternativas: list, fecha: date, guias: list | None, pruebas: list) -> dict` con claves exactas `fecha` (ISO), `caso` (`paciente_ref`, `edad`, `sexo`, `temporalidad`), `sintomas` (`cognitivos`, `emocionales`, `conductuales`, `afectacion_social`), `hipotesis` (`codigo`, `titulo`, `url`, `justificacion`, `criterios_cumplidos`, `criterios_no_cumplidos`), `ambiguedades`, `diferenciales`, `alternativas` (`codigo`, `titulo`, `url`), `datos_faltantes`, `pruebas` (`nombre`, `motivo`, `guia` {titulo,url}|None, `cita`), `guias` (`tipo`, `etiqueta`, `titulo`, `url`, `cita`), `aviso`. `MapaPII.reinsertar_datos(obj) -> tuple[obj, list[str]]` (recorre dict/list y reinserta en cada `str`). El estado del grafo gana `reporte_datos`; `ejecutar()` devuelve además `reporte` (dict ya con datos reinsertados). `render_markdown` se conserva.

- [ ] **Step 1:** Pruebas: `test_construir_datos_tiene_las_claves_del_contrato`, `test_pruebas_sin_guia_quedan_con_guia_none`, `test_reinsertar_datos_recorre_estructuras_anidadas`, `test_ejecutar_devuelve_reporte_con_nombres_reinsertados` (usa los componentes falsos de `tests/helpers.py`).
- [ ] **Step 2:** Verlas fallar; implementar; verlas pasar con toda la suite.
- [ ] **Step 3:** Commit.

### Task 5: Diccionario de equivalencias (`traduccion.py`)

**Files:** Create `poc_psico/traduccion.py`; Test `tests/test_traduccion.py`.

**Interfaces:**
- Produces: `PASOS: tuple[Paso, ...]` (`Paso` = dataclass `id`, `titulo`) en este orden y con estos títulos: `lectura` «Lectura del archivo», `proteccion` «Protección de datos personales», `verificacion` «Verificación del texto», `sintomas` «Identificación de síntomas», `cie11` «Búsqueda de diagnósticos en la CIE-11», `guias` «Búsqueda de guías clínicas (IMSS, APA, OMS)», `reporte` «Redacción del reporte». `ETIQUETAS_HERRAMIENTAS: dict[str, str]` con las tres herramientas del spec (sección 3); `frase_herramienta(nombre: str) -> str` (desconocida → «Consultando la CIE-11…»); `detalle_legible(paso_id: str, datos: dict) -> dict` con `{"resumen": str, "lineas": list[str]}` — `datos` es el estado parcial del grafo. Nunca incluye valores originales de datos personales, solo marcadores (`[PER_1]`) y conteos.

- [ ] **Step 1:** Pruebas: `test_ninguna_frase_expone_nombres_tecnicos` (recorre todos los pasos con los fixtures de `tests/fixtures/` y comprueba con regex que no aparece `icd11_`, `uri_api`, `guardrail`, `traza`, `tool`, `http://id.who.int`); `test_herramienta_desconocida_usa_frase_generica`; `test_proteccion_cuenta_marcadores_sin_valores_originales`; `test_verificacion_texto_no_clinico_explica_en_lenguaje_claro`.
- [ ] **Step 2:** Verlas fallar; implementar; verlas pasar. Commit.

### Task 6: Flujo con eventos (`ejecutar_eventos`)

**Files:** Modify `poc_psico/grafo.py`; Test `tests/test_grafo.py`.

**Interfaces:**
- Produces: `async def ejecutar_eventos(entrada: str, c: Componentes) -> AsyncIterator[dict]`. Eventos: `{"tipo": "paso", "id": str, "titulo": str, "estado": "en_curso"|"listo"|"omitido", "detalle": {"resumen", "lineas"}}` (el detalle solo en `listo`) y un único `{"tipo": "resultado", "resultado": dict}` al final (mismo dict que hoy devuelve `ejecutar`, más `reporte`, y `razon_amigable: str` para `fuera_de_alcance`/`error`). `ejecutar()` pasa a ser un envoltorio que consume el generador y devuelve el `resultado`. La lectura (OCR), la anonimización y los componentes síncronos se ejecutan con `asyncio.to_thread` para no bloquear el flujo de eventos.
- Consumes: `PASOS`, `detalle_legible` (Task 5); `reporte_datos` (Task 4).

- [ ] **Step 1:** Pruebas: `test_eventos_en_orden_y_un_solo_resultado` (texto: `lectura` ausente, los demás pares `en_curso`→`listo`), `test_archivo_incluye_lectura_con_el_texto_leido`, `test_texto_no_clinico_termina_con_fuera_de_alcance_sin_pasos_siguientes`, `test_falla_del_cie11_termina_con_error_y_razon_amigable`, `test_cancelar_el_generador_no_deja_tareas_colgadas`, y que todas las pruebas previas de `ejecutar` siguen pasando.
- [ ] **Step 2:** Verlas fallar; implementar (`graph.astream(..., stream_mode="updates")` para detectar el fin de cada nodo; el paso `en_curso` siguiente se emite al terminar el anterior); verlas pasar. Commit.

### Task 7: API (`/api/caso`, acceso, archivos)

**Files:** Create `componentes.py`, `errores_api.py` (copiado de `contrato.py` del kit, dejando solo `ErrorContrato` → `ErrorApi`, `respuesta_error`), `tests/test_api.py`, `tests/fixtures/eventos_demo.json`; Modify `app.py`.

**Interfaces:**
- Produces:
  - `async def obtener_componentes() -> Componentes` (cacheado por instancia; arma el LLM, MCP, agente, guardrail, JEV, OCR, guías y el NER de `models/ner/` con los mismos valores que las celdas 1.1, 2.1 y 3.1 del notebook; `MODEL_ID` y `AGENT_MCP_URL` sobreescribibles por entorno).
  - `POST /api/caso` — `multipart/form-data` con `texto` **o** `archivo`, más `confirma_ocr=true` si hay archivo. Respuesta `text/event-stream`: cada línea `data: <json>\n\n` con los eventos de Task 6 o `{"tipo":"error","error":{"codigo","mensaje","detalle","reintentable"}}`; comentario `: ping` cada 15 s.
  - Validaciones: texto de 20 a 8 000 caracteres; extensión `.jpg|.jpeg|.png|.pdf` **y** firma de bytes coincidente; archivo ≤ 4 000 000 bytes; PDF ≤ 10 páginas (ya lo valida el OCR del PoC). Códigos de error nuevos: `archivo`, `ocr`.
  - Acceso por cabecera `x-access-code` (comparación en tiempo constante); límite por visitante `MAX_POR_MINUTO` (por defecto 8); `MODO_DEMO=1` emite `eventos_demo.json` sin llamar a nada, **ignorado si existe la variable `VERCEL`**.

- [ ] **Step 1:** Pruebas con `TestClient` y componentes falsos inyectados (variable de módulo sustituible): `test_sin_codigo_responde_401`, `test_en_vercel_sin_access_code_configurado_responde_sin_configurar`, `test_texto_corto_responde_validacion`, `test_stream_entrega_pasos_y_resultado`, `test_registro_no_contiene_el_texto_del_caso` (capturar logs con un texto con un nombre y comprobar que no aparece).
- [ ] **Step 2 (Review Focus 2):** `test_archivo_renombrado_se_rechaza_por_firma`, `test_pdf_corrupto_da_error_archivo`, `test_imagen_mayor_a_4mb_se_rechaza`, `test_archivo_sin_confirmar_ocr_se_rechaza_sin_llamar_al_ocr`, `test_texto_y_archivo_a_la_vez_se_rechaza`.
- [ ] **Step 3 (Review Focus 3):** `test_archivo_temporal_se_borra_si_el_cliente_se_desconecta`, `test_tiempo_agotado_emite_error_reintentable` (con `BACKEND_TIMEOUT_S=0.1` y un componente lento). El archivo se guarda en `tempfile` con la extensión original y se borra en `finally`.
- [ ] **Step 4:** Verlas fallar; implementar `app.py` (adaptando `revisar_acceso`, `limitar`, `ip_de`, `registrar` del kit) y `componentes.py`; verlas pasar.
- [ ] **Step 5:** Commit.

### Task 8: Exportación a Word y PDF

**Files:** Create `exportar/__init__.py`, `exportar/docx.py`, `exportar/pdf.py`, `assets/fonts/Nunito-{Regular,SemiBold,Bold}.ttf`, `tests/test_exportar.py`; Modify `app.py` (`POST /api/exportar/{formato}`).

**Interfaces:**
- Produces: `generar_docx(reporte: dict) -> bytes`, `generar_pdf(reporte: dict) -> bytes` (entrada: el dict de `construir_datos`, Task 4). `POST /api/exportar/docx|pdf` (JSON del reporte, ≤ 200 KB, mismo control de acceso) → archivo con `Content-Disposition: attachment; filename="reporte-AAAA-MM-DD.<ext>"`; formato distinto → 404. Sin registrar el contenido.
- **Requiere permiso de la usuaria:** descargar Nunito (licencia OFL; origen Google Fonts / repositorio oficial de Nunito; indicar nombres, origen y tamaño antes de bajar). Para `public/fonts` (Task 9) y `assets/fonts` se usan las mismas familias en `.woff2` y `.ttf`.

- [ ] **Step 1:** Pruebas: `test_docx_usa_arial_12_e_interlineado_1_5` (abrir con `python-docx`: fuente del estilo `Normal` Arial, `Pt(12)`, `line_spacing == 1.5`), `test_docx_contiene_secciones_y_aviso`, `test_pdf_empieza_con_%PDF_y_tiene_aviso_y_numero_de_pagina` (texto extraído con `pypdf`), `test_pdf_incrusta_nunito` (fuentes con `/FontFile2` y nombre que contiene «Nunito»).
- [ ] **Step 2 (Review Focus 4):** `test_exportadores_aceptan_texto_hostil` (parametrizada para ambos formatos): `<script>alert(1)</script>`, emojis, una palabra de 500 letras, listas vacías, `ñ` y acentos, `pruebas` con `guia=None`: no lanza y el archivo se puede reabrir.
- [ ] **Step 3:** Pedir permiso y descargar las fuentes; implementar (`python-docx`: títulos en azul sobrio `#2F4B7C`; `reportlab`: plantilla con encabezado, pie y colores de la paleta B; PDF con ligas clicables); verlo todo pasar. Commit.

### Task 9: Pantalla web

**Files:** Create `public/index.html`, `public/estilos.css`, `public/sse.js`, `public/app.js`, `public/fonts/nunito-*.woff2`, `public/sse.test.mjs`. Referencia visual: `.superpowers/brainstorm/.../content/flujo-fase1-v2.html` de la sesión de diseño (ruta en el scratchpad de esa sesión) y la sección 3 del spec; si la sesión de diseño paralela dejó una pantalla terminada, partir de ella.

**Interfaces:**
- Produces: `parsearSSE(buffer: string) -> {eventos: object[], resto: string}` (en `sse.js`, ES module, testeable con `node --test`); `reducirImagen(archivo: File, ladoMax = 2000, calidad = 0.85) -> Promise<Blob>`. Estados de pantalla: `inicio → nuevo → avance → reporte`. Lee `GET /api/health` para saber si pide código. El código de acceso vive solo en memoria (no `localStorage`).
- Consumes: `/api/caso` y `/api/exportar/{formato}` (Task 7 y 8).

- [ ] **Step 1:** Pruebas de `parsearSSE` (`node --test public/sse.test.mjs`): `evento_completo`, `evento_partido_entre_trozos`, `varios_eventos_en_un_trozo`, `ignora_comentarios_ping`. Si `node` no está instalado, avisar a la usuaria y probar el parser desde el navegador integrado.
- [ ] **Step 2 (Review Focus 3):** `termina_sin_evento_final_muestra_error_reintentable` (función pura `interpretarFin(eventos) -> {ok, error}` en `sse.js`, probada con `node --test`).
- [ ] **Step 3:** Implementar las cuatro pantallas con DOM seguro (`textContent`/`createElement`, nunca `innerHTML`): línea de tiempo con `<details>` «Ver qué encontró» cerrados por defecto; aclaración de OCR con casilla obligatoria al elegir **Subir archivo** (texto del spec, sección 3); botones Word/PDF/Nuevo caso; aviso al pie; sin estilos en línea (clases CSS). PDF > 4 MB se rechaza en el cliente con mensaje claro; imágenes pasan por `reducirImagen`.
- [ ] **Step 4 (Review Focus 4):** `test_interfaz_no_usa_innerHTML` (script de Python que falla si `public/*.js` contiene `innerHTML`, `outerHTML` o `insertAdjacentHTML`), y verificación manual en el navegador integrado con `MODO_DEMO=1` de que un texto con `<script>` en un evento se ve como texto.
- [ ] **Step 5:** Verificación visual con el navegador integrado (`MODO_DEMO=1`, ancho de escritorio y 375 px): las cuatro pantallas, paleta B, Nunito cargada desde `/fonts/`, sin errores de CSP en consola. Commit.

### Task 10: Prueba de punta a punta en local

**Files:** Create `scripts/probar_caso.py`; Test: corrida manual.

**Interfaces:** `probar_caso.py <url> [--texto TEXTO | --archivo RUTA] [--codigo C]` imprime cada evento y el tiempo total; sale con código ≠ 0 si el resultado no es `ok`.

- [ ] **Step 1:** La usuaria crea `.env` local con `OPENROUTER_API_KEY` y `ACCESS_CODE` (guardado fuera de Drive si es posible, `POC_ENV_FILE`). Arrancar `uvicorn app:app --port 8000`.
- [ ] **Step 2:** Correr el caso P1 de `poc_psico/casos.py` por texto: esperado `ok`, el reporte sin los datos de `_DATOS_PERSONALES_P1` en el texto anonimizado, nombres reinsertados en el reporte final, tiempo < 300 s.
- [ ] **Step 3:** Repetir con `../poc_psicodiagnostico/data/caso1_m_28.jpeg` (confirmando OCR) y con un texto no clínico (esperado `fuera_de_alcance` con mensaje amable).
- [ ] **Step 4:** Descargar Word y PDF de ese reporte desde la pantalla y revisarlos a ojo. Revisar los registros del servidor: ningún nombre ni texto del caso. Commit.

### Task 11: Preparación del despliegue y entrega guiada

**Files:** Create `DESPLIEGUE.md`; Modify `README.md`, `vercel.json`.

- [ ] **Step 1:** `vercel.json` final: `maxDuration` 300, `includeFiles` para `models/**`, cabeceras de seguridad del kit. `DESPLIEGUE.md` en español, paso a paso: repositorio en GitHub (sin `.env`), importar en Vercel, variables `OPENROUTER_API_KEY` (Secret), `ACCESS_CODE`, opcionales `MODEL_ID`, `MAX_POR_MINUTO`, `BACKEND_TIMEOUT_S`; primer despliegue sin variables (debe verse «sin configurar»), segundo con variables; activar `VERCEL_ANALYZE_BUILD_OUTPUT=1` para ver el tamaño de la función; verificación con `scripts/probar_caso.py https://TU-PROYECTO.vercel.app`; pruebas de `kit_mvp_vercel_v1/05_entrega/PRUEBAS_DE_SEGURIDAD.md`.
- [ ] **Step 2:** Revisar contra el kit que `.gitignore` excluye `.env`, `.venv`, `.superpowers/`; `git status` sin secretos.
- [ ] **Step 3: PARAR.** Avisar a la usuaria: llegó el momento del despliegue manual. Hacerlo juntxs, un paso a la vez, verificando cada resultado (maxDuration aceptado en el plan Hobby, tamaño de la función, latencia del servidor CIE-11 desde Vercel, cabeceras y CSP, descargas Word/PDF). No hacer `git push` ni abrir Vercel sin ella.

---

## Autorrevisión contra el spec

- Secc. 2 metas → Tasks 6, 7, 9 (flujo), 8 (descargas), 7 (código). Anti-metas: nombres no filtrados (Tasks 2, 3, 5, 7), jerga (Task 5, regex), claves (Task 11).
- Secc. 3 pantallas, OCR, vocabulario, paleta, Nunito → Tasks 5, 9 y 8 (fuentes con permiso).
- Secc. 4 arquitectura, SSE, reporte como datos, duración → Tasks 4, 6, 7, 11.
- Secc. 4 anonimización (fusión, extensión, ONNX, mayúsculas) → Tasks 2 y 3.
- Secc. 5 reportes → Task 8. Secc. 6 acceso → Task 7. Secc. 7 privacidad/registros → Tasks 7 y 10. Secc. 8 pruebas → en cada tarea. Secc. 9 despliegue → Task 11.
- Fuera de alcance (login, sesiones, aportes) no tiene tarea, a propósito.
