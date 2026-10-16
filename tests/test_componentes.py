import componentes


def test_sin_app_url_no_se_manda_http_referer(monkeypatch):
    monkeypatch.delenv("APP_URL", raising=False)
    cabeceras = componentes.cabeceras_openrouter()
    assert "HTTP-Referer" not in cabeceras and cabeceras["X-Title"] == "MVP Psicodiagnostico"


def test_con_app_url_se_manda_como_http_referer(monkeypatch):
    monkeypatch.setenv("APP_URL", " https://mi-app.example ")
    assert componentes.cabeceras_openrouter()["HTTP-Referer"] == "https://mi-app.example"


def test_app_url_vacia_se_trata_como_ausente(monkeypatch):
    monkeypatch.setenv("APP_URL", "   ")
    assert "HTTP-Referer" not in componentes.cabeceras_openrouter()


def test_no_queda_ninguna_url_de_despliegue_fija():
    assert "mvp-psicodiagnostico.vercel.app" not in open(componentes.__file__, encoding="utf-8").read()
