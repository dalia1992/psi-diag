# Registro de ejecución de la fase 1: decisiones, correcciones y pendientes

Copia del registro que se llevó durante la ejecución del plan (tareas 1 a 12, revisión final y reestructura). Los nombres de carpeta anteriores (`mvp_psicodiagnostico`, `poc_psico`) aparecen tal como eran en ese momento. Las líneas «Ruling» son decisiones tomadas por el orquestador; «minor (deferred)» son hallazgos menores que quedaron pendientes.

# SDD ledger — plan: <repo>/docs/superpowers/plans/2026-10-15-mvp-psicodiagnostico-fase1.md
Spec: docs/superpowers/specs/2026-10-15-mvp-psicodiagnostico-design.md (alcanzable)
Rama: feature/fase1 (repo nuevo, base 603ac88). Sin worktree: repo nuevo, sin otras ramas.

## Escaneo previo (pares de tareas que comparten archivo o interfaz)
| Par/Tarea | Productor → consumidor | Hallazgo |
|---|---|---|
| T2↔T3 | pii.aplicar_entidades (T2) ← anonimizar usado por la prueba de nombre tras token 512 (T3) | OK |
| T4↔T6 | reporte_datos/reporte (T4) → resultado de ejecutar_eventos (T6); ambos editan grafo.py | OK, secuencial |
| T5→T6 | detalle_legible/PASOS (T5) → eventos (T6) | OK |
| T3→T7 | crear_ner_onnx + models/ner (T3) → componentes.py (T7) | OK |
| T6→T7 | ejecutar_eventos (T6) → /api/caso (T7); T7 y T8 editan app.py | OK, secuencial |
| T7→T8→T9 | /api/exportar (T8) → botones (T9); fuentes Nunito T8 → public/fonts T9 | OK |
| T1..T11 consistencia interna | Cada tarea concuerda consigo misma | T3: el .onnx (110 MB) supera el límite de 100 MB por archivo de GitHub → ver Ruling 1. T3: el script de exportación necesita onnxruntime/onnx que no están en ~/.venvs/poc_psico → ver Ruling 2. T8: bajar Nunito requiere permiso explícito de la usuaria (regla de descargas) |

Ruling 1: T3 divide model_int8.onnx en 2 partes ≤ 60 MB (models/ner/model_int8.onnx.part1/.part2) y crear_ner_onnx las concatena en memoria al cargar (InferenceSession acepta bytes) — GitHub rechaza archivos >100 MB y Git LFS en Vercel es incierto — si me equivoco: cambio trivial a LFS o descarga al arrancar.
Ruling 2: T3 copia model_int8.onnx e id2label.json ya exportados en el spike (…/scratchpad/spike/onnx/) y usa el script solo para generar tokenizer.json con el entorno del PoC; el script documenta sus dependencias (onnx, onnxruntime, torch) — evita reinstalar paquetes en el entorno del PoC — si me equivoco: el script no se puede re-ejecutar sin instalar dependencias, queda documentado.
Ruling 3: T8 se detiene a pedir permiso a la usuaria para descargar las fuentes Nunito (nombre, origen, tamaño) antes de bajarlas — regla de descargas de la sesión — si me equivoco: una pregunta de más.

Task 1: complete (commits 603ac88..dafd84b, review clean)
Task 1: minor (deferred): test_health solo cubre el caso sin configurar; paquetes sin importar aún (pesan en el bundle: vigilar en T3/T11)
Ruling 4: uvicorn se agrega a requirements-dev.txt en T10 (se necesita solo para correr en local; no va a Vercel) — si me equivoco: un paso más en T10.

Task 2: complete (commits dafd84b..f59d3f4, review clean)
Task 2: minor (deferred): guion/apóstrofo no cuentan como carácter de palabra (p. ej. "Muñoz-Ávila", "O'Brien" parcialmente detectados dejan resto visible); dos fragmentos del mismo tipo separados por un espacio reciben marcadores distintos — evaluar en revisión final

Task 3: reviewed (9c72676) — Important: truncamiento silencioso a 512 tokens dentro de un trozo de 1000 caracteres (texto denso en [UNK]/emoji deja "Dayana" visible) → fix round 1
Task 3: minor (deferred): 23/23 es sobre el conjunto de ajuste (sin conjunto aparte; README/informe deben decirlo); test del token 512 solo comprueba "Dayana" (no "Torres" ni límite de trozo); la pasada auxiliar descarta ORG (ORG en minúsculas/MAYÚSCULAS solo lo detecta la pasada base; falta caso de regresión "oficina"); import re dentro de función y fallback silencioso si .lower() cambia la longitud; entidades duplicadas entre pasadas (cosmético)
Task 3: fix round 1/5 (1 addressed, 0 open — truncamiento a 512 tokens; commits 9c72676..74c90d8)
Task 3: complete (commits f59d3f4..74c90d8, review clean)
Task 3: minor (deferred, fuera de alcance): trozo sin espacios >512 tokens se corta a media palabra (requiere entrada adversaria); basura de puntuación sobre-oculta (no filtra)

Task 4: complete (commits 74c90d8..6b330c4, review clean)
Task 4: minor (deferred): línea densa de advertencias en grafo.py:190; criterios_* pasan por referencia en construir_datos; sin test del default "reporte": None en rutas de error/fuera_de_alcance; no se compara Markdown antes/después en ejecución (solo por lectura del diff)
Ruling 5: el paso `lectura` SÍ muestra en «Ver qué encontró» el texto leído por el OCR (lo exige el spec: la persona debe poder revisar que se leyó bien, el texto vuelve solo a su propio navegador, no a un tercero); la regla de "nunca valores originales" aplica al paso `proteccion` — si me equivoco: el detalle de lectura se reduce a conteos con un cambio pequeño.
Ruling 6: se añade icd11_buscar_sintomas_y_signos al diccionario con la frase «Buscando por síntomas y signos en la CIE-11» (el agente puede usarla con TOOLS_CON_SINTOMAS) — si me equivoco: una línea.

Task 5: complete (commits 6b330c4..a1fb1f7, review clean; 1 corrección por rulings 5 y 6 antes de la revisión)
Task 5: minor (deferred): traduccion.py usa [] en vez de .get para ítems parciales (KeyError si falta codigo/titulo/herramienta); paso_id desconocido lanza KeyError; \d acepta dígitos Unicode; PROHIBIDOS del test omite «viñeta»; faltan tests de datos vacíos/None y ramas vacías

Task 6: complete (commits a1fb1f7..04f2cce, review clean)
Task 6: minor (deferred): estado `omitido` nunca se emite (paso guias sin componente aparece "listo" con 0 guías); razon_amigable de "OCR no configurado" sale genérica; un paso fallido no emite evento de fallo (T9: la pantalla marca el paso en curso como fallido al llegar el resultado con error); hilos de trabajo no cancelables (T7: borrar archivo temporal solo cuando el hilo del OCR terminó); el evento `lectura` lleva el texto OCR con nombres reales a propósito (nadie debe registrarlo ni reenviarlo)

Task 7: reviewed (228dedd) — Approved con hallazgos menores; elevados a ronda de corrección 1:
Ruling 7: se elevan a corrección los menores 1 (fuerza bruta del código: el código compartido ES la protección principal de la fase 1 y protege llamadas de pago), 3 (formulario multipart nunca cerrado: archivo con datos personales en disco hasta el GC), 4 (ventana de fuga del archivo temporal antes de iniciar el generador) y 8 (prueba de privacidad que no afirma nada) — si me equivoco: una ronda extra de corrección.
Task 7: minor (deferred): límite de tamaño solo tras leer todo el cuerpo (en Vercel lo acota la plataforma a 4,5 MB; local sin tope); x-forwarded-for/x-real-ip confiables solo en Vercel (comentar); poda del limitador solo en rutas exitosas; es_archivo rechaza notas de una línea terminadas en .pdf/.png/.jpg; pypdf/PIL síncronos en el manejador (usar to_thread); BACKEND_TIMEOUT_S=nan/≤0 sin acotar; sin pings durante la construcción en frío; TimeoutError genérico se etiqueta como timeout
Task 7: fix round 1/5 (4 addressed, 0 open; commit 0d21291) + round 2 (F5 lista blanca del resultado al cliente; commit 0bf7984)
Task 7: complete (commits 04f2cce..0bf7984, review clean)
Task 7: observación: el límite de uso depende de x-real-ip/x-forwarded-for, confiables solo en Vercel (que los sobrescribe)
Ruling 3 cumplido: la usuaria autorizó (2026-10-16) descargar Nunito de github.com/googlefonts/nunito (fonts/variable, OFL, <1 MB) para T8/T9.
Task 8: nota: el implementador hizo 1 llamada a api.github.com (listado de la carpeta de fuentes del mismo repo autorizado) fuera de lo literal del permiso (solo raw.githubusercontent.com); sin descarga extra — informar a la usuaria
Task 8: reviewed (79cc3d1) — Important: surrogate UTF-16 suelto en un string JSON ("\ud800") hace fallar generar_docx (UnicodeEncodeError → 500) → fix round 1
Task 8: minor (deferred): marcas de ancho cero/combinantes en PDF; _vinetas no pasa `vacio` por _t (constante hoy); docx conserva emojis y PDF los cambia por "?"; docDefaults del docx conserva fuentes de tema (todos los estilos en uso las sobreescriben)
Task 8: fix round 1/5 (1 addressed, 0 open; commit 4e19705)
Task 8: complete (commits 0bf7984..4e19705, review clean)

Task 9: reviewed (327f6ab) — Approved (sin Critical/Important). Ruling 8: se elevan a ronda de corrección 1 los menores de accesibilidad y privacidad 1,2 (contraste AA), 3 (foco), 4 (aviso arriba y una vez al pie), 5 (carrera al elegir archivo), 6 (data:null rompe el lector), 7 (lineas no-array), 8 (autocomplete=off: el navegador no debe restaurar texto clínico) — es una herramienta clínica y son correcciones baratas; se difieren 9 (triple anuncio a lectores de pantalla) y 10 (pista del botón deshabilitado) — si me equivoco: una ronda extra.
Task 9: no verificado en navegador real: foto de cámara con orientación EXIF, descarga real del archivo, streaming real del backend (se verá en T10)
Task 9: fix round 1/5 (8 addressed, 0 open; commit f8772de)
Task 9: complete (commits 4e19705..f8772de, review clean)
Task 9: minor (deferred): triple anuncio a lectores de pantalla en cada fallo (role=alert + status + foco); falta aria-describedby en el botón Generar deshabilitado; h1 de inicio muestra anillo de foco por defecto

Task 10: reviewed (7515cc9) — Approved el script; Important: los 173,7 s de la primera corrida P1 quedaron sin explicar y la conclusión de "margen" no se sostiene (arranque en frío medido con una solicitud que no usa LLM/MCP; sin tiempos por paso; método de los booleanos de privacidad no registrado) → fix round 1.
Ruling 9: se pide medir con tiempos por paso (añadir los ms por paso al registro del servidor: son números sin datos personales), repetir P1 hasta 3 veces reiniciando el servidor, registrar el método de las comprobaciones de privacidad y endurecer el script — por qué: es el riesgo principal contra maxDuration=300 s en Vercel y la hipótesis más probable es que el servidor CIE-11 de Azure despierta de inactividad (el README del PoC ya avisa que la primera conexión puede tardar) — si me equivoco: 3 corridas reales más (centavos) y una ronda.
Task 10: minor (deferred): ver informe del revisor (--timeout por defecto 320 s > 300 s; mensaje del servidor impreso; archivo de resultado con chmod posterior) 
Task 10: fix round 1/5 (4 addressed, 0 open; commits 7e4f5fc, 31617ef)
Task 10: complete (commits f8772de..31617ef, review clean)
Task 10: hallazgos de la corrida real: P1 texto 3 corridas en frío 60,6/78,1/134,5 s (máx. observado en total 173,7 s); paso variable busqueda_cie11 18/32/88 s; guias 26-29 s; reporte ~10 s; construir componentes ~2 s; RSS pico 490-570 MB. Sin corrida en caliente (todas en frío).
Task 10: minor (deferred): pasos_ms vacío si hay timeout/error; int(x*1000) con NaN/inf rompería el registro (casi imposible); la sección E del informe tiene una frase confusa; informe lista las cadenas sintéticas de P1 como términos de búsqueda; ACCESS_CODE no ASCII puede no coincidir (usar ASCII); mejora futura: cronometrar cada llamada a tool y presupuesto de tiempo para busqueda_cie11

Task 11: reviewed (e6fdb09) — Needs fixes. Important: (1) DESPLIEGUE.md sección 4 hace `git push -u origin main` incondicional pero `main` solo tiene docs (la app está en feature/fase1) → se desplegaría una app vacía; falta decir que la decisión es de la usuaria y dar las dos rutas; (2) datos de la plataforma afirmados sin cautela (2 GB Hobby, 300 s requiere Fluid Compute, sin tarjeta, 500 MB descomprimidos, ~2 s); (3) "Ready sin error = 300 s aceptado" es débil → fix round 1.
Ruling 10: también se corrigen en la misma ronda los menores que afectan a quien siga la guía al pie de la letra (VERCEL_ANALYZE_BUILD_OUTPUT contradictorio con "sin variables", creación de env_vercel sin mkdir ni aviso del historial de la shell, límite de uso en memoria/por instancia sin matiz, supuesto del venv) — si me equivoco: un poco más de texto en la guía.
Task 11: minor (deferred): grep sk-or- en public/ es débil; costo OCR ~US$0.002/página sin verificar (matizar); recordar que las variables Sensitive no se pueden volver a leer
Task 11: fix round 1/5 (8 addressed, 0 open; commit 16fd3c8)
Task 11: complete (commits 31617ef..16fd3c8, review clean)
Task 11: pendiente para la ronda final de correcciones: DESPLIEGUE.md L177 dice «paso 10» pero los registros están en la sección 9; la Ruta B hace `git push` (L111) antes de las comprobaciones previas (L116) y no las menciona (la Ruta A sí) → mover/mencionar las comprobaciones antes de cualquier push.

FINAL REVIEW (opus, 603ac88..16fd3c8): Ready to deploy? CON CORRECCIONES. Sin Critical. Important: (1) bomba de descompresión de imagen (pixeles; to_thread), (2) consentimiento del OCR no nombra a OpenAI(gpt-4o-mini)/Mistral y no se aplican preferencias de privacidad del proveedor (data_collection deny), (3) advertencias del servidor llegan al cliente con vocabulario prohibido y posible texto de excepciones, (4) la promesa de anonimización no es verificable por la usuaria (suavizar texto, mostrar el texto anonimizado, huecos guion/apóstrofo).
Ruling 11: UNA sola ronda de corrección final con todo (incl. menores baratos #5,#6,#7,#8,#9,#10 y los 2 arreglos de la guía de T11); se difieren #11 (CSRF solo local), #12 (DoS de exportación) y el resto de menores. Decisión de la usuaria pendiente: vista previa local /api/anonimizar para confirmar el texto anonimizado antes de enviarlo a servicios externos (cambio de especificación) — se le ofrece, no se implementa. Pruebas con servicios reales autorizadas para verificar data_collection=deny (máx. 2 P1 texto + 1 foto).
Declined-to-judge del revisor (queda para la usuaria / después del despliegue): cumplimiento legal de datos de salud en Vercel Hobby/OpenRouter; si Vercel hace streaming SSE sin búfer y propaga desconexiones; reutilización del event loop entre invocaciones (vigilar «Event loop is closed»); si functions["app.py"].includeFiles se respeta; limitador por instancia; bloqueo por NAT compartido.
Decisión de la usuaria (2026-10-16): se omite por ahora la vista previa /api/anonimizar (confirmar el texto anonimizado antes de enviarlo a servicios externos); se podrá sumar después si hay casos reales.

Final fix wave: complete (commits 16fd3c8..ff14c08); re-review (opus): A1-A4, B1-B3, C, D2-D4, E5-E11 ADDRESSED; B4/D1 PARCIAL por un sobre-prometido nuevo: «revisa el texto que se enviará» (la usuaria no puede revisarlo antes de que salga; la vista previa quedó fuera por decisión suya).
Ruling 12: ese retoque de texto (3 archivos + fixture) y los menores #2,#3,#6 y la exclusión de .env en .vercelignore se hacen como Commit 1 del encargo de reestructura (Task 12), no en una segunda ola de corrección: la usuaria pidió la reestructura backend/ + frontend/ y conviene que todo vaya antes del merge a main — si me equivoco: el texto sobre-prometedor tendría que corregirse a mano.
Observaciones del re-revisor (no se arreglan ahora): el docx conserva dc:description «generated by python-docx» y app.xml de plantilla (sin datos personales); el límite de 40 MP aún permite picos de ~280 MB con RGBA (acotado por 4 MB de cuerpo); si se definiera LANGSMITH_API_KEY el estado del grafo (con advertencias_tecnicas y texto anonimizado) iría a LangSmith — no definirla; Vercel y .vercelignore sin verificar; la razón de la exclusión de provider en Decisions API pasa a «no está confirmado que acepte ese campo».
Task 12 (reestructura): encargo en restructure-brief.md; decisiones de la usuaria: carpeta final `psi-diag`, backend/src (psi_diag, exportar), backend/models, frontend/ aparte; ella hace el push; main = fuente de Vercel (se une feature/fase1 a main antes).
Task 12: complete (commits ff14c08..51c7c97, review clean)
