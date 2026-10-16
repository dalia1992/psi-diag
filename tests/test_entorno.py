import os

from poc_psico.entorno import cargar_env


def _aislar_entorno(monkeypatch):
    # dotenv escribe en os.environ; una copia evita que las pruebas contaminen el proceso.
    monkeypatch.setattr(os, "environ", os.environ.copy())


def test_carga_las_variables_del_archivo(tmp_path, monkeypatch):
    _aislar_entorno(monkeypatch)
    monkeypatch.delenv("POC_PRUEBA_CLAVE", raising=False)
    archivo = tmp_path / ".env"
    archivo.write_text("POC_PRUEBA_CLAVE=abc123\n", encoding="utf-8")
    assert cargar_env(archivo) is True
    assert os.environ["POC_PRUEBA_CLAVE"] == "abc123"


def test_no_pisa_una_variable_ya_definida(tmp_path, monkeypatch):
    _aislar_entorno(monkeypatch)
    monkeypatch.setenv("POC_PRUEBA_CLAVE", "del-entorno")
    archivo = tmp_path / ".env"
    archivo.write_text("POC_PRUEBA_CLAVE=del-archivo\n", encoding="utf-8")
    assert cargar_env(archivo) is True
    assert os.environ["POC_PRUEBA_CLAVE"] == "del-entorno"


def test_sin_archivo_devuelve_false_y_no_falla(tmp_path):
    assert cargar_env(tmp_path / "no-existe.env") is False


def test_usa_poc_env_file_si_no_se_pasa_ruta(tmp_path, monkeypatch):
    _aislar_entorno(monkeypatch)
    monkeypatch.delenv("POC_PRUEBA_CLAVE", raising=False)
    archivo = tmp_path / "claves.env"
    archivo.write_text("POC_PRUEBA_CLAVE=desde-poc-env-file\n", encoding="utf-8")
    monkeypatch.setenv("POC_ENV_FILE", str(archivo))
    assert cargar_env() is True
    assert os.environ["POC_PRUEBA_CLAVE"] == "desde-poc-env-file"
