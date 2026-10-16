// Ψ-DIAG con IA · pantalla web.
// Reglas: el DOM se arma solo con createElement/textContent (el texto del modelo puede traer marcas: nunca se interpreta
// como HTML); sin estilos ni código en línea (CSP); el código de acceso y el caso viven solo en memoria.
import { parsearSSE, interpretarFin } from "./sse.js";

const MIN_TEXTO = 20;
const MAX_TEXTO = 8000;
const MAX_BYTES = 4_000_000; // un PDF
const MAX_BYTES_TOTAL = 4_000_000; // todas las imágenes juntas (Vercel rechaza cuerpos de más de 4.5 MB)
const MAX_IMAGENES = 10;
// Lado mayor y calidad JPEG de cada intento: si las imágenes juntas pesan demasiado se prueba con el siguiente.
const NIVELES_REDUCCION = [[2000, 0.85], [1600, 0.8], [1300, 0.75], [1000, 0.7]];

const TITULOS = {
  conexion: "Conexión con los servicios",
  lectura: "Lectura del archivo",
  proteccion: "Protección de datos personales",
  verificacion: "Verificación del texto",
  sintomas: "Identificación de síntomas",
  cie11: "Búsqueda de diagnósticos en la CIE-11",
  guias: "Búsqueda de guías clínicas (IMSS, APA, OMS)",
  reporte: "Redacción del reporte",
};
const ACTIVIDAD = {
  conexion: "Conectando con los servicios (la primera vez puede tardar unos segundos)",
  lectura: "Leyendo el archivo",
  proteccion: "Ocultando nombres, lugares y organizaciones",
  verificacion: "Comprobando que sea un caso clínico",
  sintomas: "Organizando los síntomas",
  cie11: "Buscando el trastorno y revisando los criterios clínicos",
  guias: "Buscando guías clínicas relacionadas",
  reporte: "Redactando el reporte",
};
const CATEGORIAS = [
  ["Cognitivos", "cognitivos"],
  ["Emocionales", "emocionales"],
  ["Conductuales", "conductuales"],
  ["Afectación social", "afectacion_social"],
];

// ----------------------------------------------------------------------------- estado (solo memoria)
const estado = {
  codigo: "",
  requiereCodigo: false,
  modo: "texto",
  seleccion: [], // lo que la persona eligió, en orden: {archivo, nombre, esPdf, cache}
  archivos: [], // lo que se envía, ya validado y, si son fotos, reducidas: [{blob, nombre}]
  pasos: [], // recorrido terminado: {titulo, resumen, lineas}
  reporte: null,
  controlador: null,
  enCurso: false,
  procesando: false, // se están reduciendo las fotos elegidas
};
const filas = new Map(); // id de paso -> {li, avance, vivo, claves}

const $ = (id) => document.getElementById(id);

// ----------------------------------------------------------------------------- DOM seguro
function el(etiqueta, clase, texto) {
  const nodo = document.createElement(etiqueta);
  if (clase) nodo.className = clase;
  if (texto !== undefined && texto !== null) nodo.textContent = String(texto);
  return nodo;
}

function vaciar(nodo) {
  while (nodo.firstChild) nodo.removeChild(nodo.firstChild);
}

// Una línea del detalle es texto o {negrita, texto}: la parte en negrita se dibuja con <strong>, siempre como texto.
function normalizarLinea(linea) {
  if (linea && typeof linea === "object" && !Array.isArray(linea)) {
    return { negrita: String(linea.negrita ?? ""), texto: String(linea.texto ?? "") };
  }
  return String(linea);
}

function listaDe(elementos, clase) {
  const ul = el("ul", clase);
  for (const e of elementos) {
    const linea = normalizarLinea(e);
    const li = el("li");
    if (typeof linea === "string") {
      li.textContent = linea;
    } else {
      li.appendChild(el("strong", "", linea.negrita));
      li.appendChild(document.createTextNode(linea.texto ? ` ${linea.texto}` : ""));
    }
    ul.appendChild(li);
  }
  return ul;
}

function urlSegura(valor) {
  try {
    const url = new URL(String(valor), window.location.href);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function liga(texto, valor) {
  const href = urlSegura(valor);
  if (!href) return null;
  const a = el("a", "", texto);
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

function mostrarMensaje(nodo, texto) {
  nodo.textContent = texto || "";
  nodo.hidden = !texto;
}

// ----------------------------------------------------------------------------- pantallas
const PANTALLAS = ["inicio", "nuevo", "avance", "reporte"];

function irA(nombre) {
  for (const p of PANTALLAS) $(`pantalla-${p}`).hidden = p !== nombre;
  window.scrollTo(0, 0);
  const titulo = { inicio: "titulo-inicio", nuevo: "titulo-nuevo", avance: "titulo-avance", reporte: "titulo-reporte" }[nombre];
  if (titulo) $(titulo).focus({ preventScroll: true });
}

// ----------------------------------------------------------------------------- inicio
async function consultarSalud() {
  try {
    const r = await fetch("/api/health", { cache: "no-store" });
    const datos = await r.json();
    estado.requiereCodigo = Boolean(datos.requiere_codigo);
    // Despierta el modelo de protección de datos y la conexión a la CIE-11 mientras la persona escribe su caso: sin esperar la respuesta.
    if (datos.configurado) fetch("/api/calentar", { cache: "no-store" }).catch(() => {});
  } catch {
    estado.requiereCodigo = false;
  }
  $("bloque-codigo").hidden = !estado.requiereCodigo;
}

// El código se comprueba aquí, antes de pasar a «Nuevo caso»: así un código erróneo se detecta de inmediato y no se sube nada.
async function comprobarCodigo(codigo) {
  try {
    const r = await fetch("/api/acceso", { method: "POST", headers: { "x-access-code": codigo }, cache: "no-store" });
    if (r.ok) return { ok: true };
    const error = await errorDeRespuesta(r);
    return { ok: false, mensaje: error.mensaje };
  } catch {
    return { ok: false, mensaje: "No se pudo comprobar el código. Revisa tu conexión e inténtalo de nuevo." };
  }
}

async function iniciar() {
  const campo = $("codigo-acceso");
  const boton = $("boton-iniciar");
  if (boton.disabled) return;
  if (estado.requiereCodigo) {
    const codigo = campo.value.trim();
    if (!codigo) {
      mostrarMensaje($("mensaje-inicio"), "Escribe el código de acceso para continuar.");
      campo.focus();
      return;
    }
    boton.disabled = true;
    boton.textContent = "Comprobando…";
    const resultado = await comprobarCodigo(codigo);
    boton.disabled = false;
    boton.textContent = "Iniciar";
    if (!resultado.ok) {
      estado.codigo = "";
      mostrarMensaje($("mensaje-inicio"), resultado.mensaje);
      campo.focus();
      campo.select();
      return;
    }
    estado.codigo = codigo;
  }
  mostrarMensaje($("mensaje-inicio"), "");
  irA("nuevo");
  actualizarBotonGenerar();
}

// ----------------------------------------------------------------------------- nuevo caso
function textoCaso() {
  return $("texto-caso").value.trim();
}

function actualizarContador() {
  const n = textoCaso().length;
  const contador = $("contador-texto");
  if (n === 0) contador.textContent = `0 de ${MAX_TEXTO} caracteres (mínimo ${MIN_TEXTO})`;
  else if (n < MIN_TEXTO) contador.textContent = `${n} de ${MAX_TEXTO} caracteres: faltan ${MIN_TEXTO - n} para el mínimo de ${MIN_TEXTO}`;
  else contador.textContent = `${n} de ${MAX_TEXTO} caracteres`;
}

function puedeGenerar() {
  if (estado.enCurso) return false;
  if (estado.modo === "texto") {
    const n = textoCaso().length;
    return n >= MIN_TEXTO && n <= MAX_TEXTO;
  }
  return $("confirma-ocr").checked && estado.archivos.length > 0 && !estado.procesando;
}

function actualizarBotonGenerar() {
  $("boton-generar").disabled = !puedeGenerar();
}

function elegirModo(modo) {
  estado.modo = modo;
  $("opcion-texto").setAttribute("aria-pressed", String(modo === "texto"));
  $("opcion-archivo").setAttribute("aria-pressed", String(modo === "archivo"));
  $("panel-texto").hidden = modo !== "texto";
  $("panel-archivo").hidden = modo !== "archivo";
  mostrarMensaje($("mensaje-nuevo"), "");
  if (modo === "archivo") {
    // La aclaración se muestra cada vez que se elige subir archivo: no se recuerda la aceptación.
    $("confirma-ocr").checked = false;
  }
  actualizarBotonGenerar();
}

/** Reduce una foto a JPEG con el lado mayor <= ladoMax. */
export async function reducirImagen(archivo, ladoMax = 2000, calidad = 0.85) {
  const imagen = await createImageBitmap(archivo, { imageOrientation: "from-image" });
  try {
    const escala = Math.min(1, ladoMax / Math.max(imagen.width, imagen.height));
    const ancho = Math.max(1, Math.round(imagen.width * escala));
    const alto = Math.max(1, Math.round(imagen.height * escala));
    const lienzo = document.createElement("canvas");
    lienzo.width = ancho;
    lienzo.height = alto;
    const ctx = lienzo.getContext("2d");
    ctx.fillStyle = "#ffffff"; // un PNG con transparencia no debe quedar negro al pasar a JPEG
    ctx.fillRect(0, 0, ancho, alto);
    ctx.drawImage(imagen, 0, 0, ancho, alto);
    return await new Promise((resolver, rechazar) => {
      lienzo.toBlob((blob) => (blob ? resolver(blob) : rechazar(new Error("sin imagen"))), "image/jpeg", calidad);
    });
  } finally {
    imagen.close();
  }
}

let turnoArchivo = 0;

function tipoDe(archivo) {
  const nombre = archivo.name.toLowerCase();
  if (nombre.endsWith(".pdf") || archivo.type === "application/pdf") return "pdf";
  if (/\.(jpe?g|png)$/.test(nombre) || archivo.type === "image/jpeg" || archivo.type === "image/png") return "foto";
  return null;
}

function tamanoLegible(bytes) {
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;
}

/** Dibuja la lista de lo elegido, con un botón para quitar cada archivo. */
function dibujarSeleccion() {
  const lista = $("lista-archivos");
  vaciar(lista);
  estado.seleccion.forEach((entrada, i) => {
    const li = el("li", "archivo-elegido");
    li.appendChild(el("span", "archivo-nombre", `${i + 1}. ${entrada.nombre}`));
    li.appendChild(el("span", "nota-suave", ` · ${tamanoLegible(entrada.archivo.size)}`));
    const quitar = el("button", "boton boton-suave boton-chico", "Quitar");
    quitar.type = "button";
    quitar.setAttribute("aria-label", `Quitar ${entrada.nombre}`);
    quitar.addEventListener("click", () => {
      estado.seleccion.splice(i, 1);
      procesarSeleccion();
    });
    li.appendChild(quitar);
    lista.appendChild(li);
  });
  lista.hidden = estado.seleccion.length === 0;
}

/** Suma lo elegido a la selección: un solo PDF, o hasta 10 fotos (sin mezclar). */
function agregarArchivos() {
  const nuevos = Array.from($("archivo-caso").files || []);
  $("archivo-caso").value = ""; // así se puede volver a elegir el mismo archivo
  mostrarMensaje($("mensaje-nuevo"), "");
  for (const archivo of nuevos) {
    const tipo = tipoDe(archivo);
    if (!tipo) return mostrarMensaje($("mensaje-nuevo"), "Solo se aceptan fotos JPG o PNG y archivos PDF.");
    const hayPdf = estado.seleccion.some((e) => e.esPdf);
    if (tipo === "pdf" && estado.seleccion.length > 0) {
      return mostrarMensaje($("mensaje-nuevo"), "Sube un solo PDF o varias fotos, sin mezclarlos. Quita lo anterior para cambiar.");
    }
    if (tipo === "foto" && hayPdf) {
      return mostrarMensaje($("mensaje-nuevo"), "Ya elegiste un PDF. Quítalo si prefieres subir fotos.");
    }
    if (tipo === "foto" && estado.seleccion.length >= MAX_IMAGENES) {
      return mostrarMensaje($("mensaje-nuevo"), `Puedes subir hasta ${MAX_IMAGENES} fotos.`);
    }
    estado.seleccion.push({ archivo, nombre: archivo.name, esPdf: tipo === "pdf", cache: new Map() });
  }
  procesarSeleccion();
}

async function reducirEntrada(entrada, nivel) {
  if (!entrada.cache.has(nivel)) {
    const [lado, calidad] = NIVELES_REDUCCION[nivel];
    entrada.cache.set(nivel, await reducirImagen(entrada.archivo, lado, calidad));
  }
  return entrada.cache.get(nivel);
}

/** Valida y prepara lo elegido: un PDF va tal cual; las fotos se reducen en el dispositivo hasta que juntas quepan en el envío. */
async function procesarSeleccion() {
  const turno = ++turnoArchivo; // una elección más reciente invalida a la anterior
  estado.archivos = [];
  dibujarSeleccion();
  actualizarBotonGenerar();
  if (estado.seleccion.length === 0) return;
  estado.procesando = true;
  actualizarBotonGenerar();
  try {
    if (estado.seleccion[0].esPdf) {
      const { archivo } = estado.seleccion[0];
      if (archivo.size > MAX_BYTES) {
        mostrarMensaje($("mensaje-nuevo"), "El PDF pesa más de 4 MB. Elige uno más liviano o escribe el caso como texto.");
        return;
      }
      estado.archivos = [{ blob: archivo, nombre: "caso.pdf" }];
      return;
    }
    for (let nivel = 0; nivel < NIVELES_REDUCCION.length; nivel++) {
      const reducidas = [];
      for (const entrada of estado.seleccion) {
        reducidas.push(await reducirEntrada(entrada, nivel));
        if (turno !== turnoArchivo) return;
      }
      const total = reducidas.reduce((suma, blob) => suma + blob.size, 0);
      if (total <= MAX_BYTES_TOTAL) {
        estado.archivos = reducidas.map((blob, i) => ({ blob, nombre: `hoja-${i + 1}.jpg` }));
        return;
      }
    }
    mostrarMensaje($("mensaje-nuevo"), "Las fotos pesan más de 4 MB juntas aun reducidas. Quita alguna o escribe el caso como texto.");
  } catch {
    if (turno !== turnoArchivo) return;
    mostrarMensaje($("mensaje-nuevo"), "No se pudo leer una de las fotos. Quítala, prueba con otra o escribe el caso como texto.");
  } finally {
    if (turno === turnoArchivo) {
      estado.procesando = false;
      actualizarBotonGenerar();
    }
  }
}

// ----------------------------------------------------------------------------- avance
function pasosEsperados() {
  const ids = ["proteccion", "verificacion", "sintomas", "cie11", "guias", "reporte"];
  return estado.modo === "archivo" ? ["lectura", ...ids] : ids;
}

function armarLineaDeTiempo() {
  const lista = $("linea-tiempo");
  vaciar(lista);
  filas.clear();
  for (const id of pasosEsperados()) crearFila(id, TITULOS[id]);
}

const FUENTES_GUIAS = ["IMSS", "APA", "OMS"];

/** Pone el nombre del paso. En el de las guías, IMSS, APA y OMS van en negritas (con <strong>, nunca como HTML). */
function ponerNombre(nodo, id, nombre) {
  vaciar(nodo);
  const dentro = id === "guias" ? /^(.*\()(IMSS), (APA), (OMS)(\).*)$/.exec(nombre) : null;
  if (!dentro) {
    nodo.textContent = nombre;
    return;
  }
  nodo.appendChild(document.createTextNode(dentro[1]));
  FUENTES_GUIAS.forEach((fuente, i) => {
    if (i > 0) nodo.appendChild(document.createTextNode(", "));
    nodo.appendChild(el("strong", "", fuente));
  });
  nodo.appendChild(document.createTextNode(dentro[5]));
}

function crearFila(id, titulo) {
  const li = el("li", "paso");
  const nombreFila = el("span", "paso-nombre");
  ponerNombre(nombreFila, id, titulo || TITULOS[id] || "Paso");
  li.appendChild(nombreFila);
  // Un paso inesperado se coloca en su lugar del recorrido, no al final.
  const orden = Object.keys(TITULOS);
  const mio = orden.indexOf(id);
  let antes = null;
  if (mio >= 0) {
    for (const [otroId, otra] of filas) {
      if (orden.indexOf(otroId) > mio) {
        antes = otra.li;
        break;
      }
    }
  }
  $("linea-tiempo").insertBefore(li, antes);
  const fila = { li, avance: null, vivo: null, claves: new Map() };
  filas.set(id, fila);
  return fila;
}

function anunciar(texto) {
  $("estado-lector").textContent = texto;
}

function aplicarPaso(ev) {
  const fila = filas.get(ev.id) || crearFila(ev.id, ev.titulo);
  const nombre = ev.titulo || TITULOS[ev.id] || "Paso";
  ponerNombre(fila.li.querySelector(".paso-nombre"), ev.id, nombre);
  if (fila.avance) {
    fila.avance.remove();
    fila.avance = null;
  }
  fila.li.classList.remove("en-curso", "listo", "fallo");
  if (ev.estado === "en_curso") {
    fila.li.classList.add("en-curso");
    fila.avance = el("p", "paso-avance", `${ACTIVIDAD[ev.id] || "Trabajando en este paso"}…`);
    fila.li.appendChild(fila.avance);
    anunciar(`En curso: ${nombre}`);
    $("aviso-ocr-avance").hidden = !(ev.id === "lectura");
  } else if (ev.estado === "listo") {
    fila.li.classList.add("listo");
    anunciar(`Listo: ${nombre}`);
    if (ev.id === "lectura") $("aviso-ocr-avance").hidden = true;
    if (ev.detalle && !fila.li.querySelector("details")) {
      // Lo que se fue mostrando en vivo (consultas a la CIE-11, hallazgos por fuente) pasa a «Ver qué encontró», antes del resumen final.
      const vivas = [...fila.claves.values(), ...(fila.sueltas || [])].map((x) => x.linea);
      const extra = Array.isArray(ev.detalle.lineas) ? ev.detalle.lineas : [];
      const detalle = { resumen: ev.detalle.resumen || "", lineas: [...vivas, ...extra.filter((l) => !vivas.some((v) => mismaLinea(v, l)))] };
      limpiarVivo(fila);
      fila.li.appendChild(detallesDelPaso(detalle));
      if (ev.id !== "conexion") estado.pasos.push({ titulo: nombre, resumen: detalle.resumen, lineas: detalle.lineas.map(normalizarLinea) });
    }
  }
}

function mismaLinea(a, b) {
  const x = normalizarLinea(a);
  const y = normalizarLinea(b);
  return JSON.stringify(x) === JSON.stringify(y);
}

function limpiarVivo(fila) {
  if (fila.vivo) fila.vivo.remove();
  fila.vivo = null;
  fila.claves = new Map();
  fila.sueltas = [];
}

/** Línea de avance dentro de un paso que sigue corriendo. Con `clave` se actualiza la línea que ya la tenía. */
function aplicarDetalle(ev) {
  const fila = filas.get(ev.paso);
  if (!fila || ev.linea === undefined || ev.linea === null) return;
  const linea = normalizarLinea(ev.linea);
  if (typeof linea !== "string" && !linea.negrita && !linea.texto) return;
  if (!fila.vivo) {
    fila.vivo = el("ul", "paso-vivo");
    fila.li.appendChild(fila.vivo);
    fila.sueltas = [];
  }
  const clave = typeof ev.clave === "string" ? ev.clave : "";
  const previa = clave ? fila.claves.get(clave) : null;
  const li = previa ? previa.li : el("li");
  vaciar(li);
  if (typeof linea === "string") {
    li.textContent = linea;
  } else {
    if (linea.negrita) li.appendChild(el("strong", "", linea.negrita));
    if (linea.texto) li.appendChild(document.createTextNode(linea.negrita ? ` ${linea.texto}` : linea.texto));
  }
  if (!previa) fila.vivo.appendChild(li);
  if (clave) fila.claves.set(clave, { li, linea });
  else fila.sueltas.push({ li, linea });
}

function detallesDelPaso(detalle) {
  const d = document.createElement("details"); // cerrado por defecto
  d.appendChild(el("summary", "", "Ver qué encontró"));
  const cuerpo = el("div", "detalle");
  if (detalle.resumen) cuerpo.appendChild(el("p", "", detalle.resumen));
  const lineas = Array.isArray(detalle.lineas) ? detalle.lineas : [];
  if (lineas.length) cuerpo.appendChild(listaDe(lineas));
  d.appendChild(cuerpo);
  return d;
}

function marcarFalloDelPasoEnCurso() {
  for (const fila of filas.values()) {
    if (fila.li.classList.contains("en-curso")) {
      fila.li.classList.remove("en-curso");
      fila.li.classList.add("fallo");
      if (fila.avance) fila.avance.textContent = "No se pudo completar este paso.";
    }
  }
}

function mostrarFalla(mensaje, { reintentable = true, marcarPaso = true } = {}) {
  if (marcarPaso) marcarFalloDelPasoEnCurso();
  $("titulo-avance").textContent = "No se pudo terminar";
  $("texto-error").textContent = mensaje;
  $("boton-reintentar").hidden = !reintentable;
  $("bloque-error").hidden = false;
  $("acciones-cancelar").hidden = true;
  $("aviso-ocr-avance").hidden = true;
  anunciar(mensaje);
  $("titulo-avance").focus({ preventScroll: true });
}

function prepararAvance() {
  estado.pasos = [];
  $("titulo-avance").textContent = "Analizando el caso…";
  $("bloque-error").hidden = true;
  $("acciones-cancelar").hidden = false;
  $("aviso-ocr-avance").hidden = true;
  anunciar("");
  armarLineaDeTiempo();
}

// ----------------------------------------------------------------------------- envío del caso
function cabeceraAcceso() {
  return estado.codigo ? { "x-access-code": estado.codigo } : {};
}

async function errorDeRespuesta(respuesta) {
  try {
    const cuerpo = await respuesta.json();
    const e = cuerpo.error || {};
    return { codigo: e.codigo || "http", mensaje: e.mensaje || "No se pudo procesar la solicitud.", reintentable: e.reintentable === true };
  } catch {
    return { codigo: "http", mensaje: "No se pudo procesar la solicitud. Puedes intentarlo de nuevo.", reintentable: true };
  }
}

async function enviar() {
  if (estado.enCurso) return;
  estado.enCurso = true;
  const controlador = new AbortController();
  estado.controlador = controlador;
  prepararAvance();
  irA("avance");

  const datos = new FormData();
  if (estado.modo === "archivo") {
    for (const archivo of estado.archivos) datos.append("archivos", archivo.blob, archivo.nombre);
    datos.append("confirma_ocr", "true");
  } else {
    datos.append("texto", textoCaso());
  }

  const eventos = [];
  try {
    const respuesta = await fetch("/api/caso", { method: "POST", headers: cabeceraAcceso(), body: datos, signal: controlador.signal });
    const tipo = respuesta.headers.get("content-type") || "";
    if (!respuesta.ok || !tipo.includes("text/event-stream")) {
      const error = await errorDeRespuesta(respuesta);
      if (error.codigo === "acceso") {
        estado.codigo = "";
        $("codigo-acceso").value = "";
        irA("inicio");
        mostrarMensaje($("mensaje-inicio"), error.mensaje);
        return;
      }
      mostrarFalla(error.mensaje, { reintentable: error.reintentable });
      return;
    }
    await leerFlujo(respuesta, controlador.signal, eventos);
    if (controlador.signal.aborted) return;
    const fin = interpretarFin(eventos);
    if (!fin.ok) {
      mostrarFalla(fin.error.mensaje, { reintentable: fin.error.reintentable });
      return;
    }
    const resultado = eventos.find((e) => e.tipo === "resultado").resultado || {};
    recibirResultado(resultado);
  } catch (e) {
    if (controlador.signal.aborted) return;
    mostrarFalla("No se pudo conectar. Revisa tu conexión e inténtalo de nuevo.", { reintentable: true });
  } finally {
    if (estado.controlador === controlador) {
      estado.controlador = null;
      estado.enCurso = false;
      actualizarBotonGenerar();
    }
  }
}

async function leerFlujo(respuesta, senal, eventos) {
  const decodificador = new TextDecoder("utf-8");
  let buffer = "";
  const procesar = (nuevos) => {
    for (const ev of nuevos) {
      eventos.push(ev);
      if (ev.tipo === "paso") aplicarPaso(ev);
      else if (ev.tipo === "detalle") aplicarDetalle(ev);
    }
  };
  if (!respuesta.body || !respuesta.body.getReader) {
    procesar(parsearSSE((await respuesta.text()) + "\n\n").eventos);
    return;
  }
  const lector = respuesta.body.getReader();
  while (!senal.aborted) {
    const { done, value } = await lector.read();
    if (done) break;
    buffer += decodificador.decode(value, { stream: true });
    const { eventos: nuevos, resto } = parsearSSE(buffer);
    buffer = resto;
    procesar(nuevos);
  }
  buffer += decodificador.decode();
  if (!senal.aborted) procesar(parsearSSE(buffer + "\n\n").eventos);
}

function recibirResultado(resultado) {
  if (resultado.estado_final === "ok" && resultado.reporte) {
    estado.reporte = resultado.reporte;
    dibujarReporte(resultado.reporte, resultado.advertencias || []);
    irA("reporte");
  } else if (resultado.estado_final === "fuera_de_alcance") {
    mostrarFalla(
      resultado.razon_amigable || "Esto no parece ser un caso de psicología clínica. Revisa el texto, ajústalo y vuelve a intentar.",
      { reintentable: false, marcarPaso: false },
    );
    $("titulo-avance").textContent = "No parece un caso de psicología clínica";
  } else {
    mostrarFalla(resultado.razon_amigable || "No se pudo completar el análisis. Puedes intentarlo de nuevo.", { reintentable: true });
  }
}

// ----------------------------------------------------------------------------- reporte
function seccion(titulo) {
  const s = el("section", "reporte-seccion");
  s.appendChild(el("h3", "", titulo));
  return s;
}

function lista(valor) {
  return Array.isArray(valor) ? valor.filter((x) => typeof x === "string" && x.trim()) : [];
}

function objetos(valor) {
  return Array.isArray(valor) ? valor.filter((x) => x && typeof x === "object") : [];
}

function dibujarReporte(reporte, advertencias) {
  const cuerpo = $("cuerpo-reporte");
  vaciar(cuerpo);

  const caso = reporte.caso && typeof reporte.caso === "object" ? reporte.caso : {};
  const datos = [];
  if (reporte.fecha) datos.push(`Fecha: ${reporte.fecha}`);
  if (caso.paciente_ref) datos.push(`Caso: ${caso.paciente_ref}`);
  if (caso.edad !== null && caso.edad !== undefined && caso.edad !== "") datos.push(`Edad: ${caso.edad}`);
  if (caso.sexo) datos.push(`Sexo: ${caso.sexo}`);
  if (caso.temporalidad) datos.push(`Temporalidad: ${caso.temporalidad}`);
  if (datos.length) cuerpo.appendChild(el("p", "datos-caso", datos.join(" · ")));

  // Síntomas por categoría
  const sSint = seccion("Síntomas identificados");
  const sintomas = reporte.sintomas && typeof reporte.sintomas === "object" ? reporte.sintomas : {};
  let hubo = false;
  for (const [etiqueta, clave] of CATEGORIAS) {
    const items = lista(sintomas[clave]);
    if (!items.length) continue;
    hubo = true;
    sSint.appendChild(el("h4", "", etiqueta));
    sSint.appendChild(listaDe(items));
  }
  if (!hubo) sSint.appendChild(el("p", "nota-suave", "No se identificaron síntomas."));
  cuerpo.appendChild(sSint);

  // Hipótesis
  const sHip = seccion("Hipótesis diagnósticas (CIE-11)");
  const hipotesis = objetos(reporte.hipotesis);
  if (!hipotesis.length) sHip.appendChild(el("p", "nota-suave", "Sin hipótesis diagnósticas para este caso."));
  for (const h of hipotesis) {
    const titulo = el("h4", "");
    titulo.appendChild(el("span", "codigo", h.codigo || "sin código"));
    titulo.appendChild(document.createTextNode(h.titulo || "Sin título"));
    sHip.appendChild(titulo);
    const enlace = liga("Abrir en el navegador OMS", h.url);
    if (enlace) {
      const p = el("p", "nota-suave");
      p.appendChild(enlace);
      sHip.appendChild(p);
    }
    if (h.justificacion) sHip.appendChild(el("p", "", h.justificacion));
    const cumplidos = lista(h.criterios_cumplidos);
    if (cumplidos.length) {
      sHip.appendChild(el("p", "etiqueta-lista", "Criterios cumplidos"));
      sHip.appendChild(listaDe(cumplidos, "cumplido"));
    }
    const faltan = lista(h.criterios_no_cumplidos);
    if (faltan.length) {
      sHip.appendChild(el("p", "etiqueta-lista", "Criterios no cumplidos o sin confirmar"));
      sHip.appendChild(listaDe(faltan));
    }
  }
  cuerpo.appendChild(sHip);

  const simples = [
    ["Ambigüedades", lista(reporte.ambiguedades)],
    ["Diagnósticos diferenciales a considerar", lista(reporte.diferenciales)],
  ];
  for (const [titulo, items] of simples) {
    if (!items.length) continue;
    const s = seccion(titulo);
    s.appendChild(listaDe(items));
    cuerpo.appendChild(s);
  }

  // Alternativas consideradas y descartadas
  const alternativas = objetos(reporte.alternativas);
  if (alternativas.length) {
    const s = seccion("Alternativas consideradas y descartadas");
    const ul = el("ul", "");
    for (const a of alternativas) {
      const li = el("li", "");
      li.appendChild(el("span", "codigo", a.codigo || "sin código"));
      li.appendChild(document.createTextNode(a.titulo || ""));
      const enlace = liga("Abrir en el navegador OMS", a.url);
      if (enlace) {
        li.appendChild(document.createTextNode(" · "));
        li.appendChild(enlace);
      }
      ul.appendChild(li);
    }
    s.appendChild(ul);
    cuerpo.appendChild(s);
  }

  const faltantes = lista(reporte.datos_faltantes);
  if (faltantes.length) {
    const s = seccion("Información que falta");
    s.appendChild(listaDe(faltantes));
    cuerpo.appendChild(s);
  }

  // Pruebas sugeridas
  const guias = objetos(reporte.guias);
  const pruebas = objetos(reporte.pruebas);
  if (pruebas.length) {
    const s = seccion("Pruebas sugeridas");
    const ul = el("ul", "");
    for (const p of pruebas) {
      const li = el("li", "");
      li.appendChild(el("strong", "", p.nombre || "Prueba"));
      if (p.motivo) li.appendChild(document.createTextNode(` · ${p.motivo}`));
      if (p.guia && typeof p.guia === "object") {
        li.appendChild(el("br"));
        li.appendChild(document.createTextNode("Referencia: "));
        li.appendChild(liga(p.guia.titulo || "guía", p.guia.url) || document.createTextNode(p.guia.titulo || "guía"));
        if (p.cita) li.appendChild(el("span", "nota-suave", ` «${p.cita}»`));
      } else if (guias.length) {
        li.appendChild(el("br"));
        li.appendChild(el("span", "sin-referencia", "sin referencia en las guías consultadas"));
      }
      ul.appendChild(li);
    }
    s.appendChild(ul);
    cuerpo.appendChild(s);
  }

  // Guías por fuente
  if (guias.length) {
    const s = seccion("Guías clínicas consultadas");
    const porFuente = new Map();
    for (const g of guias) {
      const fuente = g.etiqueta || g.tipo || "Otras fuentes";
      if (!porFuente.has(fuente)) porFuente.set(fuente, []);
      porFuente.get(fuente).push(g);
    }
    for (const [fuente, items] of porFuente) {
      s.appendChild(el("h4", "", fuente));
      const ul = el("ul", "");
      for (const g of items) {
        const li = el("li", "");
        li.appendChild(liga(g.titulo || "Guía", g.url) || document.createTextNode(g.titulo || "Guía"));
        ul.appendChild(li);
      }
      s.appendChild(ul);
    }
    cuerpo.appendChild(s);
  }

  // Conclusión, recomendaciones y siguientes pasos
  if (typeof reporte.conclusion === "string" && reporte.conclusion.trim()) {
    const s = seccion("Conclusión, recomendaciones y siguientes pasos");
    for (const parrafo of reporte.conclusion.split(/\n+/)) {
      if (parrafo.trim()) s.appendChild(el("p", "conclusion", parrafo.trim()));
    }
    cuerpo.appendChild(s);
  }

  // Notas amables
  const notas = lista(advertencias);
  if (notas.length) {
    const s = seccion("Para tener en cuenta");
    s.appendChild(listaDe(notas, "nota-suave"));
    cuerpo.appendChild(s);
  }

  // Recorrido
  if (estado.pasos.length) {
    const s = el("section", "reporte-seccion");
    const d = document.createElement("details");
    d.appendChild(el("summary", "", "Ver cómo se llegó a este reporte"));
    const ol = el("ol", "detalle");
    for (const paso of estado.pasos) {
      const li = el("li", "");
      li.appendChild(el("strong", "", paso.titulo));
      if (paso.resumen) li.appendChild(el("p", "", paso.resumen));
      if (paso.lineas.length) li.appendChild(listaDe(paso.lineas));
      ol.appendChild(li);
    }
    d.appendChild(ol);
    s.appendChild(d);
    cuerpo.appendChild(s);
  }

}

// ----------------------------------------------------------------------------- descargas
function nombreDeDescarga(respuesta, formato) {
  const cabecera = respuesta.headers.get("content-disposition") || "";
  const coincide = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cabecera);
  const limpio = coincide ? coincide[1].replace(/[^\w.\-]/g, "_") : "";
  return limpio || `reporte.${formato}`;
}

async function descargar(formato, boton) {
  if (!estado.reporte) return;
  mostrarMensaje($("mensaje-reporte"), "");
  boton.disabled = true;
  try {
    const respuesta = await fetch(`/api/exportar/${formato}`, {
      method: "POST",
      headers: { "content-type": "application/json", ...cabeceraAcceso() },
      body: JSON.stringify(estado.reporte),
    });
    if (!respuesta.ok) {
      const error = await errorDeRespuesta(respuesta);
      mostrarMensaje($("mensaje-reporte"), error.mensaje);
      return;
    }
    const blob = await respuesta.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nombreDeDescarga(respuesta, formato);
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch {
    mostrarMensaje($("mensaje-reporte"), "No se pudo descargar el archivo. Inténtalo de nuevo.");
  } finally {
    boton.disabled = false;
  }
}

// ----------------------------------------------------------------------------- reinicio
function cancelarEnvio() {
  if (estado.controlador) estado.controlador.abort();
  estado.controlador = null;
  estado.enCurso = false;
}

function nuevoCaso() {
  cancelarEnvio();
  estado.reporte = null;
  estado.pasos = [];
  estado.seleccion = [];
  estado.archivos = [];
  estado.procesando = false;
  turnoArchivo++;
  dibujarSeleccion();
  filas.clear();
  vaciar($("linea-tiempo"));
  vaciar($("cuerpo-reporte"));
  $("texto-caso").value = "";
  $("archivo-caso").value = "";
  $("confirma-ocr").checked = false;
  mostrarMensaje($("mensaje-nuevo"), "");
  mostrarMensaje($("mensaje-reporte"), "");
  elegirModo("texto");
  actualizarContador();
  irA("nuevo");
}

function editarCaso() {
  cancelarEnvio();
  irA("nuevo");
  actualizarBotonGenerar();
}

// ----------------------------------------------------------------------------- arranque
function conectar() {
  $("boton-iniciar").addEventListener("click", iniciar);
  $("codigo-acceso").addEventListener("keydown", (e) => {
    if (e.key === "Enter") iniciar();
  });
  $("opcion-texto").addEventListener("click", () => elegirModo("texto"));
  $("opcion-archivo").addEventListener("click", () => elegirModo("archivo"));
  $("texto-caso").addEventListener("input", () => {
    actualizarContador();
    actualizarBotonGenerar();
  });
  $("confirma-ocr").addEventListener("change", actualizarBotonGenerar);
  $("archivo-caso").addEventListener("change", agregarArchivos);
  $("boton-generar").addEventListener("click", enviar);
  $("boton-reintentar").addEventListener("click", enviar);
  $("boton-editar").addEventListener("click", editarCaso);
  $("boton-cancelar").addEventListener("click", editarCaso);
  $("boton-docx").addEventListener("click", (e) => descargar("docx", e.currentTarget));
  $("boton-pdf").addEventListener("click", (e) => descargar("pdf", e.currentTarget));
  $("boton-nuevo").addEventListener("click", nuevoCaso);
  actualizarContador();
  consultarSalud();
}

conectar();
