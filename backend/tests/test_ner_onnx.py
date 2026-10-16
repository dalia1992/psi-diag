import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from psi_diag.ner_onnx import decodificar_bio, trozos, crear_ner_onnx, con_pasada_auxiliar
from psi_diag.pii import MapaPII, aplicar_entidades

DIR_NER = Path(__file__).resolve().parents[1] / "models" / "ner"
CASOS = json.loads((Path(__file__).parent / "fixtures" / "ner_casos.json").read_text(encoding="utf-8"))


def test_decodificar_bio_une_tokens_de_una_entidad():
    offsets = [(0, 0), (0, 5), (6, 12), (13, 15), (0, 0)]
    etiquetas = ["O", "B-PER", "I-PER", "O", "O"]
    assert decodificar_bio(offsets, etiquetas) == [{"entity_group": "PER", "start": 0, "end": 12}]


def test_decodificar_bio_separa_dos_entidades_B():
    offsets = [(0, 5), (6, 12), (13, 20)]
    etiquetas = ["B-PER", "B-PER", "B-LOC"]
    assert decodificar_bio(offsets, etiquetas) == [
        {"entity_group": "PER", "start": 0, "end": 5},
        {"entity_group": "PER", "start": 6, "end": 12},
        {"entity_group": "LOC", "start": 13, "end": 20},
    ]


def test_trozos_cubre_todo_el_texto_sin_cortar_palabras():
    texto = " ".join(f"palabra{i}" for i in range(500))
    partes = trozos(texto, max_chars=100)
    assert len(partes) > 1
    assert all(len(frag) <= 100 for _, frag in partes)
    assert all(texto[desp:desp + len(frag)] == frag for desp, frag in partes)
    reconstruido = set()
    for desp, frag in partes:
        reconstruido.update(range(desp, desp + len(frag)))
    assert all(i in reconstruido for i, c in enumerate(texto) if c != " ")
    palabras = set(texto.split())
    assert all(p in palabras for _, frag in partes for p in frag.split())


def test_modelo_partido_se_reensambla_con_el_mismo_sha256():
    partes = sorted(DIR_NER.glob("model_int8.onnx.part*"))
    assert len(partes) >= 2
    assert all(p.stat().st_size <= 60 * 1024 * 1024 for p in partes)
    datos = b"".join(p.read_bytes() for p in partes)
    assert hashlib.sha256(datos).hexdigest() == "c1672d272e719e9c56a10af3e70a5f128e94945ab7c176c9a1ab45670e214a4c"


@pytest.fixture(scope="module")
def ner_base():
    return crear_ner_onnx(DIR_NER)


@pytest.fixture(scope="module")
def ner(ner_base):
    return con_pasada_auxiliar(ner_base)


def _ocultar(ner, texto):
    return aplicar_entidades(texto, ner(texto), MapaPII())


def _palabras(texto):
    return re.findall(r"\w+", texto)


def _medir(ner):
    """Camino de producción: NER -> aplicar_entidades (fusiona fragmentos y extiende a palabra completa).
    Una entidad está cubierta si ninguna de sus palabras significativas (>= 4 letras o siglas) sobrevive en
    el texto anonimizado. Caracteres de más: letras de palabras no-gold de >= 4 letras que desaparecieron."""
    total = cubiertas = de_mas = 0
    for caso in CASOS:
        texto = caso["texto"]
        salida = _ocultar(ner, texto)
        gold = set()
        for cadena, _ in caso["entidades"]:
            total += 1
            sig = [p for p in _palabras(cadena) if len(p) >= 4 or p.isupper()]
            gold.update(_palabras(cadena))
            if not any(re.search(rf"\b{re.escape(p)}\b", salida) for p in sig):
                cubiertas += 1
        sobrantes = Counter(_palabras(re.sub(r"\[[A-Z]+_\d+\]", " ", salida)))
        for p in _palabras(texto):
            if p in gold or len(p) < 4:  # artículos y títulos (la, del, don, Dra.) no son pérdida clínica
                continue
            if sobrantes[p] > 0:
                sobrantes[p] -= 1
            else:
                de_mas += len(p)
    return cubiertas, total, de_mas


@pytest.mark.modelo
def test_carga_desde_partes_sin_el_onnx_entero(tmp_path):
    for p in DIR_NER.glob("*"):
        if p.name != "model_int8.onnx":
            (tmp_path / p.name).write_bytes(p.read_bytes())
    ner_local = crear_ner_onnx(tmp_path)
    assert any(e["entity_group"] == "PER" for e in ner_local("Paciente: Laura Mendoza Ríos, de 34 años."))


@pytest.mark.modelo
def test_ner_cubre_al_menos_20_de_23(ner):
    cubiertas, total, de_mas = _medir(ner)
    print(f"cubiertas={cubiertas}/{total} caracteres_de_mas={de_mas}")
    assert total == 23
    assert cubiertas >= 20
    assert de_mas <= 10


@pytest.mark.modelo
def test_pasada_auxiliar_sube_la_cobertura_sin_falsos_positivos(ner_base, ner):
    assert _medir(ner)[0] > _medir(ner_base)[0]


@pytest.mark.modelo
def test_textos_sin_nombres_no_se_modifican(ner):
    for caso in CASOS:
        if not caso["entidades"]:
            assert _ocultar(ner, caso["texto"]) == caso["texto"]


@pytest.mark.modelo
def test_nombre_despues_del_token_512(ner):
    relleno = "Paciente con tristeza persistente, insomnio y pérdida de apetito desde hace meses. " * 38
    texto = relleno + "Su hermana Dayana Torres"
    assert len(texto) > 3000
    assert "Dayana" not in _ocultar(ner, texto)


@pytest.mark.modelo
def test_mayusculas_sostenidas_quedan_ocultas(ner):
    salida = _ocultar(ner, "Paciente LUCIA HERNANDEZ, 29 años")
    assert "LUCIA" not in salida and "HERNANDEZ" not in salida


@pytest.mark.modelo
def test_trozo_con_mas_de_512_tokens_no_se_trunca_en_silencio(ner):
    """Regresión: un trozo de <1000 caracteres puede superar 512 tokens (puntuación pegada = 1 token por signo)."""
    for relleno in ("😀 " * 300, ".,;:" * 200 + " "):
        salida = _ocultar(ner, relleno + "Su hermana Dayana Torres")
        assert "Dayana" not in salida and "Torres" not in salida


@pytest.mark.modelo
def test_nombre_en_el_limite_entre_trozos(ner):
    relleno = "tristeza persistente e insomnio. "
    for n in range(26, 34):
        texto = relleno * n + "Su hermana Dayana Torres vive aquí."
        salida = _ocultar(ner, texto)
        assert "Dayana" not in salida and "Torres" not in salida, n
