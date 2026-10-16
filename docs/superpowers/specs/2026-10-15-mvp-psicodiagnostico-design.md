# MVP del asistente de apoyo al psicodiagnóstico · Diseño (fase 1)

Fecha: 2026-10-15 · Estado: borrador para aprobación

Convención: **[decidido]** lo dijo o eligió la usuaria. **[mi decisión]** lo propuso el diseñador y puede cambiarse. **[abierto]** necesita respuesta de la usuaria antes de construir.

## 1. Intención

Llevar el PoC de psicodiagnóstico (`poc_psicodiagnostico/`, backend Python con LangGraph, hoy en un notebook) a un MVP: una página web pública en Vercel donde una persona clínica describe un caso y recibe un reporte con síntomas, hipótesis CIE-11, datos faltantes, pruebas sugeridas y guías clínicas. El MVP se parte del kit del curso (`kit_mvp_vercel_v1`, alternativa `03_langchain`), que trae pantalla, proxy FastAPI, contrato, límite de consultas y pruebas de despliegue.

El objetivo de fondo es que sirva con **casos reales**, no solo como demo. Eso fija la vara de privacidad (sección 7) y la redacción de la interfaz.

## 2. Alcance

### Metas de la fase 1
- Entrar a la página, pulsar **Iniciar**, elegir entre **escribir texto** o **subir un archivo** (foto o PDF de hasta 10 páginas) y generar el reporte.
- Ver el **avance en vivo**, paso por paso, y poder abrir en cada paso **«Ver qué encontró»** (cerrado por defecto) con la salida de esa etapa en lenguaje legible.
- Ver el reporte en pantalla y **descargarlo en Word (.docx) y PDF**.
- Acceso restringido con **código de acceso compartido**.
- Desplegado en Vercel, con la anonimización corriendo dentro de la misma función.

### Fuera de alcance de la fase 1 (fases posteriores, en este orden aproximado)
1. Login con Google; lista de correos autorizados reemplaza al código; opción de guardar la descarga en Drive si la persona lo permite.
2. Sesiones guardadas para revisar casos anteriores, cuidando los datos personales.
3. Más aportes de la persona clínica sobre el caso (antes o después de guardar sesiones).
4. Agregar información nueva (texto o documento) a un caso para afinar las hipótesis.

El diseño de la fase 1 no debe cerrar el paso a estas: el reporte y los pasos se representan como datos estructurados (no solo como texto), y el servidor no asume que cada caso es independiente para siempre.

### Anti-metas (el MVP fallaría aunque «funcione» si…)
- Se filtran nombres, lugares u organizaciones a un servicio externo desde el texto escrito.
- El reporte sugiere un diagnóstico como definitivo. Siempre es apoyo, no sustituye el criterio clínico.
- La pantalla muestra jerga técnica (nombres de herramientas internas, «guardrail», «traza», «tools»).
- Se publica una clave en el repositorio o en el navegador.

## 3. Experiencia de la persona usuaria  [decidido, salvo lo marcado]

Cuatro pantallas. Los bocetos están en `.superpowers/brainstorm/` de la sesión de diseño (`paleta.html`, `flujo-fase1-v2.html`).

1. **Inicio.** Título «Asistente de apoyo al psicodiagnóstico». Un párrafo amigable que explica qué hace (describe lo que observaste en consulta con tus palabras, o sube una nota o PDF; organiza síntomas, propone hipótesis según la CIE-11, señala qué falta y reúne guías), cuida los datos personales (se intentan ocultar los nombres de personas, lugares y organizaciones antes de analizar el texto; la detección automática puede fallar y ella debe revisar el texto anonimizado que se le muestra) y aclara que **es una herramienta de apoyo y no sustituye el criterio clínico**. No dice «datos sintéticos». Botón **Iniciar**. Si hay código de acceso, se pide aquí. **[mi decisión]**
2. **Nuevo caso.** «¿Qué quieres compartir?» con dos opciones: **Escribir texto** (área libre) y **Subir archivo** (foto o PDF). Botón **Generar reporte**. No se usa la palabra «viñeta». Al elegir **Subir archivo** aparece, antes de poder enviar, la **aclaración sobre el uso de OCR** (ver abajo), con una casilla de confirmación obligatoria.

#### Aclaración sobre el uso de OCR  [decidido que debe existir; redacción: mi propuesta]
Para leer fotos y PDF el sistema usa un **servicio externo de reconocimiento de texto (OCR)**: el archivo se envía completo a OpenRouter y a Mistral, **con los nombres y datos que contenga, antes de que se oculten**. Por eso, a diferencia del texto escrito, el archivo original sale del sistema sin proteger.

Texto propuesto para la pantalla (tono cercano, sin jerga):
> **Antes de subir tu archivo.** Para leer una foto o un PDF usamos un servicio externo de lectura de texto. El archivo se envía tal como está, *antes* de ocultar nombres y otros datos personales. Si es un caso real, te recomendamos tapar o recortar los datos personales antes de subirlo, o escribir el caso como texto. ☐ Entiendo y quiero subir el archivo.

Reglas:
- La casilla es obligatoria para habilitar el envío del archivo; el texto escrito no la pide.
- El aviso se muestra cada vez que se elige subir archivo (no se recuerda la aceptación).
- El mismo aviso, resumido, aparece en la pantalla de avance durante «Lectura del archivo» y en la sección de privacidad de la pantalla de inicio («los archivos se leen con un servicio externo antes de ocultar los datos personales»).
- Tras el OCR, el texto leído se muestra en «Ver qué encontró» para que la persona revise que se leyó bien, porque un error de lectura puede cambiar el sentido clínico (el PoC midió ~14 % de error de caracteres en una foto manuscrita).
3. **Avance.** Línea de tiempo vertical, sin cajas. Pasos, con estos nombres: Lectura del archivo (solo si hay archivo) · Protección de datos personales · Verificación del texto · Identificación de síntomas · Búsqueda de diagnósticos en la CIE-11 · Búsqueda de guías clínicas · Redacción del reporte. Cada paso terminado tiene «▸ Ver qué encontró», cerrado por defecto; el paso en curso muestra su avance (por ejemplo «Revisando criterios clínicos»). La palabra «traza» no aparece.
4. **Reporte.** Secciones: síntomas identificados, hipótesis diagnósticas (CIE-11, con código y liga a la OMS), información que falta, pruebas sugeridas, guías clínicas consultadas. Botones **Word (.docx)**, **PDF** y **Nuevo caso**. «Ver cómo se llegó a este reporte» (plegado) con el recorrido completo. El aviso de herramienta de apoyo se repite al pie. Sin descarga de Markdown.

### Vocabulario y diccionario de equivalencias
Ningún nombre interno de herramienta se muestra. Un único archivo (por ejemplo `traduccion.py`) mapea nombres internos a frases para la persona usuaria, p. ej.: `icd11_buscar_fundacion` → «Buscando el trastorno en la CIE-11»; `icd11_buscar_codigo_mms` → «Obteniendo el código CIE-11»; `icd11_obtener_criterios_clinicos` → «Revisando los criterios clínicos». Una herramienta no registrada muestra un texto genérico («Consultando la CIE-11…»), nunca su nombre técnico.

### Nombre de la app  [decidido]
El nombre visible es **Ψ-DIAG con IA**, con **«IA» resaltada** (en la pantalla, un resaltado en lavanda `#8E85C2`; «Ψ-DIAG con» en azul `#2F4B7C`). Reemplaza al título «Asistente de apoyo al psicodiagnóstico», que pasa a ser la descripción corta bajo el nombre. Aparece en el inicio, en el encabezado de todas las pantallas, en la pestaña del navegador y en el encabezado del PDF (con «IA» resaltada también allí; en el Word va en texto simple).
- **Detalle técnico [mi decisión]:** Nunito probablemente no incluye la letra griega Ψ; si es así, se dibuja como un pequeño SVG propio (en pantalla y en el PDF) en lugar de depender de una fuente de respaldo. Se verifica al implementar.

### Diseño visual
- **Paleta B** [decidido]: azul `#2F4B7C` (principal), lavanda `#8E85C2` (segundo protagonista: bordes, puntos de avance, títulos de sección, botones), menta `#5BB5A2` (acento/éxito), fondo `#F7F6FC`.
- **Sin cajitas separadas**: contenido en flujo, con separadores finos y espacio, legible.
- **Tipografía: Nunito** [decidido en una sesión de diseño paralela], incluida como archivos en `public/fonts` (sin depender de Google Fonts en ejecución; licencia OFL).
- Debe verse bien en móvil (el kit ya exige ancho de teléfono sin scroll horizontal).

## 4. Arquitectura

```
Navegador ──POST /api/caso (texto o archivo)──▶ función Vercel (FastAPI)
          ◀── eventos en vivo (SSE) paso a paso ──┘     │
                                                         ├─ OCR (Mistral vía OpenRouter) si hay archivo
                                                         ├─ anonimización local (NER ONNX + reglas)
                                                         ├─ verificación del texto (JEV/decisión)
                                                         ├─ extracción de síntomas (LLM, OpenRouter)
                                                         ├─ agente CIE-11 (MCP en Azure, ya desplegado)
                                                         ├─ búsqueda de guías (plugin web de OpenRouter)
                                                         └─ redacción del reporte (LLM)
Navegador ──POST /api/exportar (reporte en JSON)──▶ .docx / .pdf
```

- **Base de código [mi decisión]:** carpeta nueva `mvp_psicodiagnostico/` hermana de `poc_psicodiagnostico/`, con el esqueleto del kit `03_langchain/proyecto-vercel` y el paquete `poc_psico` **copiado** dentro (Vercel despliega un solo repositorio). El PoC queda como laboratorio y no se modifica.
- **Avance en vivo [mi decisión]:** el servidor emite eventos SSE: `{paso, estado, titulo, resumen_legible, detalle}` por cada etapa, más un evento final con el reporte estructurado. Reemplaza el contrato de una sola respuesta del kit; se mantiene su forma de errores (`ok:false`, `codigo`, `reintentable`). El grafo del PoC se ejecuta con su modo de streaming de eventos por nodo; si algún nodo no emite eventos útiles, se añaden.
- **Reporte como datos [mi decisión]:** el estado final se representa como JSON estructurado (síntomas, hipótesis con código y liga, faltantes, pruebas, guías con fuente) y de ahí salen la vista en pantalla, el Word y el PDF. Así las fases 3 y 4 pueden reutilizarlo.
- **Duración [decidido: 300 s]:** el PoC tarda unos 50 s con Haiku 5.5 y hasta unos 190 s con la foto y modelo gratuito. Se configura `maxDuration` = 300 s (el máximo del plan Hobby con Fluid Compute; verificar en la consola de Vercel al desplegar, porque algunas páginas de Vercel aún citan 60 s). Si un caso excede el tiempo, la pantalla muestra un error reintentable de tiempo agotado. Modelo por defecto: `anthropic/claude-haiku-5.5` (de pago).
- **Plan de Vercel [decidido]:** Hobby para el MVP del curso. Hobby es solo para uso personal y no comercial según los términos de Vercel; antes de ofrecerlo a otras personas clínicas con casos reales hay que pasar a Pro. El diseño no cambia entre planes (Pro daría hasta 800 s y 4 GB).

### Anonimización dentro de Vercel [decidido, tras un spike]
- Spike (muestra pequeña de ajuste: 10 textos sintéticos, 23 datos personales, sin conjunto de prueba aparte; no son una tasa general): modelo actual `MMG/xlm-roberta-large-ner-spanish` ocultó 21/23; `mrm8488/bert-spanish-cased-finetuned-ner` en ONNX int8 (110 MB, ~12 ms por texto) ocultó 20/23. Las fugas de ambos fueron nombres/lugares en minúsculas (`juan perez`, `bogotá`) y, en el base, un nombre en mayúsculas parcialmente.
- Se usa el **modelo base en ONNX int8**, con `onnxruntime` y `tokenizers` (sin `torch` en producción), más las reglas existentes de fechas, teléfonos, cédulas y correos de `pii.py`.
- **Dos mejoras obligatorias [mi decisión]:** (1) unir fragmentos contiguos de una misma entidad; (2) extender cada entidad detectada hasta los límites de la palabra, para no dejar letras sueltas (el PoC ya mostró «LU» como nombre). Opcional: tratar texto en minúsculas o en mayúsculas sostenidas con una pasada auxiliar.
- Los archivos del modelo ONNX se incluyen en el despliegue; la carga ocurre una vez por instancia.
- El spike es desechable (`scratchpad/spike`); lo que se conserve se reescribe con pruebas.

## 5. Reportes descargables  [decidido el formato; construcción a cargo del builder]

- **Word (.docx):** Arial 12 pt, interlineado 1.5 (estándar de documentos clínicos). Sin identidad de la app, salvo opcionalmente títulos en azul sobrio.
- **PDF:** conserva la identidad: Nunito incrustada, paleta B, encabezado con el nombre del asistente, pie con el aviso «herramienta de apoyo, no sustituye el criterio clínico» y numeración de páginas.
- No hay descarga de Markdown.
- Son dos plantillas distintas alimentadas por el mismo JSON del reporte. El PDF se genera con una solución que funcione en una función de Vercel (sin binarios pesados de navegador); la elección es del builder, midiendo tamaño y arranque.
- Los datos personales se **reinsertan** en el reporte al final, solo del lado del servidor/cliente (como en el PoC), nunca se envían a un servicio externo.

## 6. Acceso

- **Fase 1: código de acceso compartido [decidido]**, con la variable `ACCESS_CODE` del kit y su límite de consultas por minuto. Quien no lo tenga no ve nada útil.
- **Fase siguiente:** login con Google y lista blanca de correos (variable de entorno al inicio, tabla después). El servidor debe verificar el token de Google y que el correo esté verificado.
- **Quien no tiene cuenta de Google [mi decisión, a confirmar en esa fase]:** además de Google, ofrecer inicio de sesión por **enlace o código de un solo uso enviado al correo** (cualquier proveedor), contra la misma lista blanca de correos. Un servicio de autenticación gestionado (p. ej. Supabase Auth, que también serviría para guardar sesiones en la fase 2) resuelve ambos métodos. La descarga a Drive solo aplica a quien entre con Google. Mientras tanto, el código de acceso compartido sigue funcionando.

## 7. Privacidad y seguridad

- Texto escrito: se intenta que el texto original no salga del servidor; la detección automática puede fallar. Todo servicio externo (OpenRouter, MCP, búsquedas) recibe solo texto anonimizado (o títulos de entidades CIE-11), como en el PoC. La pantalla muestra el texto anonimizado («Ver qué encontró» en «Protección de datos personales») para que ella lo revise.
- **Archivos (foto o PDF) [decidido: se aceptan, con aclaración de uso de OCR]:** el PoC envía el archivo a OpenRouter y Mistral **antes** de anonimizar, con nombres sin ocultar. En el MVP se mantiene, pero la persona debe ser informada y confirmar antes de subir (sección 3, «Aclaración sobre el uso de OCR»), y el texto de inicio no promete que *todo* se oculte antes de salir: dice que se intentan ocultar los nombres antes de analizar el texto y que los archivos se leen con un servicio externo. Un OCR local queda como mejora futura.
- Sin base de datos ni guardado de casos en la fase 1: el caso vive en la pantalla y se pierde al cerrarla. Los registros del servidor no deben contener texto del caso ni datos personales.
- Claves (`OPENROUTER_API_KEY`, `ACCESS_CODE`) solo en variables de entorno de Vercel y en `.env` local (ignorado por git, fuera de Drive si es posible). Prueba de seguridad del kit (`05_entrega/PRUEBAS_DE_SEGURIDAD.md`) aplicada.
- La interfaz nunca usa `innerHTML` con texto del modelo (regla del kit).

## 8. Pruebas

- Mantener las pruebas unitarias del PoC (sin red) y los casos P1–P4.
- Añadir: pruebas del anonimizador (incluyendo fusión de fragmentos y extensión a palabra), del diccionario de traducción (sin nombres técnicos en pantalla), del flujo de eventos SSE, de la exportación a Word y PDF y del control de acceso.
- Verificación de punta a punta local antes de desplegar (`probar_endpoint.py` adaptado), y en Vercel después.

## 9. Despliegue

- **Lo hace la usuaria a mano, guiada paso a paso, con Claude al lado**: repositorio en GitHub (sin `.env`), importar en Vercel, variables de entorno, redeploy y verificación. El construido avisa cuando se llegue a ese punto.
- Plan Hobby, `maxDuration` 300 s: verificar el valor aceptado en la consola de Vercel al llegar al despliegue.

## 9b. Aclaraciones tras la revisión de un constructor independiente

- **Límites de Vercel [mi decisión]:** el tamaño no es problema (el límite de Python es 500 MB descomprimidos; el modelo ONNX son 110 MB más `onnxruntime`). El límite que sí importa es el **cuerpo de la petición (~4,5 MB)**: las fotos se reducen en el navegador antes de enviarse y los PDF se limitan a ese tamaño (aviso claro si lo superan); el tope de «10 páginas» se mantiene solo si cabe en ese tamaño.
- **Servidor MCP CIE-11:** es un endpoint SSE público en Azure (`AGENT_MCP_URL`, valor por defecto en `.env.example` del PoC), sin credenciales. Hay que medir su latencia desde Vercel y probar la primera conexión tras inactividad (puede tardar o fallar; el PoC ya reintenta).
- **Reinserción de datos personales [mi decisión]:** el mapa nombre↔marcador vive solo durante la petición en el servidor. Los datos se reinsertan en el servidor justo antes del evento final, que entrega el reporte completo al navegador. `/api/exportar` recibe ese reporte ya completo del navegador y genera el Word o el PDF sin guardar nada. Los registros del servidor no incluyen el texto del caso ni el reporte.
- **«Verificación del texto»:** es el filtro del PoC que comprueba que la entrada describe un caso clínico. Si no lo es, el flujo **termina sin error** con estado `fuera_de_alcance`: la pantalla muestra un mensaje amable («Este texto no parece describir un caso clínico; revisa lo que escribiste») y deja corregir y reintentar. Si el servicio de verificación falla, el flujo se detiene (falla cerrado, como en el PoC) con un error reintentable.

## 10. Preguntas abiertas para la usuaria

1. ~~Archivos con casos reales~~ **Resuelta:** se aceptan foto/PDF con la aclaración de uso de OCR y casilla de confirmación (sección 3).
2. ~~Plan de Vercel~~ **Resuelta:** Hobby con 300 s por caso (sección 4).

No quedan preguntas abiertas para la usuaria en la fase 1.

## 11. Lo que queda al builder

Estructura interna del código y de la copia de `poc_psico`; librerías de Word y PDF; formato exacto de los eventos SSE (respetando lo de la sección 4); contenido exacto de «Ver qué encontró» por paso (siempre legible y sin nombres técnicos); manejo de reconexión del flujo en vivo; forma de empaquetar el modelo ONNX.
