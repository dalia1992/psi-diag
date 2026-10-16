"""Revisiones estáticas de la pantalla web: DOM seguro, CSP (sin código ni estilos en línea) y vocabulario."""
import re
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "public"
PROHIBIDO_DOM = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(")


def _scripts():
    return sorted([*PUBLIC.glob("*.js"), *PUBLIC.glob("*.mjs")])


def test_interfaz_no_usa_innerHTML():
    archivos = _scripts()
    assert archivos, "no hay scripts en public/"
    for archivo in archivos:
        texto = archivo.read_text(encoding="utf-8")
        for patron in PROHIBIDO_DOM:
            assert patron not in texto, f"{archivo.name} usa {patron}"


def test_html_sin_scripts_ni_estilos_en_linea():
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    for etiqueta in re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.S | re.I):
        assert etiqueta.strip() == "", "hay un <script> con código en línea"
    assert not re.search(r"<script\b(?![^>]*\bsrc=)", html, flags=re.I), "hay un <script> sin src"
    assert not re.search(r"<style\b", html, flags=re.I), "hay una etiqueta <style>"
    assert not re.search(r"\sstyle\s*=", html, flags=re.I), "hay un atributo style="
    assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I), "hay un manejador de eventos en línea"
    assert not re.search(r"""(?:src|href|action)\s*=\s*["']?(?:https?:)?//""", html, flags=re.I), "hay una referencia a otro origen"
    assert "<title>Ψ-DIAG con IA</title>" in html


def test_textos_prohibidos_no_aparecen_en_la_interfaz():
    prohibidos = ("traza", "guardrail", "viñeta", "icd11_", "datos sintéticos")
    for nombre in ("index.html", "app.js", "estilos.css"):
        texto = (PUBLIC / nombre).read_text(encoding="utf-8").lower()
        for palabra in prohibidos:
            assert palabra not in texto, f"{nombre} contiene «{palabra}»"
        assert not re.search(r"\btools?\b", texto), f"{nombre} contiene «tool»"
