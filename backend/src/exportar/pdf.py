"""Reporte en PDF con reportlab: Nunito incrustada, paleta B, encabezado con el nombre de la app y pie con «Página X de Y».

Nunito no trae la Ψ (U+03A8): en el encabezado se dibuja como trazo vectorial."""
import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily, stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from reportlab.platypus.tableofcontents import TableOfContents

from . import comun
from .comun import dicc, lista, lista_de_dicts, mayuscula_inicial, texto, url_segura

FUENTES = Path(__file__).resolve().parents[2] / "assets" / "fonts"
AZUL, LAVANDA, MENTA, FONDO, TEXTO = (HexColor(c) for c in (comun.AZUL, comun.LAVANDA, comun.MENTA, comun.FONDO, "#26304A"))
NINGUNO = "Ninguno indicado"
REGULAR, SEMI, NEGRITA = "Nunito", "Nunito-SemiBold", "Nunito-Bold"


def _registrar_fuentes() -> None:
    if REGULAR in pdfmetrics.getRegisteredFontNames():
        return
    for nombre, archivo in ((REGULAR, "Nunito-Regular"), (SEMI, "Nunito-SemiBold"), (NEGRITA, "Nunito-Bold")):
        pdfmetrics.registerFont(TTFont(nombre, str(FUENTES / f"{archivo}.ttf")))
    registerFontFamily(REGULAR, normal=REGULAR, bold=NEGRITA, italic=REGULAR, boldItalic=NEGRITA)


def _t(valor) -> str:
    """Texto seguro para el marcado de Paragraph: se escapa y los caracteres que Nunito no trae (emojis, etc.) pasan a «?»."""
    glifos = pdfmetrics.getFont(REGULAR).face.charToGlyph
    limpio = "".join(c if c in "\n" or ord(c) in glifos else "?" for c in texto(valor))
    return escape(limpio).replace("\n", "<br/>")


def _liga(url, etiqueta: str) -> str:
    destino = url_segura(url)
    if not destino:
        return _t(etiqueta)
    return f'<a href="{escape(destino, {chr(34): "&quot;"})}" color="{comun.AZUL}"><u>{_t(etiqueta)}</u></a>'


def _estilos() -> dict:
    base = dict(fontName=REGULAR, bulletFontName=REGULAR, fontSize=10.5, leading=15.5, textColor=TEXTO, alignment=TA_LEFT, splitLongWords=1, wordWrap="CJK")
    return {
        "cuerpo": ParagraphStyle("cuerpo", spaceAfter=4, **base),
        "titulo": ParagraphStyle("titulo", **{**base, "fontName": NEGRITA, "fontSize": 20, "leading": 25, "textColor": AZUL}, spaceAfter=2),
        "sub": ParagraphStyle("sub", **{**base, "fontSize": 11.5, "textColor": LAVANDA, "fontName": SEMI}, spaceAfter=8),
        "h1": ParagraphStyle("h1", **{**base, "fontName": NEGRITA, "fontSize": 14, "leading": 18, "textColor": AZUL}, spaceBefore=14, spaceAfter=3, keepWithNext=1),
        "h2": ParagraphStyle("h2", **{**base, "fontName": SEMI, "fontSize": 11.5, "leading": 16, "textColor": AZUL}, spaceBefore=8, spaceAfter=2, keepWithNext=1),
        "indice_titulo": ParagraphStyle("indice_titulo", **{**base, "fontName": NEGRITA, "fontSize": 14, "leading": 18, "textColor": AZUL}, spaceBefore=6, spaceAfter=4),
        "indice1": ParagraphStyle("indice1", **{**base, "fontName": SEMI}, leftIndent=0, spaceBefore=3, spaceAfter=1),
        "indice2": ParagraphStyle("indice2", **{**base, "fontSize": 9.5, "leading": 13.5}, leftIndent=14, spaceAfter=0),
        "vineta": ParagraphStyle("vineta", **base, leftIndent=14, bulletIndent=3, spaceAfter=2),
        "nota": ParagraphStyle("nota", **{**base, "fontSize": 9.5, "leading": 13.5, "textColor": HexColor("#5A6480")}, spaceAfter=4),
        "aviso": ParagraphStyle("aviso", **base, backColor=FONDO, borderColor=MENTA, borderWidth=0.8, borderPadding=(8, 9, 8, 9),
                                spaceBefore=6, spaceAfter=6),
    }


class _LienzoNumerado(Canvas):
    """Dibuja encabezado y pie al final, cuando ya se conoce el total de páginas."""

    def __init__(self, *args, **kwargs):
        kwargs["initialFontName"] = REGULAR   # sin esto cada página declara Helvetica sin usarla
        super().__init__(*args, **kwargs)
        self._estados: list[dict] = []
        self._marcas: list[tuple] = []   # marcadores y entradas del panel lateral, con la página en que se pidieron

    def showPage(self):
        self._estados.append(dict(self.__dict__))
        self._startPage()

    # Las páginas se cierran todas al final (para saber el total), y un marcador pedido antes apuntaría siempre a la primera:
    # se anotan con su página y se registran en `save`, cuando cada página ya es la vigente.
    def bookmarkPage(self, key, *args, **kwargs):
        self._marcas.append((len(self._estados), "marcador", key, args, kwargs))

    def addOutlineEntry(self, title, key, level=0, closed=None):
        self._marcas.append((len(self._estados), "entrada", (title, key, level, closed), (), {}))

    def save(self):
        total = len(self._estados)
        for pagina, estado in enumerate(self._estados):
            self.__dict__.update(estado)
            for donde, tipo, dato, args, kwargs in self._marcas:
                if donde != pagina:
                    continue
                if tipo == "marcador":
                    super().bookmarkPage(dato, *args, **kwargs)
                else:
                    titulo, clave, nivel, cerrado = dato
                    super().addOutlineEntry(titulo, clave, nivel, cerrado)
            self._decorar(total)
            super().showPage()
        super().save()

    def _decorar(self, total: int) -> None:
        ancho, alto = A4
        izq, der = 2 * cm, ancho - 2 * cm
        self.saveState()
        self._nombre_app(izq, alto - 1.5 * cm)
        self.setStrokeColor(LAVANDA)
        self.setLineWidth(0.8)
        self.line(izq, alto - 1.95 * cm, der, alto - 1.95 * cm)
        self.line(izq, 1.55 * cm, der, 1.55 * cm)
        self.setFillColor(HexColor("#5A6480"))
        self.setFont(REGULAR, 8.5)
        self.drawString(izq, 1.0 * cm, comun.PIE)
        self.drawRightString(der, 1.0 * cm, f"Página {self._pageNumber} de {total}")
        self.restoreState()

    def _nombre_app(self, x: float, y: float) -> None:
        """«Ψ-DIAG con» en azul (la Ψ es un trazo vectorial) y «IA» sobre una pastilla lavanda."""
        s = 13
        cx = x + 0.45 * s
        self.setStrokeColor(AZUL)
        self.setLineWidth(1.7)
        self.setLineCap(1)
        trazo = self.beginPath()
        trazo.moveTo(cx, y - 0.1 * s)
        trazo.lineTo(cx, y + 1.0 * s)
        trazo.moveTo(cx - 0.42 * s, y + 1.0 * s)
        trazo.lineTo(cx - 0.42 * s, y + 0.5 * s)
        trazo.curveTo(cx - 0.42 * s, y + 0.1 * s, cx + 0.42 * s, y + 0.1 * s, cx + 0.42 * s, y + 0.5 * s)
        trazo.lineTo(cx + 0.42 * s, y + 1.0 * s)
        self.drawPath(trazo, stroke=1, fill=0)
        self.setFillColor(AZUL)
        self.setFont(NEGRITA, 14)
        resto = "-DIAG con "
        self.drawString(x + 0.95 * s, y, resto)
        x_ia = x + 0.95 * s + stringWidth(resto, NEGRITA, 14)
        ancho_ia = stringWidth("IA", NEGRITA, 14) + 8
        self.setFillColor(LAVANDA)
        self.roundRect(x_ia, y - 4, ancho_ia, 19, 5, stroke=0, fill=1)
        self.setFillColor(white)
        self.drawString(x_ia + 4, y, "IA")


class _Encabezado(Paragraph):
    """Título que entra al índice: lleva su nivel y una clave fija para la liga interna y el marcador del visor de PDF."""

    def __init__(self, texto: str, estilo, nivel: int, clave: str, indexar: bool = True):
        super().__init__(texto, estilo)
        self.marcado, self.nivel, self.clave, self.indexar = texto, nivel, clave, indexar   # `texto` ya viene escapado


class _Documento(SimpleDocTemplate):
    """Plantilla que, por cada título, deja un marcador en el panel lateral del visor y una entrada (con liga) en el índice."""

    def beforeDocument(self):
        self._registrados = set()

    def afterFlowable(self, flowable):
        for f in [flowable, *getattr(flowable, "_content", [])]:   # los títulos que van dentro de un KeepTogether también cuentan
            if isinstance(f, _Encabezado) and f.indexar and f.clave not in self._registrados:
                self._registrados.add(f.clave)
                titulo = f.getPlainText()
                self.canv.bookmarkPage(f.clave)
                self.canv.addOutlineEntry(titulo, f.clave, f.nivel, closed=0)
                self.notify("TOCEntry", (f.nivel, f.marcado, self.page, f.clave))   # el índice vuelve a leer marcado: va escapado


def _vinetas(historia: list, estilos: dict, items, vacio: str | None = None) -> None:
    items = lista(items)
    for item in items:
        historia.append(Paragraph(_t(mayuscula_inicial(item)), estilos["vineta"], bulletText="•"))
    if not items and vacio:
        historia.append(Paragraph(vacio, estilos["vineta"], bulletText="•"))


def generar_pdf(reporte: dict) -> bytes:
    _registrar_fuentes()
    reporte = dicc(reporte)
    e = _estilos()
    h: list = []

    claves = iter(f"seccion{n}" for n in range(1, 100))

    def seccion(titulo: str) -> None:
        h.append(_Encabezado(_t(titulo), e["h1"], 0, next(claves)))
        h.append(HRFlowable(width="100%", thickness=0.6, color=LAVANDA, spaceAfter=5))

    def subtitulo(titulo: str, indexar: bool = True) -> _Encabezado:
        return _Encabezado(_t(titulo), e["h2"], 1, next(claves), indexar)

    h.append(Paragraph("Reporte de apoyo al psicodiagnóstico", e["titulo"]))
    h.append(Paragraph("Hipótesis de apoyo según la CIE-11", e["sub"]))
    estilo_tabla = TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("FONTNAME", (0, 0), (-1, -1), REGULAR)])   # sin FONTNAME usaría Helvetica
    indice = TableOfContents(dotsMinLevel=0, levelStyles=[e["indice1"], e["indice2"]], tableStyle=estilo_tabla)
    h.append(Paragraph("Índice", e["indice_titulo"]))
    h.append(indice)
    h.append(PageBreak())

    seccion("1. Datos del caso")
    for rotulo, valor in comun.datos_del_caso(reporte):
        h.append(Paragraph(f"<b>{_t(rotulo)}:</b> {_t(valor)}", e["cuerpo"]))

    seccion("2. Síntomas por categoría")
    sintomas = dicc(reporte.get("sintomas"))
    for etiqueta, clave in comun.ETIQUETAS_SINTOMAS:
        h.append(subtitulo(etiqueta, indexar=False))   # las cuatro categorías de síntomas no van al índice
        _vinetas(h, e, sintomas.get(clave), "Ninguno identificado")

    seccion("3. Hipótesis diagnósticas (de la más a la menos plausible)")
    hipotesis = lista_de_dicts(reporte.get("hipotesis"))
    for i, hip in enumerate(hipotesis, 1):
        bloque = [
            subtitulo(f"{i}. {mayuscula_inicial(hip.get('titulo')) or 'Sin título'} — {hip.get('codigo') or 'sin código'}"),
            Paragraph(_liga(hip.get("url"), "Abrir en el navegador OMS"), e["cuerpo"]),
        ]
        h.append(KeepTogether(bloque))
        h.append(Paragraph(f"<b>Justificación:</b> {_t(mayuscula_inicial(hip.get('justificacion')) or 'No indicada')}", e["cuerpo"]))
        h.append(Paragraph("<b>Criterios cumplidos:</b>", e["cuerpo"]))
        _vinetas(h, e, hip.get("criterios_cumplidos"), NINGUNO)
        h.append(Paragraph("<b>Criterios no cumplidos o sin confirmar:</b>", e["cuerpo"]))
        _vinetas(h, e, hip.get("criterios_no_cumplidos"), NINGUNO)
    if not hipotesis:
        h.append(Paragraph("Sin hipótesis diagnósticas.", e["cuerpo"]))
    if lista(reporte.get("ambiguedades")):
        h.append(subtitulo("Ambigüedades"))
        _vinetas(h, e, reporte.get("ambiguedades"))

    seccion("4. Diferenciales y exclusiones")
    _vinetas(h, e, reporte.get("diferenciales"), NINGUNO)
    alternativas = lista_de_dicts(reporte.get("alternativas"))
    if alternativas:
        h.append(subtitulo("Alternativas consultadas y descartadas"))
        for a in alternativas:
            h.append(Paragraph(f"{_t(mayuscula_inicial(a.get('titulo')) or 'Sin título')} ({_t(a.get('codigo') or 'sin código')}) — "
                               f"{_liga(a.get('url'), 'OMS')}", e["vineta"], bulletText="•"))

    seccion("5. Datos faltantes por recabar")
    _vinetas(h, e, reporte.get("datos_faltantes"), NINGUNO)

    seccion("6. Pruebas complementarias sugeridas")
    h.append(Paragraph("Sugerencias a validar por el profesional. Solo se indica el nombre de la prueba: "
                       "no se incluyen cuestionarios ni formas de calificación.", e["nota"]))
    guias = lista_de_dicts(reporte.get("guias"))
    pruebas = lista_de_dicts(reporte.get("pruebas"))
    for p in pruebas:
        linea = f"<b>{_t(mayuscula_inicial(p.get('nombre')) or 'Prueba sin nombre')}</b>"
        if texto(p.get("motivo")):
            linea += f": {_t(mayuscula_inicial(p.get('motivo')))}"
        guia = dicc(p.get("guia"))
        if guia:
            linea += f" · Referencia: {_liga(guia.get('url'), texto(guia.get('titulo')) or 'Guía')}"
            if texto(p.get("cita")):
                linea += f" — «{_t(p.get('cita'))}»"
        elif guias:
            linea += " · <i>(sin referencia en las guías consultadas)</i>"
        h.append(Paragraph(linea, e["vineta"], bulletText="•"))
    if not pruebas:
        h.append(Paragraph("Ninguna sugerida", e["vineta"], bulletText="•"))

    if guias:
        h.append(subtitulo("Guías clínicas consultadas"))
        h.append(Paragraph("Referencias para consulta del profesional; el sistema no recomienda tratamientos.", e["nota"]))

        def grupo_de(g: dict) -> str:
            return texto(g.get("etiqueta")) or texto(g.get("tipo")) or "Otras"
        for etiqueta in dict.fromkeys(grupo_de(g) for g in guias):
            h.append(Paragraph(f"<b>{_t(etiqueta)}</b>", e["cuerpo"]))
            for g in (g for g in guias if grupo_de(g) == etiqueta):
                cita = f" — «{_t(g.get('cita'))}»" if texto(g.get("cita")) else ""
                h.append(Paragraph(_liga(g.get("url"), texto(g.get("titulo")) or "Guía") + cita, e["vineta"], bulletText="•"))

    numero = 7
    conclusion = texto(reporte.get("conclusion"))
    if conclusion:
        seccion(f"{numero}. Conclusión, recomendaciones y siguientes pasos")
        for parrafo in comun.parrafos(conclusion):
            h.append(Paragraph(_t(parrafo), e["cuerpo"]))
        numero += 1

    seccion(f"{numero}. Aviso")
    h.append(Paragraph(_t(reporte.get("aviso")) or "&nbsp;", e["aviso"]))

    salida = io.BytesIO()
    documento = _Documento(
        salida, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.5 * cm, bottomMargin=2.2 * cm,
        title="Reporte de apoyo al psicodiagnóstico", author="Ψ-DIAG con IA".replace("Ψ", "Psi"), creator="Ψ-DIAG con IA".replace("Ψ", "Psi"),
    )
    documento.multiBuild(h, canvasmaker=_LienzoNumerado)   # varias pasadas: el índice necesita saber en qué página cae cada título
    return salida.getvalue()
