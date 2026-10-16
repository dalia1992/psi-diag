# Guía de despliegue en Vercel

Esta guía es para hacerlo a mano, con calma y con tu asistente al lado. Son pocos pasos. Después de cada uno hay tres cosas: **qué deberías ver**, **cómo saber que funcionó** y **qué hacer si no**. Si algo no coincide con lo que dice aquí, detente y pregunta: las pantallas de GitHub y Vercel cambian de vez en cuando, por eso uso frases como «busca ... (los nombres pueden variar)».

Regla de oro: **las claves y el código de acceso nunca se pegan en un chat, en un correo ni en un archivo del repositorio.** Solo van en un gestor de contraseñas y en la pantalla de variables de Vercel.

## 0. Qué vas a tener al final

- Un repositorio en GitHub con este proyecto: **privado** si es solo tuyo, o **público** si lo va a revisar alguien del curso. En un repositorio público la regla es todavía más estricta: nunca subas un `.env`, claves ni el código de acceso (el historial de este proyecto se revisó y no los tiene).
- Un proyecto en Vercel (plan Hobby, gratis, sin tarjeta) con una dirección tipo `https://tu-proyecto.vercel.app`.
- Dos variables secretas: la clave de OpenRouter y un código de acceso que tú inventas.

Datos que conviene saber antes de empezar:

- El plan Hobby de Vercel es **solo para uso personal y no comercial**. Para ofrecer la herramienta a otras colegas con casos reales hay que pasar al plan Pro.
- La función tendría hasta **300 s** de duración (esto depende de que «Fluid Compute» esté activado) y 2 GB de memoria en el plan Hobby (según lo que sabíamos al preparar esta guía; confírmalo en la consola de Vercel). En una corrida real local un caso de texto tardó entre 60 y 174 s; la búsqueda CIE-11 (servidor en Azure) por sí sola varía entre 18 y 88 s. La memoria máxima fue de ~500-570 MB.
- La app corta por su cuenta a los 280 s con un error «timeout» que se puede reintentar.
- La primera solicitud después de un rato sin uso puede ser lenta.

## 1. Requisitos

- Cuenta de GitHub (github.com).
- Cuenta de Vercel (vercel.com). Elige el plan **Hobby**; no debería pedir tarjeta (según lo que sabíamos al preparar esta guía; confírmalo en la consola de Vercel). Puedes entrar con tu cuenta de GitHub.
- `git` instalado. Comprueba:

```bash
git --version
```

Debe imprimir una versión (por ejemplo `git version 2.x`). Si dice «command not found», instala git (en Mac: `xcode-select --install`).

- La clave de OpenRouter (openrouter.ai/keys) con algo de saldo. Guárdala ya en tu gestor de contraseñas.
- `openssl` (viene en Mac) para generar el código de acceso.

## 2. Preparar la carpeta (un aviso sobre Google Drive)

Este proyecto vive dentro de Google Drive. La carpeta oculta `.git` dentro de una carpeta sincronizada puede volverse lenta o pesada (miles de archivitos y el modelo de ~110 MB). Dos opciones:

- **A (más simple):** seguir en esta carpeta. Funciona, solo puede tardar más.
- **B (recomendada si notas lentitud):** trabajar desde una copia fuera de Drive. Una vez que el repositorio exista en GitHub, clónalo en una carpeta local (por ejemplo `~/proyectos`) con `git clone` y usa esa copia de ahí en adelante.

Antes de subir nada, revisa que no hay secretos que viajen:

```bash
git status
```

Debes ver `nothing to commit, working tree clean` (o solo archivos que reconoces). **No debe aparecer ningún `.env`.** Para estar seguras:

```bash
git ls-files | grep -i "\.env"
```

Lo único que debe salir es `.env.example` (es una plantilla vacía, sin claves). Si sale otro `.env`, detente y avisa.

## 3. Crear el repositorio vacío en GitHub

1. En github.com busca el botón para crear un repositorio nuevo (suele ser un «+» arriba a la derecha → «New repository»; los nombres pueden variar).
2. Ponle un nombre (por ejemplo `psi-diag`).
3. Elige la visibilidad: **Private** si es solo tuyo, o **Public** si es para que lo revise un profe. Si es público, ten presente que cualquiera puede leer el código (los secretos no están en él: viven solo en Vercel).
4. **No** marques «Add a README», «.gitignore» ni licencia: debe quedar vacío.
5. Crea el repositorio. GitHub muestra una dirección como `https://github.com/TU-USUARIO/psi-diag.git`.

Cómo saber que salió bien: arriba del nombre del repositorio aparece la etiqueta «Private» o «Public», según elegiste.

## 4. Subir el proyecto

Estos pasos **los ejecutan juntas** y no se hace nada de golpe. Primero entiende dónde está el trabajo.

**Estado actual:** la rama `main` ya contiene toda la aplicación (`app.py`, `backend/`, `public/`...). La rama `feature/fase1` es solo una copia local del mismo commit y no hace falta subirla. Vercel desplegará `main`, que es su rama de producción por defecto.

Comprueba en qué rama estás (debe decir `main`):

```bash
git branch --show-current
```

Conecta el repositorio de GitHub (cambia la dirección por la tuya):

```bash
git remote add origin https://github.com/TU-USUARIO/psi-diag.git
```

**Haz primero las comprobaciones de abajo** («Comprobaciones antes de cualquier `git push`») y solo cuando todas salgan bien ejecuta:

```bash
git push -u origin main
```

**Comprobaciones antes de cualquier `git push`** (en la rama que vas a subir):

```bash
git status
```

Debe decir `nothing to commit, working tree clean`.

```bash
git log --oneline -3
```

Los commits más recientes deben ser de la aplicación, no solo de documentos.

```bash
git ls-files | grep -E '(^|/)app\.py$'
```

Debe imprimir `app.py`. Si no imprime nada, estás en la rama equivocada: **no subas**.

```bash
git ls-files | grep -E '(^|/)\.env$'
```

No debe imprimir **nada** (`.env.example` no cuenta, no coincide). Si imprime algo, detente.

Si GitHub pide usuario y contraseña, en lugar de contraseña usa un token personal o el inicio de sesión que te sugiera (GitHub ya no acepta la contraseña normal). Nunca pegues ese token en un chat.

Sobre el tamaño: GitHub rechaza archivos de más de 100 MB. El modelo de anonimización (`backend/models/ner/`) está guardado **en dos partes de ~55 MB cada una** (`model_int8.onnx.part1` y `.part2`), por eso GitHub las acepta. La app las junta en memoria al arrancar. No intentes «arreglarlo» juntándolas.

Cómo saber que funcionó: recarga la página del repositorio en GitHub (en la rama que subiste); ves las carpetas (`backend`, `public`, `docs`...) y el archivo `app.py`. Comprueba que **no** hay ningún `.env` y que la etiqueta de visibilidad («Private» o «Public») es la que elegiste.

Si falla: `remote origin already exists` → `git remote -v` para ver a dónde apunta y avisa; `file exceeds 100 MB` → avisa (algún archivo grande se coló); error de permisos → revisa que iniciaste sesión en la cuenta correcta.

## 5. Importar el repositorio en Vercel

1. En vercel.com entra a tu panel y busca «Add New... → Project» (los nombres pueden variar).
2. Si es la primera vez, autoriza que Vercel lea tus repositorios de GitHub. Puedes dar acceso **solo a este repositorio**; es lo más prudente.
3. Elige el repositorio y pulsa «Import».
4. En la pantalla de configuración revisa:
   - **Framework Preset:** deja el que Vercel detecte. Para este proyecto lo esperable es «Other» o que detecte Python/FastAPI por sí solo. Si te ofrece algo muy distinto (Next.js, por ejemplo), cámbialo a «Other».
   - **Root Directory:** la raíz del repositorio (donde está `app.py`).
   - **Build Command / Output Directory:** déjalos vacíos o como vengan; el proyecto no compila nada. La carpeta `public/` es la raíz web: Vercel la sirve sola desde su CDN, sin configurar nada. Si al terminar la página no aparece, ve a «La página no aparece / 404 en la raíz» en la sección 14.
5. Todavía **no agregues variables secretas** (la única excepción es la opcional de abajo). Despliega (botón «Deploy»).

Para ver el tamaño de la función en el registro de construcción, antes de pulsar Deploy (o después, y luego haz un nuevo despliegue) puedes añadir **una variable de entorno de construcción** `VERCEL_ANALYZE_BUILD_OUTPUT` con valor `1`. Es la única variable que puedes agregar ahora: es opcional, solo sirve para mirar tamaños y no es secreta. Cuando ya hayas visto el tamaño, quítala (no hace falta dejarla).

Cómo saber que funcionó: tras unos minutos Vercel muestra «Congratulations» o un estado «Ready» y un botón para visitar el sitio.

Si falla: abre el despliegue y lee el registro de construcción (sección «Build Logs»). Copia al asistente **solo las últimas líneas del error** (no hay secretos ahí). Causas típicas: versión de Python (el proyecto pide 3.12 en `.python-version`), o la función excede el límite de tamaño (ver paso 9).

## 6. Primer despliegue sin variables: debe decir «sin configurar»

Abre `https://TU-PROYECTO.vercel.app/api/health` (la dirección exacta aparece en Vercel). Deberías ver algo como:

```json
{"ok":true,"configurado":false,"requiere_codigo":false}
```

`configurado:false` es lo correcto en este momento: aún no hay clave. Abre también la página principal: debe verse la pantalla de inicio. Si intentas analizar algo, la app responde **«sin_configurar»**: es el comportamiento esperado, no un fallo. (En Vercel, sin `ACCESS_CODE` la app nunca queda abierta.)

Si `/api/health` da 404 o error 500, mira los «Runtime Logs»/«Logs» del proyecto (sección 9).

## 7. Agregar las variables

Primero genera el código de acceso en tu terminal:

```bash
openssl rand -base64 18 | tr -d '/+=' | cut -c1-20
```

Obtendrás ~20 caracteres al azar (solo letras y números, justo lo que necesita la app: ASCII, largo y sin signos raros). **Guárdalo en tu gestor de contraseñas ahora.** Debe ser **distinto** del que usas en tu equipo local.

En Vercel: abre el proyecto → «Settings» → «Environment Variables» (los nombres pueden variar). Agrega:

| Nombre | Valor | Notas |
|---|---|---|
| `OPENROUTER_API_KEY` | tu clave de OpenRouter | Obligatoria. Marca **Sensitive** si la opción aparece. |
| `ACCESS_CODE` | el código que generaste | Obligatoria. Marca **Sensitive**. |
| `MODEL_ID` | por ejemplo `anthropic/claude-haiku-5.5` | Opcional; ese es el valor por omisión. |
| `MAX_POR_MINUTO` | `8` | Opcional: consultas por minuto por visitante. |
| `BACKEND_TIMEOUT_S` | `280` | Opcional: segundos antes de cortar. Debe ser menor que 300. |
| `APP_URL` | la dirección de tu app, por ejemplo `https://TU-PROYECTO.vercel.app` | Opcional: se manda a OpenRouter solo como referencia de quién llama (cabecera `HTTP-Referer`). Si no la defines, no se manda. |
| `AGENT_MCP_URL` | dirección del servidor CIE-11 | Opcional; por omisión apunta al servidor en Azure. Solo cámbiala si te lo indican. |

Escribe el valor tú misma en el campo (no lo pegues en ningún chat). Las variables marcadas como Sensitive **no se pueden volver a leer en Vercel, solo reemplazar**: por eso el gestor de contraseñas es tu única copia. Deja marcados los entornos «Production» (y «Preview» si quieres probar ahí).

Importante: **las variables nuevas no afectan a un despliegue ya hecho.** Hay que volver a desplegar:

1. Ve a «Deployments», abre el menú «...» del último despliegue y elige «Redeploy» (los nombres pueden variar).
2. Espera a que quede «Ready».

## 8. Verificar el despliegue

1. `https://TU-PROYECTO.vercel.app/api/health` → ahora debe decir `"configurado":true` y `"requiere_codigo":true`. Solo muestra verdadero/falso, nunca los valores.
2. Abre la página. Escribe el código de acceso en el campo y pulsa «Iniciar».
3. Con un **caso inventado** (nunca uno real al probar), por ejemplo:

```text
Mujer de 34 años, ficticia, que desde hace tres meses refiere tristeza casi todos los días, poco interés por sus actividades, dificultad para dormir y cansancio constante. Dice que le cuesta concentrarse en el trabajo.
```

   Pega ese texto en «Escribir texto» y pulsa «Generar reporte». Verás una línea de tiempo con los pasos; tarda de uno a tres minutos.
4. Cuando termine, descarga el **Word** y el **PDF** y ábrelos: deben tener el reporte completo y el texto con acentos.
5. Prueba de punta a punta desde la terminal. Crea un archivo pequeño **fuera de Google Drive** que contenga solo tu código de Vercel. No escribas el código con `echo` en la terminal: quedaría guardado en el historial de la terminal. Mejor ábrelo en un editor de texto.

```bash
mkdir -p ~/.config/mvp_psico
```

```bash
nano ~/.config/mvp_psico/env_vercel
```

   Dentro del editor escribe una sola línea, `ACCESS_CODE=` seguido de tu código (cópialo del gestor de contraseñas). Guarda con Ctrl+O y Enter, y sal con Ctrl+X. (Si prefieres un editor gráfico, `open -e ~/.config/mvp_psico/env_vercel` abre TextEdit, pero el archivo debe existir antes: crea uno vacío con `touch` o usa `nano`.) Luego restringe quién puede leerlo:

```bash
chmod 600 ~/.config/mvp_psico/env_vercel
```

   Este script usa el Python del entorno virtual del proyecto. Si no lo creaste todavía, créalo siguiendo la sección «Correr en local» del README (`uv venv ~/.venvs/mvp_psico --python 3.12` y luego instalar `requirements-dev.txt`); o usa el `python` de tu propio entorno con `httpx` instalado.

   Ejecuta (cambia la dirección):

```bash
~/.venvs/mvp_psico/bin/python backend/scripts/probar_caso.py https://TU-PROYECTO.vercel.app --env-file ~/.config/mvp_psico/env_vercel --texto "Mujer de 34 años, ficticia, con tristeza casi diaria desde hace tres meses, poco interés, mal sueño y cansancio."
```

   Imprime un renglón por paso y termina con un resumen; el código de salida 0 significa que todo llegó a `ok`. El script nunca imprime el código.

## 9. Qué revisar en Vercel (la parte técnica)

**Duración de 300 s aceptada en Hobby.** El archivo `vercel.json` pide `maxDuration: 300`. Si el plan no lo permitiera, el registro de construcción lo diría con un mensaje sobre `maxDuration`. Que el despliegue quede «Ready» sin ese error es una buena señal, pero no una prueba. Confírmalo en Vercel: abre el proyecto → «Settings» → «Functions» (y busca también «Fluid Compute»; los nombres pueden variar) y comprueba que la duración máxima permitida sea de 300 s y que Fluid Compute esté activado. **Si ves un máximo menor (por ejemplo 60 s o 100 s), detente y avisa a tu asistente: no cambies código ni configuración por tu cuenta.** Después confirma con un caso largo: no debe cortarse antes de ~280 s por culpa de la plataforma.

**Qué se sube a la función.** El archivo `.vercelignore` deja fuera lo que no se usa en ejecución (`backend/tests/`, `backend/scripts/`, `docs/`, `.superpowers/`, los `.md`, `backend/requirements-dev.txt`, cachés y cualquier `.env`; `.env.example` se queda, es solo una plantilla). Debe seguir incluyendo `app.py`, `backend/src/`, `backend/models/`, `backend/assets/`, `public/`, `vercel.json`, `requirements.txt` y `.python-version`; la prueba `backend/tests/test_despliegue.py` lo comprueba. La estructura es: `app.py` (entrada que Vercel busca en la raíz, solo apunta a `backend/src/servidor.py`), `backend/` (código, modelo `backend/models/ner/`, fuentes del PDF `backend/assets/fonts/`, pruebas, scripts) y `public/` (la pantalla web, con sus fuentes en `public/fonts/`; es la carpeta estática que Vercel sirve por su cuenta).

**Tamaño de la función.** Estimación local (paquetes de Python ≈ 229 MB + modelo ≈ 106 MB + fuentes y código ≈ 1 MB) da unos **335 MB**, bajo el límite de 500 MB descomprimidos que Vercel pone a las funciones de Python (según lo que sabíamos al preparar esta guía; confírmalo en la consola de Vercel). Para verlo real: activa `VERCEL_ANALYZE_BUILD_OUTPUT=1` (paso 5) y busca en el registro de construcción la tabla de tamaños de la función. Si te acercas a los 500 MB, avisa: hay que quitar dependencias.

**Registros.** En el proyecto: «Logs» (o «Runtime Logs») muestra lo que escribe la app, una línea JSON por solicitud con `id`, `estado`, `ms` y tiempos por paso. **No contienen texto del caso ni el código de acceso.** Los «Build Logs» (dentro de cada despliegue) muestran la construcción. Cuando algo falle, el `id` que ves en la página sirve para encontrar su línea.

**Primera solicitud lenta.** Tras un rato sin uso, la función «arranca en frío»: cargar el modelo y los componentes tarda unos segundos extra (~2 s es una medición **local**; en Vercel la primera solicitud tras un rato sin uso puede tardar bastante más). No es un fallo. Si ocurre seguido, dímelo.

**Latencia del servidor CIE-11 (Azure).** Es la parte más variable (18-88 s). Revisa en los registros el campo de tiempos por paso para ver cuánto tomó la búsqueda. Si el servidor tarda demasiado, el caso puede acercarse a los 280 s y aparecer el error «timeout».

## 10. Pruebas de seguridad (adaptadas del kit)

Cambia `TU-PROYECTO` y usa un cliente como `curl` o el propio navegador. Nada de esto usa casos reales.

1. **Código incorrecto → 401, y 429 tras 5 fallos.** Prueba con un código falso:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://TU-PROYECTO.vercel.app/api/caso -H "x-access-code: incorrecto" -F "texto=prueba de acceso con codigo falso para verificar"
```

   Debe dar `401`. Repítelo hasta pasar de 5 intentos en un minuto: después debe dar `429`. **Puede variar:** el contador vive en la memoria de cada copia de la función (es «de mejor esfuerzo»), así que en Vercel el 429 puede no aparecer justo en el sexto intento y el contador puede reiniciarse cuando la función «despierta» de nuevo. Espera un minuto para que se libere (mientras tanto ni el código correcto pasa desde tu conexión).
2. **Cabeceras de seguridad y CSP.**

```bash
curl -sI https://TU-PROYECTO.vercel.app/
```

   Deben aparecer `content-security-policy`, `x-content-type-options: nosniff`, `x-frame-options: DENY`, `referrer-policy: no-referrer`, `permissions-policy` y `cross-origin-opener-policy`. En el navegador, la consola (F12) no debe mostrar bloqueos de la CSP al usar la página.
3. **Sin claves en la página ni en `public/`.** En el navegador «Ver código fuente» y revisa `app.js`, `index.html`: no debe haber `sk-or-`, ni tu código de acceso (compáralo a ojo con el de tu gestor de contraseñas; no lo pegues en ningún sitio). Haz lo mismo con el texto que devuelve `/api/health`. En tu copia local:

```bash
grep -rn "sk-or-" public/
```

   No debe imprimir nada.
4. **`/api/health` solo muestra verdadero/falso.** Ya lo viste en el paso 8: ni valores, ni nombres de modelo, ni rutas.
5. **Cuerpo muy grande rechazado.** Un archivo de más de 4 MB debe responder `413` con error «archivo» (la pantalla lo avisa antes de enviar). Un reporte de exportación de más de 200 KB también da `413`.
6. **Tipo de archivo no permitido rechazado.** Solo se aceptan JPG, PNG y PDF cuyo contenido coincida con su extensión. Sube desde la pantalla un `.txt` o un `.exe` renombrado: debe rechazarse con mensaje claro.
7. **El código nunca viaja en la dirección.** Se envía en una cabecera, no en la URL; confirma que la barra de direcciones nunca lo muestra y que los registros de Vercel tampoco lo contienen (busca un fragmento de tu código en «Logs»: no debe aparecer).

## 11. Si una clave se filtró

El orden importa: **primero revocar, después crear otra**.

1. En openrouter.ai/keys elimina (revoca) la clave filtrada.
2. Crea una nueva y guárdala en el gestor de contraseñas.
3. En Vercel → Settings → Environment Variables, edita `OPENROUTER_API_KEY` con la nueva.
4. Haz «Redeploy» (paso 7).
5. Si se filtró el código de acceso: genera otro (paso 7), cámbialo en Vercel, redespliega y avisa a quienes lo usan.
6. Revisa en OpenRouter el uso reciente por si hubo gastos que no reconoces.

## 12. Volver atrás y borrar

**Volver a una versión anterior.** En Vercel → «Deployments» busca un despliegue anterior que funcionara, abre su menú «...» y elige algo como «Promote to Production» o «Instant Rollback» (los nombres pueden variar). Alternativa: en tu repositorio, vuelve a la versión buena (`git revert` del cambio problemático) y súbela; Vercel despliega de nuevo.

**Borrar el despliegue.** Vercel → Settings → al final, «Delete Project» (confirma escribiendo el nombre). Para borrar también el código, elimina el repositorio en GitHub (Settings → «Delete this repository»). No olvides revocar la clave de OpenRouter si ya no la usarás.

## 13. Costos y datos

- **Costo por caso:** unos centavos de dólar en OpenRouter (modelo + búsquedas de guías; leer un archivo con OCR suma aproximadamente US$0.002 por página; revisa las cifras reales en tu panel de OpenRouter). Vercel Hobby no cobra, pero tiene límites de uso. Revisa tu saldo en OpenRouter de vez en cuando y, si quieres, ponle un tope de gasto.
- **Nada se guarda.** La app no tiene base de datos: el caso vive solo mientras se genera el reporte. Los registros guardan estados y tiempos, **nunca texto del caso**.
- **Archivos subidos (foto/PDF):** el archivo **original, con nombres incluidos, se envía antes de la anonimización** a: **OpenRouter** (que intermedia la llamada), el servicio de reconocimiento de texto (**Mistral**) y un modelo auxiliar de otro proveedor (**OpenAI**, `gpt-4o-mini`, que acompaña la petición aunque su respuesta se ignora). La pantalla lo nombra y pide confirmación con una casilla obligatoria; mantén ese aviso.
- **Texto escrito:** a OpenRouter, a los proveedores del modelo de lenguaje y a las búsquedas de guías llega solo el texto anonimizado (o títulos de entidades de la CIE-11); se intenta que no llegue el original (la detección automática puede fallar).
- **Preferencia de privacidad en OpenRouter.** Las llamadas de chat (extracción de síntomas, agente de la CIE-11 y redacción del reporte), la lectura de archivos (OCR) y las búsquedas de guías llevan `provider.data_collection = deny`, que pide a OpenRouter enrutar solo a proveedores que declaran no guardar ni entrenar con tus datos. **No la llevan** las dos llamadas a la «Decisions API» de OpenRouter (verificación de que el texto es clínico y elección de fuentes de guías): es una API en versión alfa y no está confirmado que acepte ese campo, y solo reciben el texto ya anonimizado. Es una **petición de enrutamiento**, no una garantía contractual: orienta la elección del proveedor del modelo, y no está confirmado que cubra también al proveedor propio del plugin de OCR; no prometas a nadie que los datos no se guardan ni se usan para entrenar. Si alguna vez una llamada fallara con «no endpoints found» (ningún proveedor cumple), avisa a tu asistente en lugar de quitar la preferencia por tu cuenta.
- **Antes de usar casos reales, revisa la privacidad de tu cuenta de OpenRouter.** En openrouter.ai, en la configuración de tu cuenta (los nombres pueden variar), busca las opciones de privacidad: que **no** permitan entrenar con tus datos ni guardar tus mensajes, y, si existe, la opción de enrutar solo a proveedores con **retención cero de datos** («zero data retention»). Haz esto **antes** de procesar cualquier caso real.
- **Vercel Hobby no es para uso comercial.** Hobby está pensado para uso personal; si la usarán otras colegas con casos de sus pacientes, necesitas el plan Pro (y revisar sus términos) antes de ofrecerla.
- **La anonimización puede fallar.** Se intenta ocultar nombres, lugares y organizaciones, pero hay nombres en minúsculas o poco comunes que el modelo puede no detectar. El texto anonimizado debe revisarse (la pantalla lo muestra en «Protección de datos personales → Ver qué encontró»). La cifra 23/23 de cobertura se midió sobre el conjunto pequeño de ajuste (10 textos, 23 datos personales), sin conjunto de prueba aparte: no es una tasa general.

## 14. Si algo falla: tabla por código de error

| Código | Qué significa | Causa probable | Qué hacer |
|---|---|---|---|
| `sin_configurar` | La app no tiene lo que necesita | Falta `OPENROUTER_API_KEY` o `ACCESS_CODE` en Vercel, o no se redesplegó después de agregarlas | Revisa `/api/health`; agrega la variable; «Redeploy». |
| `acceso` (401) | Código incorrecto | Código mal escrito, con espacios o diferente al de Vercel | Copia el código del gestor de contraseñas; compara con el que está en Vercel. |
| `limite` (429) | Demasiadas solicitudes o 5 códigos incorrectos en un minuto | Un botón pulsado muchas veces, o pruebas de seguridad | Espera un minuto y reintenta. Si es habitual, sube `MAX_POR_MINUTO`. |
| `timeout` | El análisis pasó de 280 s | Servidor CIE-11 lento, primera solicitud lenta, caso muy largo | Reintenta (es reintentable); acorta el caso; avisa si se repite. |
| `backend` | Error inesperado | Clave de OpenRouter inválida o sin saldo, servicio externo caído, fallo interno | Mira «Logs» con el `id` de la pantalla; revisa saldo y clave. |
| `archivo` | No se pudo usar el archivo | Más de 4 MB, más de 10 páginas, tipo no permitido o dañado | Usa JPG, PNG o PDF más pequeño. |
| `ocr` | Falta confirmar la lectura del archivo | No se marcó la casilla «Entiendo y quiero subir el archivo» | Marca la casilla de confirmación y reintenta. |
| `validacion` | La solicitud no es válida | Texto de menos de 20 o más de 8000 caracteres, o reporte de exportación inválido o demasiado grande | Ajusta el texto. |
| `corte` (desde la pantalla) | La conexión se cortó antes del final | Se cerró la pestaña, falló la red o la plataforma cortó el flujo | Pulsa «Reintentar»; si pasa de nuevo, revisa «Logs». |

**La página no aparece / 404 en la raíz.** El despliegue dice «Ready» y `/api/health` responde, pero `https://TU-PROYECTO.vercel.app/` da 404. La pantalla web está en `public/` (la carpeta estática que Vercel sirve sola); comprueba que existe `public/index.html` en la rama que desplegaste. Si existe y sigue el 404, **detente y avisa a tu asistente; no cambies ajustes por tu cuenta.**

Si nada de esto explica el problema: copia al asistente el `id` de la solicitud y la línea del registro (no contiene datos del caso), y el código de error que mostró la pantalla.
