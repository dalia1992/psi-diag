from poc_psico.pii import (
    MapaPII,
    anonimizar,
    aplicar_entidades,
    ocultar_cedulas,
    ocultar_correos,
    ocultar_fechas,
    ocultar_telefonos,
)


def ent(texto, fragmento, tipo, desde=0, margen=0):
    ini = texto.index(fragmento, desde)
    return {"entity_group": tipo, "start": ini - margen, "end": ini + len(fragmento), "word": fragmento}


def test_reemplaza_persona_lugar_y_organizacion():
    t = "Laura Mendoza vive en Guadalajara y trabaja en Banco Andino."
    ents = [ent(t, "Laura Mendoza", "PER"), ent(t, "Guadalajara", "LOC"), ent(t, "Banco Andino", "ORG")]
    mapa = MapaPII()
    assert aplicar_entidades(t, ents, mapa) == "[PER_1] vive en [LOC_1] y trabaja en [ORG_1]."
    assert mapa.valores() == {"[PER_1]": "Laura Mendoza", "[LOC_1]": "Guadalajara", "[ORG_1]": "Banco Andino"}


def test_misma_persona_con_nombre_completo_y_de_pila_comparte_placeholder():
    t = "Ana Torres llegó. Luego Ana habló."
    ents = [ent(t, "Ana Torres", "PER"), ent(t, "Ana", "PER", desde=11)]
    mapa = MapaPII()
    assert aplicar_entidades(t, ents, mapa) == "[PER_1] llegó. Luego [PER_1] habló."
    assert mapa.valores() == {"[PER_1]": "Ana Torres"}


def test_conserva_el_valor_mas_completo_aunque_aparezca_despues():
    t = "Ana habló. Ana Torres llegó."
    ents = [ent(t, "Ana", "PER"), ent(t, "Ana Torres", "PER", desde=5)]
    mapa = MapaPII()
    assert aplicar_entidades(t, ents, mapa) == "[PER_1] habló. [PER_1] llegó."
    assert mapa.valores()["[PER_1]"] == "Ana Torres"


def test_personas_distintas_tienen_placeholders_distintos():
    t = "Ana Torres y Luis Pérez"
    ents = [ent(t, "Ana Torres", "PER"), ent(t, "Luis Pérez", "PER")]
    assert aplicar_entidades(t, ents, MapaPII()) == "[PER_1] y [PER_2]"


def test_ignora_misc_y_entidades_sin_tipo_conocido():
    t = "El Quijote lo leyó Ana"
    ents = [ent(t, "Quijote", "MISC"), ent(t, "Ana", "PER")]
    assert aplicar_entidades(t, ents, MapaPII()) == "El Quijote lo leyó [PER_1]"


def test_entidad_con_espacio_inicial_no_deja_residuos():
    t = "Vive con Marta ahora"
    ents = [ent(t, "Marta", "PER", margen=1)]  # HF a veces incluye el espacio previo
    assert aplicar_entidades(t, ents, MapaPII()) == "Vive con [PER_1] ahora"


def test_entidades_solapadas_conserva_la_primera():
    t = "Clínica San Rafael"
    ents = [ent(t, "Clínica San Rafael", "ORG"), ent(t, "San Rafael", "LOC")]
    assert aplicar_entidades(t, ents, MapaPII()) == "[ORG_1]"


def test_sin_entidades_no_cambia_el_texto():
    assert aplicar_entidades("Texto sin nombres", [], MapaPII()) == "Texto sin nombres"


def test_reinsertar_reemplaza_y_reporta_placeholders_desconocidos():
    mapa = MapaPII()
    mapa.asignar("PER", "Laura Mendoza")
    texto, desconocidos = mapa.reinsertar("Paciente [PER_1] y familiar [PER_9].")
    assert texto == "Paciente Laura Mendoza y familiar [PER_9]."
    assert desconocidos == ["[PER_9]"]


def test_reinsertar_texto_sin_placeholders():
    assert MapaPII().reinsertar("Nada que cambiar") == ("Nada que cambiar", [])


def test_fechas_exactas_se_ocultan():
    assert ocultar_fechas("nació el 14/05/1978 y el 12 de mayo de 2026") == "nació el [FECHA] y el [FECHA]"


def test_fechas_relativas_y_cifras_clinicas_se_conservan():
    t = "hace 3 semanas, 34 años, 20 mg, desde marzo, 2 veces por día"
    assert ocultar_fechas(t) == t
    assert ocultar_telefonos(t) == t
    assert ocultar_cedulas(t) == t


def test_telefonos():
    assert ocultar_telefonos("Teléfono 33-1234-5678 o 5551234567") == "Teléfono [TEL] o [TEL]"


def test_cedulas():
    assert ocultar_cedulas("Cédula Prof. 4589213 vigente") == "[ID] vigente"


def test_correos():
    assert ocultar_correos("escribe a mfernandagp@correo.mx hoy") == "escribe a [CORREO] hoy"


def test_anonimizar_completo_conserva_edad_y_sexo():
    t = "Laura Mendoza, mujer de 34 años, vive en Guadalajara. Tel 33-1234-5678."
    ner = lambda texto: [ent(texto, "Laura Mendoza", "PER"), ent(texto, "Guadalajara", "LOC")]
    mapa = MapaPII()
    salida = anonimizar(t, ner, mapa)
    assert salida == "[PER_1], mujer de 34 años, vive en [LOC_1]. Tel [TEL]."
    assert "Laura" not in salida and "Guadalajara" not in salida
