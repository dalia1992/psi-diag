"""NER (personas, lugares, organizaciones) con onnxruntime: sin torch ni transformers.

El modelo (`mrm8488/bert-spanish-cased-finetuned-ner`, int8) se versiona partido en
`model_int8.onnx.part1`, `.part2`... (GitHub rechaza archivos > 100 MB) y se reensambla en memoria.
Nunca se registra el texto.
"""
from pathlib import Path
from typing import Callable

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MAX_TOKENS = 512


def decodificar_bio(offsets: list, etiquetas: list) -> list:
    """Une tokens B-/I- en entidades {entity_group, start, end}. Ignora offsets (0, 0) (tokens especiales)."""
    entidades, actual = [], None
    for (ini, fin), etiqueta in zip(offsets, etiquetas):
        if ini == fin:
            continue
        if etiqueta == "O":
            actual = None
            continue
        prefijo, tipo = etiqueta.split("-", 1)
        if prefijo == "B" or actual is None or actual["entity_group"] != tipo:
            actual = {"entity_group": tipo, "start": int(ini), "end": int(fin)}
            entidades.append(actual)
        else:
            actual["end"] = int(fin)
    return entidades


def trozos(texto: str, max_chars: int = 1000) -> list:
    """Parte el texto en fragmentos de <= max_chars cortando en espacios. Devuelve (desplazamiento, fragmento)."""
    partes, ini, n = [], 0, len(texto)
    while ini < n:
        fin = min(ini + max_chars, n)
        if fin < n:
            corte = texto.rfind(" ", ini + 1, fin + 1)
            if corte > ini:
                fin = corte
        partes.append((ini, texto[ini:fin]))
        ini = fin
    return partes


def _leer_modelo(directorio: Path) -> bytes:
    partes = sorted(directorio.glob("model_int8.onnx.part*"), key=lambda p: int(p.name.rsplit("part", 1)[1]))
    if not partes:
        raise FileNotFoundError(f"No hay model_int8.onnx.part* en {directorio}")
    return b"".join(p.read_bytes() for p in partes)


def crear_ner_onnx(directorio: Path) -> Callable[[str], list]:
    """Devuelve ner(texto) -> [{entity_group, start, end}], mismo contrato que `Componentes.ner`."""
    import json
    directorio = Path(directorio)
    sesion = ort.InferenceSession(_leer_modelo(directorio), providers=["CPUExecutionProvider"])
    tokenizador = Tokenizer.from_file(str(directorio / "tokenizer.json"))
    id2label = {int(k): v for k, v in json.loads((directorio / "id2label.json").read_text(encoding="utf-8")).items()}
    entradas = {i.name for i in sesion.get_inputs()}

    def _ner_trozo(fragmento: str) -> list:
        enc = tokenizador.encode(fragmento)
        if len(enc.ids) > MAX_TOKENS and len(fragmento) > 1:
            # Nada se trunca en silencio: si el trozo excede el límite de tokens (emojis, [UNK]...), se parte y se reintenta.
            resultado = []
            for desp, sub in trozos(fragmento, max_chars=len(fragmento) // 2 + 1):
                resultado += [{**e, "start": e["start"] + desp, "end": e["end"] + desp} for e in _ner_trozo(sub)]
            return resultado
        campos = {
            "input_ids": enc.ids,
            "attention_mask": enc.attention_mask,
            "token_type_ids": enc.type_ids,
        }
        feeds = {k: np.array([v], dtype=np.int64) for k, v in campos.items() if k in entradas}
        logits = sesion.run(None, feeds)[0][0]
        etiquetas = [id2label[int(i)] for i in logits.argmax(-1)]
        return decodificar_bio(enc.offsets, etiquetas)

    def ner(texto: str) -> list:
        entidades = []
        for desplazamiento, fragmento in trozos(texto):
            if not fragmento.strip():
                continue
            for e in _ner_trozo(fragmento):
                entidades.append({**e, "start": e["start"] + desplazamiento, "end": e["end"] + desplazamiento})
        return entidades

    return ner


def _capitalizar_palabras(texto: str) -> str:
    """Primera letra de cada palabra en mayúscula y el resto en minúscula, con la misma longitud."""
    capitalizado = "".join(
        (p[:1].upper() + p[1:].lower()) if p.strip() else p
        for p in _separar_palabras(texto))
    return capitalizado if len(capitalizado) == len(texto) else texto


def _separar_palabras(texto: str) -> list:
    import re
    return re.findall(r"\s+|\S+", texto)


def con_pasada_auxiliar(ner: Callable[[str], list]) -> Callable[[str], list]:
    """Además del texto original, corre el NER sobre una versión 'Título' (misma longitud) y une los rangos.
    De la pasada auxiliar solo se aceptan PER y LOC: las ORG que inventa sobre minúsculas (p. ej. «oficina»)
    ocultaban texto clínico sin ganar cobertura.
    El modelo es sensible a mayúsculas: así detecta NOMBRES EN MAYÚSCULAS SOSTENIDAS o en minúsculas."""
    def ner_doble(texto: str) -> list:
        entidades = list(ner(texto))
        alterno = _capitalizar_palabras(texto)
        if alterno != texto:
            entidades += [e for e in ner(alterno) if e["entity_group"] in ("PER", "LOC")]
        return entidades
    return ner_doble
