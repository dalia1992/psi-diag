from psi_diag.pii import (
    MapaPII,
    anonimizar,
    aplicar_entidades,
    extender_a_palabra,
    fusionar_entidades,
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


def test_fusiona_fragmentos_contiguos():
    t = "Cochabamba"
    ents = [{"entity_group": "LOC", "start": 0, "end": 2}, {"entity_group": "LOC", "start": 2, "end": 10}]
    assert aplicar_entidades(t, ents, MapaPII()) == "[LOC_1]"
    assert fusionar_entidades(ents) == [{"entity_group": "LOC", "start": 0, "end": 10}]


def test_extiende_a_la_palabra():
    t = "Paciente LUCIA HERNANDEZ, 29"
    ents = [ent(t, "CIA HERNANDEZ", "PER")]
    assert aplicar_entidades(t, ents, MapaPII()) == "Paciente [PER_1], 29"


def test_fusiona_fragmento_de_palabra_con_el_resto_del_nombre():
    t = "Paciente LUCIA HERNANDEZ, 29"
    ents = [ent(t, "LU", "PER"), ent(t, "CIA HERNANDEZ", "PER")]
    assert aplicar_entidades(t, ents, MapaPII()) == "Paciente [PER_1], 29"


def test_no_funde_tipos_distintos():
    ents = [{"entity_group": "PER", "start": 0, "end": 3}, {"entity_group": "LOC", "start": 3, "end": 8}]
    assert len(fusionar_entidades(ents)) == 2


def test_conserva_comportamiento_previo():
    t = "Ana y Luis viven en Lima."
    ents = [ent(t, "Ana", "PER"), ent(t, "Luis", "PER"), ent(t, "Lima", "LOC")]
    assert aplicar_entidades(t, ents, MapaPII()) == "[PER_1] y [PER_2] viven en [LOC_1]."


def test_extender_a_palabra_con_acentos_y_enie():
    t = "Señora Muñoz-Ávila"
    assert extender_a_palabra(t, 9, 11) == (7, 18)   # el guion entre letras une el apellido compuesto
    assert extender_a_palabra("ab cd", 1, 4) == (0, 5)


def test_reinsertar_datos_recorre_estructuras_anidadas():
    mapa = MapaPII()
    ph = mapa.asignar("PER", "Laura Mendoza")
    obj = {"a": f"Paciente {ph}", "b": [f"{ph} y [PER_9]", {"c": [f"{ph}"]}], "n": 34, "v": None, "t": (f"{ph}",)}
    nuevo, desconocidos = mapa.reinsertar_datos(obj)
    assert nuevo == {"a": "Paciente Laura Mendoza", "b": ["Laura Mendoza y [PER_9]", {"c": ["Laura Mendoza"]}], "n": 34, "v": None,
                     "t": ["Laura Mendoza"]}
    assert desconocidos == ["[PER_9]"]
    assert obj["a"] == f"Paciente {ph}"  # no muta el original


def test_apellido_con_guion_se_cubre_completo_aunque_el_ner_solo_vea_una_parte():
    t = "La paciente Ana Muñoz-Ávila llegó tarde."
    for parte in ("Muñoz", "Ávila"):
        mapa = MapaPII()
        salida = aplicar_entidades(t, [ent(t, parte, "PER")], mapa)
        assert salida == "La paciente Ana [PER_1] llegó tarde."
        assert list(mapa.valores().values()) == ["Muñoz-Ávila"]


def test_apellido_con_apostrofo_se_cubre_completo_con_ambos_tipos_de_apostrofo():
    for apostrofo in ("'", "’"):
        t = f"El señor O{apostrofo}Brien llegó."
        for parte in ("O", "Brien"):
            mapa = MapaPII()
            salida = aplicar_entidades(t, [ent(t, parte, "PER")], mapa)
            assert salida == "El señor [PER_1] llegó."
            assert list(mapa.valores().values()) == [f"O{apostrofo}Brien"]


def test_guion_y_apostrofo_fuera_de_una_palabra_no_se_incluyen():
    t = "Dijo 'Ana' y luego - Ana - se fue; Ana- nada."
    mapa = MapaPII()
    ents = [ent(t, "Ana", "PER"), ent(t, "Ana", "PER", desde=15), ent(t, "Ana", "PER", desde=30)]
    salida = aplicar_entidades(t, ents, mapa)
    assert salida == "Dijo '[PER_1]' y luego - [PER_1] - se fue; [PER_1]- nada."


def test_extender_a_palabra_no_cambia_una_frase_normal():
    t = "Ana habló con María en la casa."
    assert extender_a_palabra(t, 0, 3) == (0, 3)
    assert extender_a_palabra(t, 10, 13) == (10, 13)
    assert extender_a_palabra(t, 11, 13) == (10, 13)   # parte de una palabra sin signos: igual que antes
