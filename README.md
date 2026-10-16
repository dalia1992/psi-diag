# MVP psicodiagnóstico

Apoyo al psicodiagnóstico (fase 1): backend FastAPI reutilizando el PoC `poc_psico/`, desplegable en Vercel.
Para correr las pruebas: `uv pip install -r requirements-dev.txt && pytest -q` (copia `.env.example` a `.env` para uso local; nunca subas `.env`).

## NER de anonimización (ONNX)

`poc_psico/ner_onnx.py` ejecuta `mrm8488/bert-spanish-cased-finetuned-ner` (int8, ~110 MB) con onnxruntime, sin torch.
El modelo se versiona partido en `models/ner/model_int8.onnx.part1`/`.part2` (GitHub rechaza archivos > 100 MB) y se
reensambla en memoria; se regenera con `scripts/exportar_ner_onnx.py`. Los textos largos se procesan por trozos de 1000 caracteres.

**Límite conocido:** el modelo distingue mayúsculas. `con_pasada_auxiliar` repite el NER con las palabras en formato "Título"
(acepta solo PER/LOC) y cubre nombres en MAYÚSCULAS o minúsculas de los casos de prueba (23/23), pero un nombre en minúsculas
sin contexto claro (p. ej. un apodo solo) aún puede escapar. Por eso el texto anonimizado debe seguir revisándose antes de enviarse a un LLM externo.
