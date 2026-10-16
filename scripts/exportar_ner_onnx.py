"""Exporta el NER `mrm8488/bert-spanish-cased-finetuned-ner` a ONNX int8 para `models/ner/`.

Dependencias (solo para este script, NO van en requirements.txt): torch, transformers, onnx, onnxruntime.
Se corre con el entorno del PoC y sin red si el modelo ya está en la caché de Hugging Face:

    HF_HUB_OFFLINE=1 ~/.venvs/poc_psico/bin/python scripts/exportar_ner_onnx.py            # todo
    HF_HUB_OFFLINE=1 ~/.venvs/poc_psico/bin/python scripts/exportar_ner_onnx.py --solo-tokenizador

Genera en models/ner/: tokenizer.json (tokenizer rápido), id2label.json y el modelo int8 (~110 MB)
partido en model_int8.onnx.part1 / .part2 (GitHub rechaza archivos de más de 100 MB; el .onnx entero
está en .gitignore y `crear_ner_onnx` reensambla las partes en memoria).
"""
import argparse
import json
import tempfile
from pathlib import Path

MODELO = "mrm8488/bert-spanish-cased-finetuned-ner"
DESTINO = Path(__file__).resolve().parent.parent / "models" / "ner"
TAMANO_PARTE = 60 * 1024 * 1024


def guardar_tokenizador():
    from transformers import AutoTokenizer
    DESTINO.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(MODELO)
    tok.backend_tokenizer.save(str(DESTINO / "tokenizer.json"))


def exportar_y_cuantizar():
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    DESTINO.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(MODELO)
    modelo = AutoModelForTokenClassification.from_pretrained(MODELO).eval()
    (DESTINO / "id2label.json").write_text(
        json.dumps({str(k): v for k, v in modelo.config.id2label.items()}), encoding="utf-8")
    enc = tok("Hola Juan", return_tensors="pt")
    nombres = [k for k in ("input_ids", "attention_mask", "token_type_ids") if k in enc]
    with tempfile.TemporaryDirectory() as tmp:
        fp32, int8 = Path(tmp) / "model_fp32.onnx", Path(tmp) / "model_int8.onnx"
        torch.onnx.export(
            modelo, tuple(enc[k] for k in nombres), str(fp32),
            input_names=nombres, output_names=["logits"],
            dynamic_axes={**{k: {0: "b", 1: "s"} for k in nombres}, "logits": {0: "b", 1: "s"}},
            opset_version=17, dynamo=False)
        quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8)
        dividir(int8.read_bytes())


def dividir(datos: bytes):
    """Parte el modelo en trozos de <= 60 MB: model_int8.onnx.part1, .part2, ..."""
    for viejo in DESTINO.glob("model_int8.onnx.part*"):
        viejo.unlink()
    for i, ini in enumerate(range(0, len(datos), TAMANO_PARTE), start=1):
        (DESTINO / f"model_int8.onnx.part{i}").write_bytes(datos[ini:ini + TAMANO_PARTE])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-tokenizador", action="store_true", help="solo guarda tokenizer.json")
    args = ap.parse_args()
    guardar_tokenizador()
    if not args.solo_tokenizador:
        exportar_y_cuantizar()
