import pytest

from poc_psico.reintentos import acon_reintentos_503, con_reintentos_503, es_503


class Error503(Exception):
    status_code = 503


class ErrorConRespuesta(Exception):
    def __init__(self, estado):
        super().__init__("falla del servidor")
        self.response = type("R", (), {"status_code": estado})()


def test_es_503_reconoce_el_codigo_en_el_error_en_la_respuesta_y_en_el_texto():
    assert es_503(Error503("overloaded"))
    assert es_503(ErrorConRespuesta(503))
    assert es_503(RuntimeError("Error code: 503 - {'error': 'system overload'}"))


def test_es_503_no_confunde_otros_errores():
    assert not es_503(ErrorConRespuesta(429))
    assert not es_503(RuntimeError("se procesaron 1503 tokens"))
    assert not es_503(ValueError("otra cosa"))


def _funcion_que_falla(veces, error=Error503):
    llamadas = []

    def funcion(*args, **kwargs):
        llamadas.append((args, kwargs))
        if len(llamadas) <= veces:
            raise error("overloaded")
        return "listo"

    return funcion, llamadas


def test_reintenta_dos_veces_y_espera_1_y_2_segundos():
    funcion, llamadas = _funcion_que_falla(2)
    esperas = []
    assert con_reintentos_503(funcion, "a", clave=1, esperar=esperas.append) == "listo"
    assert esperas == [1, 2]
    assert llamadas == [(("a",), {"clave": 1})] * 3


def test_si_el_503_persiste_hace_3_reintentos_con_1_2_y_4_segundos_y_lanza_el_error():
    funcion, llamadas = _funcion_que_falla(99)
    esperas = []
    with pytest.raises(Error503):
        con_reintentos_503(funcion, esperar=esperas.append)
    assert esperas == [1, 2, 4]
    assert len(llamadas) == 4  # el intento original y 3 reintentos


def test_un_error_que_no_es_503_no_se_reintenta():
    funcion, llamadas = _funcion_que_falla(99, error=ValueError)
    esperas = []
    with pytest.raises(ValueError):
        con_reintentos_503(funcion, esperar=esperas.append)
    assert esperas == [] and len(llamadas) == 1


def test_sin_error_no_espera():
    funcion, _ = _funcion_que_falla(0)
    esperas = []
    assert con_reintentos_503(funcion, esperar=esperas.append) == "listo"
    assert esperas == []


async def test_version_asincrona_con_503_persistente():
    llamadas, esperas = [], []

    async def funcion():
        llamadas.append(1)
        raise Error503("overloaded")

    async def esperar(segundos):
        esperas.append(segundos)

    with pytest.raises(Error503):
        await acon_reintentos_503(funcion, aesperar=esperar)
    assert esperas == [1, 2, 4] and len(llamadas) == 4


async def test_version_asincrona_se_recupera():
    estado = {"n": 0}
    esperas = []

    async def funcion():
        estado["n"] += 1
        if estado["n"] < 3:
            raise Error503("overloaded")
        return "listo"

    async def esperar(segundos):
        esperas.append(segundos)

    assert await acon_reintentos_503(funcion, aesperar=esperar) == "listo"
    assert esperas == [1, 2]


def test_reintenta_si_el_formato_es_invalido():
    from pydantic import BaseModel, ValidationError

    from poc_psico.reintentos import con_reintentos_formato

    class M(BaseModel):
        x: list[str]

    llamadas = []

    def f():
        llamadas.append(1)
        if len(llamadas) < 3:
            return M(x="no es lista")
        return M(x=["ok"])

    assert con_reintentos_formato(f).x == ["ok"]
    assert len(llamadas) == 3


def test_formato_invalido_persistente_se_propaga():
    import pytest
    from pydantic import BaseModel, ValidationError

    from poc_psico.reintentos import con_reintentos_formato

    class M(BaseModel):
        x: list[str]

    with pytest.raises(ValidationError):
        con_reintentos_formato(lambda: M(x="mal"))
