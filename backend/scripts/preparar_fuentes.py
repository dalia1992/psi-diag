"""Descarga Nunito (SIL OFL 1.1) del repositorio oficial y genera las instancias estáticas.

Origen único: github.com/googlefonts/nunito (archivado), vía raw.githubusercontent.com.
Salida: backend/assets/fonts/Nunito-{Regular,SemiBold,Bold}.ttf (PDF), public/fonts/nunito-{400,600,700}.woff2 (web)
y OFL.txt junto a cada carpeta. Requiere fonttools y brotli (requirements-dev.txt).

Uso: python backend/scripts/preparar_fuentes.py
"""
import io
import ssl
import urllib.request
from pathlib import Path

import certifi
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

RAIZ = Path(__file__).resolve().parents[2]   # raíz del repositorio
BASE = "https://raw.githubusercontent.com/googlefonts/nunito/main"
VARIABLE = f"{BASE}/fonts/variable/Nunito%5Bwght%5D.ttf"
LICENCIA = f"{BASE}/OFL.txt"
PESOS = {400: "Regular", 600: "SemiBold", 700: "Bold"}


def descargar(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60, context=ssl.create_default_context(cafile=certifi.where())) as respuesta:  # noqa: S310  URL fija y oficial
        return respuesta.read()


def main() -> None:
    destino_ttf, destino_web = RAIZ / "backend" / "assets" / "fonts", RAIZ / "public" / "fonts"
    destino_ttf.mkdir(parents=True, exist_ok=True)
    destino_web.mkdir(parents=True, exist_ok=True)
    datos = descargar(VARIABLE)
    licencia = descargar(LICENCIA)
    (destino_ttf / "OFL.txt").write_bytes(licencia)
    (destino_web / "OFL.txt").write_bytes(licencia)
    for peso, nombre in PESOS.items():
        fuente = instancer.instantiateVariableFont(TTFont(io.BytesIO(datos)), {"wght": peso}, updateFontNames=True)
        fuente.save(destino_ttf / f"Nunito-{nombre}.ttf")
        fuente.flavor = "woff2"
        fuente.save(destino_web / f"nunito-{peso}.woff2")
    psi = 0x03A8 in TTFont(io.BytesIO(datos)).getBestCmap()
    print(f"Listo. Ψ (U+03A8) en Nunito: {'sí' if psi else 'no'}")


if __name__ == "__main__":
    main()
