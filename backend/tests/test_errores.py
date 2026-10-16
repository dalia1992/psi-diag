import pytest

from psi_diag.errores import FlujoDetenido


def test_flujo_detenido_es_excepcion_con_mensaje():
    with pytest.raises(FlujoDetenido, match="sin conexión"):
        raise FlujoDetenido("sin conexión")
