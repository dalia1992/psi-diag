// Pruebas del lector de eventos (SSE). Se ejecutan con: node --test public/sse.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { parsearSSE, interpretarFin } from "./sse.js";

test("evento_completo", () => {
  const { eventos, resto } = parsearSSE('data: {"tipo":"paso","id":"lectura"}\n\n');
  assert.deepEqual(eventos, [{ tipo: "paso", id: "lectura" }]);
  assert.equal(resto, "");
});

test("evento_partido_entre_trozos", () => {
  const a = parsearSSE('data: {"tipo":"pa');
  assert.deepEqual(a.eventos, []);
  const b = parsearSSE(a.resto + 'so","id":"x"}\n');
  assert.deepEqual(b.eventos, []);
  const c = parsearSSE(b.resto + "\n");
  assert.deepEqual(c.eventos, [{ tipo: "paso", id: "x" }]);
  assert.equal(c.resto, "");
});

test("varios_eventos_en_un_trozo", () => {
  const { eventos, resto } = parsearSSE('data: {"n":1}\n\ndata: {"n":2}\n\ndata: {"n"');
  assert.deepEqual(eventos, [{ n: 1 }, { n: 2 }]);
  assert.equal(resto, 'data: {"n"');
});

test("ignora_comentarios_ping", () => {
  const { eventos } = parsearSSE(': ping\n\ndata: {"n":1}\n\n: ping\n\n');
  assert.deepEqual(eventos, [{ n: 1 }]);
});

test("acepta_saltos_CRLF", () => {
  const { eventos, resto } = parsearSSE('data: {"n":1}\r\n\r\ndata: {"n":2}\r\n\r\n');
  assert.deepEqual(eventos, [{ n: 1 }, { n: 2 }]);
  assert.equal(resto, "");
});

test("json_malformado_se_omite_sin_lanzar", () => {
  const { eventos } = parsearSSE('data: {roto\n\ndata: {"n":3}\n\n');
  assert.deepEqual(eventos, [{ n: 3 }]);
});

test("termina_sin_evento_final_muestra_error_reintentable", () => {
  const r = interpretarFin([{ tipo: "paso", id: "lectura", estado: "en_curso" }]);
  assert.equal(r.ok, false);
  assert.equal(r.error.codigo, "corte");
  assert.equal(r.error.mensaje, "La conexión se interrumpió antes de terminar. Puedes intentarlo de nuevo.");
  assert.equal(r.error.reintentable, true);
});

test("fin_con_resultado_es_ok", () => {
  assert.deepEqual(interpretarFin([{ tipo: "resultado", resultado: {} }]), { ok: true, error: null });
});

test("fin_con_evento_error_devuelve_ese_error", () => {
  const error = { codigo: "timeout", mensaje: "Tardó demasiado.", detalle: "x", reintentable: true };
  const r = interpretarFin([{ tipo: "paso" }, { tipo: "error", error }]);
  assert.equal(r.ok, false);
  assert.equal(r.error.codigo, "timeout");
  assert.equal(r.error.mensaje, "Tardó demasiado.");
  assert.equal(r.error.reintentable, true);
});
