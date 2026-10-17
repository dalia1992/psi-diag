"""Reporte en Word: Arial 12 pt, interlineado 1.5, títulos en azul sobrio. El nombre de la app va en texto simple."""
import io
from datetime import datetime, timezone

from docx import Document
from docx.enum.text import WD_UNDERLINE
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from . import comun
from .comun import dicc, lista, lista_de_dicts, mayuscula_inicial, texto, url_segura

AZUL = RGBColor(0x2F, 0x4B, 0x7C)
FUENTE = "Arial"
NINGUNO = "Ninguno indicado"


def _fuente(estilo, tamano, negrita=False, color=None) -> None:
    estilo.font.name = FUENTE
    estilo.font.size = Pt(tamano)
    estilo.font.bold = negrita
    if color is not None:
        estilo.font.color.rgb = color
    propiedades = estilo.element.get_or_add_rPr()
    fuentes = propiedades.find(qn("w:rFonts"))
    if fuentes is None:
        fuentes = OxmlElement("w:rFonts")
        propiedades.insert(0, fuentes)
    for atributo in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fuentes.set(qn(atributo), FUENTE)
    for atributo in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):   # el tema pisaría a Arial
        if fuentes.get(qn(atributo)) is not None:
            del fuentes.attrib[qn(atributo)]


def _estilos(documento) -> None:
    normal = documento.styles["Normal"]
    _fuente(normal, 12)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(4)
    for nombre, tamano in (("Title", 22), ("Subtitle", 14), ("Heading 1", 16), ("Heading 2", 14), ("Heading 3", 12)):
        _fuente(documento.styles[nombre], tamano, negrita=True, color=AZUL)
        documento.styles[nombre].paragraph_format.line_spacing = 1.5
    _fuente(documento.styles["List Bullet"], 12)
    documento.styles["List Bullet"].paragraph_format.line_spacing = 1.5


def _corrida_de_campo(tipo: str, sucio: bool = False):
    corrida, marca = OxmlElement("w:r"), OxmlElement("w:fldChar")
    marca.set(qn("w:fldCharType"), tipo)
    if sucio:   # Word recalcula el campo (números de página incluidos) al abrir el archivo, sin preguntar
        marca.set(qn("w:dirty"), "true")
    corrida.append(marca)
    return corrida


def _marcar(parrafo, numero: int) -> str:
    """Marcador oculto (_Toc…) que abarca el título: es el destino de la liga del índice."""
    nombre = f"_Toc{100000 + numero}"
    inicio, fin = OxmlElement("w:bookmarkStart"), OxmlElement("w:bookmarkEnd")
    inicio.set(qn("w:id"), str(numero))
    inicio.set(qn("w:name"), nombre)
    fin.set(qn("w:id"), str(numero))
    propiedades = parrafo._p.pPr
    parrafo._p.insert(0 if propiedades is None else 1, inicio)
    parrafo._p.append(fin)
    return nombre


def _insertar_indice(documento, ancla, entradas: list) -> None:
    """Índice como campo TOC de Word (títulos 1 y 2) justo después de `ancla`. Se rellena con los títulos, ligados a sus marcadores,
    para que se vea y navegue aunque el visor no recalcule campos; Word lo actualiza con los números de página al abrir."""
    parrafos = []
    for i, (nivel, titulo, marcador) in enumerate(entradas):
        parrafo = documento.add_paragraph()
        parrafo.paragraph_format.line_spacing = 1.15
        parrafo.paragraph_format.space_after = Pt(2)
        if nivel > 1:
            parrafo.paragraph_format.left_indent = Pt(20)
        if i == 0:
            instruccion = OxmlElement("w:r")
            texto_instruccion = OxmlElement("w:instrText")
            texto_instruccion.set(qn("xml:space"), "preserve")
            texto_instruccion.text = ' TOC \\o "1-2" \\h \\z \\u '
            instruccion.append(texto_instruccion)
            for hijo in (_corrida_de_campo("begin", sucio=True), instruccion, _corrida_de_campo("separate")):
                parrafo._p.append(hijo)
        enlace = OxmlElement("w:hyperlink")
        enlace.set(qn("w:anchor"), marcador)
        enlace.set(qn("w:history"), "1")
        corrida = parrafo.add_run(titulo)
        corrida.font.color.rgb = AZUL
        enlace.append(corrida._r)
        parrafo._p.append(enlace)
        if i == len(entradas) - 1:
            parrafo._p.append(_corrida_de_campo("end"))
        parrafos.append(parrafo)
    for parrafo in reversed(parrafos):
        ancla._p.addnext(parrafo._p)


def _liga(parrafo, url: str, etiqueta: str) -> None:
    relacion = parrafo.part.relate_to(url, RT.HYPERLINK, is_external=True)
    enlace = OxmlElement("w:hyperlink")
    enlace.set(qn("r:id"), relacion)
    corrida = parrafo.add_run(etiqueta)
    corrida.font.color.rgb = AZUL
    corrida.font.underline = WD_UNDERLINE.SINGLE
    enlace.append(corrida._r)
    parrafo._p.append(enlace)


def _vinetas(documento, items, vacio=None) -> None:
    items = lista(items)
    for item in items:
        documento.add_paragraph(mayuscula_inicial(item), style="List Bullet")
    if not items and vacio:
        documento.add_paragraph(vacio, style="List Bullet")


def _nota(documento, contenido: str) -> None:
    documento.add_paragraph().add_run(contenido).italic = True


def _con_liga(documento, etiqueta: str, url: str, resto: str = "", estilo: str | None = None, prefijo: str = "") -> None:
    parrafo = documento.add_paragraph(prefijo, style=estilo)
    liga = url_segura(url)
    if liga:
        _liga(parrafo, liga, etiqueta)
    else:
        parrafo.add_run(etiqueta)
    if resto:
        parrafo.add_run(resto)


def _negrita_y_texto(documento, rotulo: str, contenido: str) -> None:
    parrafo = documento.add_paragraph()
    parrafo.add_run(f"{rotulo} ").bold = True
    parrafo.add_run(contenido)


def generar_docx(reporte: dict) -> bytes:
    reporte = dicc(reporte)
    documento = Document()
    propiedades = documento.core_properties   # sin esto quedan los datos de la plantilla de python-docx
    propiedades.title = "Reporte de apoyo al psicodiagnóstico"
    propiedades.author = propiedades.last_modified_by = comun.NOMBRE_APP
    propiedades.created = propiedades.modified = datetime.now(timezone.utc).replace(microsecond=0)
    _estilos(documento)
    for seccion in documento.sections:
        seccion.left_margin = seccion.right_margin = Pt(72)

    documento.add_paragraph(comun.NOMBRE_APP, style="Title")
    documento.add_paragraph("Reporte de apoyo al psicodiagnóstico", style="Subtitle")   # no es título 1 ni 2: no entra al índice
    ancla_indice = documento.add_paragraph()
    ancla_indice.add_run("Índice").bold = True
    ancla_indice.runs[0].font.size = Pt(14)
    ancla_indice.runs[0].font.color.rgb = AZUL
    entradas: list = []

    def encabezado(titulo: str, nivel: int) -> None:
        parrafo = documento.add_heading(titulo, level=nivel)
        if nivel <= 2:
            entradas.append((nivel, titulo, _marcar(parrafo, len(entradas) + 1)))

    encabezado("1. Datos del caso", 1)
    for rotulo, valor in comun.datos_del_caso(reporte):
        _negrita_y_texto(documento, f"{rotulo}:", valor)

    encabezado("2. Síntomas por categoría", 1)
    sintomas = dicc(reporte.get("sintomas"))
    for etiqueta, clave in comun.ETIQUETAS_SINTOMAS:
        encabezado(etiqueta, 3)   # categorías de síntomas: no van al índice
        _vinetas(documento, sintomas.get(clave), "Ninguno identificado")

    encabezado("3. Enfermedades conocidas y medicación", 1)
    antecedentes = dicc(reporte.get("antecedentes_medicos"))
    for etiqueta, clave in comun.ETIQUETAS_ANTECEDENTES:
        encabezado(etiqueta, 3)
        _vinetas(documento, antecedentes.get(clave), NINGUNO)

    encabezado("4. Hipótesis diagnósticas (de la más a la menos plausible)", 1)
    hipotesis = lista_de_dicts(reporte.get("hipotesis"))
    for i, h in enumerate(hipotesis, 1):
        encabezado(f"{i}. {mayuscula_inicial(h.get('titulo')) or 'Sin título'} — {texto(h.get('codigo')) or 'sin código'}", 2)
        _con_liga(documento, "Abrir en el navegador OMS", h.get("url"))
        _negrita_y_texto(documento, "Justificación:", mayuscula_inicial(h.get("justificacion")) or "No indicada")
        documento.add_paragraph().add_run("Criterios cumplidos:").bold = True
        _vinetas(documento, h.get("criterios_cumplidos"), NINGUNO)
        documento.add_paragraph().add_run("Criterios no cumplidos o sin confirmar:").bold = True
        _vinetas(documento, h.get("criterios_no_cumplidos"), NINGUNO)
    if not hipotesis:
        documento.add_paragraph("Sin hipótesis diagnósticas.")
    if lista(reporte.get("ambiguedades")):
        encabezado("Ambigüedades", 2)
        _vinetas(documento, reporte.get("ambiguedades"))

    encabezado("5. Diferenciales y exclusiones", 1)
    _vinetas(documento, reporte.get("diferenciales"), NINGUNO)
    alternativas = lista_de_dicts(reporte.get("alternativas"))
    if alternativas:
        encabezado("Alternativas consultadas y descartadas", 2)
        for a in alternativas:
            _con_liga(documento, "OMS", a.get("url"), "", "List Bullet",
                      f"{mayuscula_inicial(a.get('titulo')) or 'Sin título'} ({texto(a.get('codigo')) or 'sin código'}) — ")

    encabezado("6. Datos faltantes por recabar", 1)
    _vinetas(documento, reporte.get("datos_faltantes"), NINGUNO)

    encabezado("7. Pruebas complementarias sugeridas", 1)
    _nota(documento, "Sugerencias a validar por el profesional. Solo se indica el nombre de la prueba: "
                     "no se incluyen cuestionarios ni formas de calificación.")
    guias = lista_de_dicts(reporte.get("guias"))
    pruebas = lista_de_dicts(reporte.get("pruebas"))
    for p in pruebas:
        parrafo = documento.add_paragraph(style="List Bullet")
        parrafo.add_run(mayuscula_inicial(p.get("nombre")) or "Prueba sin nombre").bold = True
        motivo = mayuscula_inicial(p.get("motivo"))
        if motivo:
            parrafo.add_run(f": {motivo}")
        guia = dicc(p.get("guia"))
        if guia:
            parrafo.add_run(" · Referencia: ")
            titulo, liga = texto(guia.get("titulo")) or "Guía", url_segura(guia.get("url"))
            _liga(parrafo, liga, titulo) if liga else parrafo.add_run(titulo)
            if texto(p.get("cita")):
                parrafo.add_run(f" — «{texto(p.get('cita'))}»")
        elif guias:
            parrafo.add_run(" · (sin referencia en las guías consultadas)").italic = True
    if not pruebas:
        documento.add_paragraph("Ninguna sugerida", style="List Bullet")

    if guias:
        encabezado("Guías clínicas consultadas", 2)
        _nota(documento, "Referencias para consulta del profesional; el sistema no recomienda tratamientos.")
        etiquetas = list(dict.fromkeys(texto(g.get("etiqueta")) or texto(g.get("tipo")) or "Otras" for g in guias))
        for etiqueta in etiquetas:
            documento.add_paragraph().add_run(etiqueta).bold = True
            for g in guias:
                if (texto(g.get("etiqueta")) or texto(g.get("tipo")) or "Otras") != etiqueta:
                    continue
                cita = texto(g.get("cita"))
                _con_liga(documento, texto(g.get("titulo")) or "Guía", g.get("url"), f" — «{cita}»" if cita else "", "List Bullet")

    numero = 8
    conclusion = texto(reporte.get("conclusion"))
    if conclusion:
        encabezado(f"{numero}. Conclusión, recomendaciones y siguientes pasos", 1)
        for parrafo in comun.parrafos(conclusion):
            documento.add_paragraph(parrafo)
        numero += 1
    encabezado(f"{numero}. Aviso", 1)
    documento.add_paragraph(texto(reporte.get("aviso")))
    _insertar_indice(documento, ancla_indice, entradas)
    salida = io.BytesIO()
    documento.save(salida)
    return salida.getvalue()

