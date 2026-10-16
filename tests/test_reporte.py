from datetime import date

from poc_psico.esquemas import HipotesisRedactada, PruebaSugerida, ReporteClinico
from poc_psico.reporte import render_markdown, validar_hipotesis, validar_pruebas

CANDIDATOS = [
    {
        "codigo": "6A70",
        "titulo": "Trastorno depresivo de episodio único",
        "url": "https://icd.who.int/browse/2024-01/mms/es#1001",
        "definicion": "Episodio depresivo.",
        "inclusiones": [],
        "exclusiones": [],
    }
]
ALTERNATIVAS = [{"codigo": "6A71", "titulo": "Trastorno depresivo recurrente", "url": "https://icd.who.int/browse/2024-01/mms/es#1002"}]
SINTOMAS = {
    "paciente_ref": "[PER_1]", "edad": 34, "sexo": "femenino",
    "cognitivos": ["dificultad para concentrarse"], "emocionales": ["tristeza"], "conductuales": [],
    "afectacion_social": ["faltas al trabajo"], "temporalidad": "4 meses", "datos_faltantes": [],
}


def reporte_base(**extra):
    base = dict(
        hipotesis=[HipotesisRedactada(codigo="6A70", justificacion="Tristeza persistente.", criterios_cumplidos=["Ánimo bajo"], criterios_no_cumplidos=["Duración no confirmada"])],
        ambiguedades=["Podría ser recurrente"],
        diferenciales=["Descartar trastorno bipolar"],
        datos_faltantes=["Antecedentes de episodios previos"],
        pruebas=[PruebaSugerida(nombre="Inventario de Depresión de Beck", motivo="Cuantificar severidad")],
    )
    base.update(extra)
    return ReporteClinico(**base)


def test_validar_descarta_codigos_que_no_vienen_de_las_tools():
    rep = reporte_base(hipotesis=[
        HipotesisRedactada(codigo="6A70", justificacion="ok"),
        HipotesisRedactada(codigo="9Z99", justificacion="inventada"),
    ])
    finales, advertencias = validar_hipotesis(rep, CANDIDATOS)
    assert [h["codigo"] for h in finales] == ["6A70"]
    assert any("9Z99" in a for a in advertencias)


def test_validar_no_duplica_hipotesis():
    rep = reporte_base(hipotesis=[HipotesisRedactada(codigo="6A70", justificacion="a"), HipotesisRedactada(codigo="6A70", justificacion="b")])
    finales, _ = validar_hipotesis(rep, CANDIDATOS)
    assert len(finales) == 1


def test_validar_toma_titulo_y_url_del_candidato_no_del_llm():
    finales, _ = validar_hipotesis(reporte_base(), CANDIDATOS)
    assert finales[0]["titulo"] == "Trastorno depresivo de episodio único"
    assert finales[0]["url"].startswith("https://icd.who.int")
    assert finales[0]["justificacion"] == "Tristeza persistente."


def test_render_incluye_las_siete_secciones_y_codigo_y_liga():
    rep = reporte_base()
    finales, _ = validar_hipotesis(rep, CANDIDATOS)
    md = render_markdown(SINTOMAS, finales, rep, ALTERNATIVAS, date(2026, 10, 15))
    for titulo in ("## 1. Datos del caso", "## 2. Síntomas por categoría", "## 3. Hipótesis diagnósticas",
                   "## 4. Diferenciales y exclusiones", "## 5. Datos faltantes por recabar",
                   "## 6. Pruebas complementarias sugeridas", "## 7. Aviso"):
        assert titulo in md
    assert "`6A70`" in md
    assert "[Abrir en el navegador OMS](https://icd.who.int/browse/2024-01/mms/es#1001)" in md
    assert "[PER_1]" in md and "2026-10-15" in md
    assert "Trastorno depresivo recurrente" in md  # alternativa descartada, con su código


def test_render_marca_categorias_vacias_y_datos_no_indicados():
    sintomas = {**SINTOMAS, "conductuales": [], "edad": None, "sexo": None, "paciente_ref": None}
    rep = reporte_base()
    finales, _ = validar_hipotesis(rep, CANDIDATOS)
    md = render_markdown(sintomas, finales, rep, [], date(2026, 10, 15))
    assert "Ninguno identificado" in md
    assert "No indicada" in md and "No identificado" in md


def test_sintomas_inician_con_mayuscula():
    sintomas = {**SINTOMAS, "emocionales": ["ansiedad en situaciones con mucha gente", "tristeza"]}
    rep = reporte_base()
    finales, _ = validar_hipotesis(rep, CANDIDATOS)
    md = render_markdown(sintomas, finales, rep, [], date(2026, 10, 15))
    assert "- Ansiedad en situaciones con mucha gente" in md
    assert "- Dificultad para concentrarse" in md
    assert "- ansiedad" not in md


def test_pruebas_solo_nombre_y_motivo_con_aviso():
    rep = reporte_base()
    finales, _ = validar_hipotesis(rep, CANDIDATOS)
    md = render_markdown(SINTOMAS, finales, rep, [], date(2026, 10, 15))
    seccion = md.split("## 6. Pruebas complementarias sugeridas")[1].split("## 7.")[0]
    assert "**Inventario de Depresión de Beck**: Cuantificar severidad" in seccion
    assert "a validar por el profesional" in seccion


def test_todos_los_items_del_reporte_inician_en_mayuscula():
    from datetime import date

    from poc_psico.esquemas import ReporteClinico
    from poc_psico.reporte import render_markdown

    reporte = ReporteClinico.model_validate(
        {
            "hipotesis": [],
            "ambiguedades": ["duración poco clara"],
            "diferenciales": ["trastorno de ansiedad"],
            "datos_faltantes": ["edad de inicio"],
            "pruebas": [{"nombre": "inventario de beck", "motivo": "evaluar gravedad"}],
        }
    )
    hip = [{"titulo": "trastorno x", "codigo": "1A", "url": "u", "justificacion": "cumple criterios",
            "criterios_cumplidos": ["ánimo bajo"], "criterios_no_cumplidos": ["duración"]}]
    md = render_markdown({"emocionales": ["tristeza"]}, hip, reporte, [{"titulo": "otro x", "codigo": "2B", "url": "u"}], date(2026, 1, 1))
    for esperado in ["- Duración poco clara", "- Trastorno de ansiedad", "- Edad de inicio", "**Inventario de beck**: Evaluar gravedad",
                     "### 1. Trastorno x", "**Justificación:** Cumple criterios", "- Ánimo bajo", "- Duración", "- Otro x", "- Tristeza"]:
        assert esperado in md


def test_el_reporte_agrupa_las_guias_por_fuente_y_tipo():
    guias = [
        {"titulo": "Guía de evaluación", "url": "https://www.apa.org/e", "cita": "Qué evaluar.", "tipo": "apa"},
        {"titulo": "GPC IMSS", "url": "https://www.imss.gob.mx/g.pdf", "cita": "", "tipo": "imss"},
        {"titulo": "mhGAP", "url": "https://www.who.int/m", "cita": "", "tipo": "oms"},
    ]
    md = render_markdown(SINTOMAS, [], reporte_base(), [], date(2026, 10, 15), guias)
    assert "### Guías clínicas consultadas" in md and "el sistema no recomienda tratamientos" in md
    orden = [md.index(x) for x in ("**IMSS (México)", "[GPC IMSS]", "**APA ·", "[Guía de evaluación]", "**OMS**", "[mhGAP]",
                                   "## 7. Aviso")]
    assert orden == sorted(orden)  # el IMSS va primero


def test_una_guia_sin_tipo_se_muestra_bajo_apa():
    md = render_markdown(SINTOMAS, [], reporte_base(), [], date(2026, 10, 15),
                         [{"titulo": "Guía", "url": "https://www.apa.org/g", "cita": ""}])
    assert md.index("**APA ·") < md.index("[Guía]")


def test_si_solo_hay_un_tipo_no_aparecen_los_otros_encabezados():
    md = render_markdown(SINTOMAS, [], reporte_base(), [], date(2026, 10, 15),
                         [{"titulo": "Guía", "url": "https://www.who.int/g", "cita": "", "tipo": "oms"}])
    assert "**OMS**" in md and "**APA" not in md and "**IMSS" not in md


def test_sin_guias_no_hay_seccion_de_guias():
    assert "Guías clínicas" not in render_markdown(SINTOMAS, [], reporte_base(), [], date(2026, 10, 15))


GUIA_G1 = {"id": "G1", "titulo": "Evaluación de depresión", "url": "https://www.apa.org/e", "cita": "", "tipo": "evaluacion",
           "extracto": "Los instrumentos como el PHQ-9 y el Beck Depression Inventory miden la severidad."}


def prueba(**kw):
    return PruebaSugerida(nombre="PHQ-9", motivo="Medir severidad", **kw)


def test_una_prueba_con_cita_literal_en_el_extracto_queda_respaldada_con_la_liga_de_la_guia():
    validadas, adv = validar_pruebas([prueba(fuente_id="G1", cita_textual="el PHQ-9 y el Beck Depression Inventory")], [GUIA_G1])
    assert validadas[0]["guia"]["url"] == "https://www.apa.org/e" and adv == []


def test_la_cita_se_compara_sin_importar_mayusculas_acentos_ni_espacios():
    validadas, _ = validar_pruebas([prueba(fuente_id="G1", cita_textual="LOS  instrumentos   como el phq-9")], [GUIA_G1])
    assert validadas[0]["guia"] is not None


def test_una_cita_inventada_deja_la_prueba_sin_respaldo_y_avisa():
    validadas, adv = validar_pruebas([prueba(fuente_id="G1", cita_textual="el PHQ-9 cura la depresión")], [GUIA_G1])
    assert validadas[0]["guia"] is None and any("PHQ-9" in a for a in adv)


def test_un_id_inexistente_deja_la_prueba_sin_respaldo_y_avisa():
    validadas, adv = validar_pruebas([prueba(fuente_id="G9", cita_textual="PHQ-9")], [GUIA_G1])
    assert validadas[0]["guia"] is None and adv


def test_una_prueba_sin_fuente_queda_sin_respaldo_sin_advertencia():
    validadas, adv = validar_pruebas([prueba()], [GUIA_G1])
    assert validadas[0]["guia"] is None and adv == []


def test_el_reporte_muestra_la_liga_de_la_prueba_respaldada_y_marca_las_demas():
    pruebas = [prueba(fuente_id="G1", cita_textual="el PHQ-9"), PruebaSugerida(nombre="Escala X", motivo="Otra")]
    rep = reporte_base(pruebas=pruebas)
    md = render_markdown(SINTOMAS, [], rep, [], date(2026, 10, 15), [GUIA_G1])
    lineas = {l for l in md.splitlines() if l.startswith("- **")}
    phq = next(l for l in lineas if "PHQ-9" in l)
    assert "[Evaluación de depresión](https://www.apa.org/e)" in phq and "el PHQ-9" in phq
    assert "sin referencia en las guías consultadas" in next(l for l in lineas if "Escala X" in l)


def test_sin_guias_ninguna_prueba_lleva_la_marca_de_sin_referencia():
    md = render_markdown(SINTOMAS, [], reporte_base(), [], date(2026, 10, 15))
    assert "sin referencia" not in md


def test_con_lista_de_guias_vacia_tampoco_se_marcan_las_pruebas():
    assert "sin referencia" not in render_markdown(SINTOMAS, [], reporte_base(), [], date(2026, 10, 15), [])
