"""Las rutas de datos se resuelven desde el código (no desde el directorio actual) y apuntan a lo que existe."""
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def test_componentes_se_importa_desde_backend_src():
    import componentes
    assert Path(componentes.__file__).resolve() == RAIZ / "backend" / "src" / "componentes.py"


def test_directorio_del_modelo_ner_existe_con_sus_partes():
    import componentes
    d = componentes.DIRECTORIO_NER
    assert d == RAIZ / "backend" / "models" / "ner"
    assert d.is_dir()
    assert (d / "model_int8.onnx.part1").is_file() and (d / "model_int8.onnx.part2").is_file()
    assert (d / "tokenizer.json").is_file() and (d / "id2label.json").is_file()


def test_pdf_encuentra_las_fuentes_nunito():
    from exportar import pdf
    assert pdf.FUENTES == RAIZ / "backend" / "assets" / "fonts"
    for nombre in ("Nunito-Regular.ttf", "Nunito-SemiBold.ttf", "Nunito-Bold.ttf"):
        assert (pdf.FUENTES / nombre).is_file(), nombre


def test_servidor_apunta_a_public_y_a_la_fixture_demo():
    import servidor
    assert servidor.RAIZ == RAIZ
    assert (RAIZ / "public" / "index.html").is_file()
    assert servidor.FIXTURE_DEMO.is_file()


def test_shim_de_la_raiz_expone_la_misma_app(tmp_path):
    """`app.py` de la raíz funciona aunque se lance desde otro directorio."""
    codigo = "import sys; sys.path.insert(0, sys.argv[1]); import app, servidor; assert app.app is servidor.app"
    r = subprocess.run([sys.executable, "-c", codigo, str(RAIZ)], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
