"""Prueba de punta a punta contra un servidor en marcha (local o desplegado).

Uso: python backend/scripts/probar_caso.py http://localhost:8000 --texto "..." | --archivo foto.jpg --confirma-ocr
El código de acceso se lee del archivo de entorno (variable ACCESS_CODE) y nunca se imprime ni va en la línea de comandos.
Imprime un renglón por paso y un resumen del resultado (solo códigos y títulos, no el cuerpo del reporte).
Sale con 0 solo si el estado final es el esperado (`ok`, o el de --esperar); con 2 ante cualquier fallo del propio script.
--timeout (300 s por omisión) es el tiempo máximo sin recibir datos; el servidor corta a los 280 s con un error reintentable."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ENV_PREDETERMINADO = "~/.config/mvp_psico/env"


def parsear_sse(buffer: str):
    """Misma idea que public/sse.js: devuelve (eventos completos, resto sin terminar). Omite comentarios y JSON dañado."""
    bloques = buffer.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")
    resto = bloques.pop()
    eventos = []
    for bloque in bloques:
        datos = [l[5:].removeprefix(" ") for l in bloque.split("\n") if l.startswith("data:")]
        if not datos:
            continue
        try:
            evento = json.loads("\n".join(datos))
        except ValueError:
            continue
        if isinstance(evento, dict):
            eventos.append(evento)
    return eventos, resto


def leer_codigo(ruta_env: str) -> str:
    from dotenv import dotenv_values
    ruta = Path(ruta_env).expanduser()
    return (dotenv_values(ruta).get("ACCESS_CODE") or "").strip() if ruta.is_file() else ""


def linea_paso(e: dict) -> str:
    detalle = e.get("detalle") if isinstance(e.get("detalle"), dict) else {}
    return f"{e.get('id', '?'):<13} {e.get('estado', '?'):<9} {detalle.get('resumen', '')}"


def enviar(url: str, texto, archivo, confirma_ocr: bool, codigo: str, timeout: float):
    """Hace el POST y devuelve la lista de eventos, imprimiendo cada paso al llegar."""
    cabeceras = {"x-access-code": codigo.encode("utf-8")} if codigo else {}
    datos = {"texto": texto} if texto is not None else {"confirma_ocr": "true" if confirma_ocr else "false"}
    archivos = {"archivo": (archivo.name, archivo.read_bytes())} if archivo is not None else None
    eventos, buffer = [], ""
    with httpx.stream("POST", url.rstrip("/") + "/api/caso", data=datos, files=archivos, headers=cabeceras,
                      timeout=httpx.Timeout(timeout, connect=15)) as r:
        if r.status_code != 200:
            r.read()
            try:
                e = r.json().get("error", {})
            except ValueError:
                e = {}
            if not isinstance(e, dict):
                e = {}
            print(f"HTTP {r.status_code} codigo={e.get('codigo', '?')} mensaje={e.get('mensaje', '')}")
            return [{"tipo": "error", "error": e}]
        for trozo in r.iter_text():
            nuevos, buffer = parsear_sse(buffer + trozo)
            for e in nuevos:
                if e.get("tipo") == "paso":
                    print(linea_paso(e), flush=True)
                eventos.append(e)
    return eventos


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--texto")
    g.add_argument("--archivo", type=Path)
    p.add_argument("--env-file", "--codigo-desde-env", dest="env_file", default=ENV_PREDETERMINADO)
    p.add_argument("--confirma-ocr", action="store_true")
    p.add_argument("--esperar", default="ok", help="estado_final esperado (predeterminado: ok)")
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--guardar-resultado", type=Path, help="guarda el resultado JSON (contiene el caso: usa /private/tmp)")
    a = p.parse_args(argv)

    inicio = time.perf_counter()
    try:
        eventos = enviar(a.url, a.texto, a.archivo, a.confirma_ocr, leer_codigo(a.env_file), a.timeout)
    except Exception as e:  # noqa: BLE001  solo el nombre del tipo: el mensaje podría traer el código o el caso
        print(f"fallo: {type(e).__name__}")
        return 2
    total = time.perf_counter() - inicio

    error = next((e for e in eventos if e.get("tipo") == "error"), None)
    final = next((e for e in eventos if e.get("tipo") == "resultado"), None)
    if error or final is None:
        e = (error or {}).get("error") or {}
        print(f"sin resultado: codigo={e.get('codigo', 'corte')} mensaje={e.get('mensaje', '')} total_s={total:.1f}")
        return 1
    r = final.get("resultado") or {}
    hipotesis = ((r.get("reporte") or {}).get("hipotesis")) or []
    print(f"estado_final: {r.get('estado_final')}")
    print(f"razon_amigable: {r.get('razon_amigable') or '-'}")
    print(f"hipotesis: {len(hipotesis)} " + ", ".join(f"{h.get('codigo')} {h.get('titulo')}" for h in hipotesis))
    print(f"advertencias: {len(r.get('advertencias') or [])}")
    print(f"total_s: {total:.1f}")
    if a.guardar_resultado:
        try:
            fd = os.open(a.guardar_resultado, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            print(f"fallo: {type(e).__name__}")
            return 2
    return 0 if r.get("estado_final") == a.esperar else 1


if __name__ == "__main__":
    sys.exit(main())
