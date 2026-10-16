// Lector de eventos del servidor (SSE). Funciones puras: se pueden probar con node, sin DOM.

const MENSAJE_CORTE = "La conexión se interrumpió antes de terminar. Puedes intentarlo de nuevo.";

/**
 * Separa un buffer de texto en eventos completos y el resto sin terminar.
 * Cada evento es un bloque terminado en línea en blanco; solo se usan las líneas `data:`.
 * Los comentarios (`: ping`) y los JSON mal formados se omiten sin lanzar errores.
 */
export function parsearSSE(buffer) {
  const texto = String(buffer ?? "").replace(/\r\n?/g, "\n");
  const bloques = texto.split("\n\n");
  const resto = bloques.pop(); // lo que no terminó con línea en blanco sigue pendiente
  const eventos = [];
  for (const bloque of bloques) {
    const datos = [];
    for (const linea of bloque.split("\n")) {
      if (linea.startsWith("data:")) datos.push(linea.slice(5).replace(/^ /, ""));
    }
    if (datos.length === 0) continue;
    try {
      eventos.push(JSON.parse(datos.join("\n")));
    } catch {
      // línea dañada: se omite
    }
  }
  return { eventos, resto };
}

/**
 * Decide cómo terminó el flujo según los eventos recibidos.
 * Sin evento final (`resultado` o `error`) se trata como un corte de conexión que se puede reintentar.
 */
export function interpretarFin(eventos) {
  const lista = Array.isArray(eventos) ? eventos : [];
  const error = lista.find((e) => e && e.tipo === "error");
  if (error) {
    const e = error.error || {};
    return {
      ok: false,
      error: {
        codigo: e.codigo || "backend",
        mensaje: e.mensaje || "Ocurrió un problema al procesar el caso. Puedes intentarlo de nuevo.",
        reintentable: e.reintentable !== false,
      },
    };
  }
  if (lista.some((e) => e && e.tipo === "resultado")) return { ok: true, error: null };
  return { ok: false, error: { codigo: "corte", mensaje: MENSAJE_CORTE, reintentable: true } };
}
