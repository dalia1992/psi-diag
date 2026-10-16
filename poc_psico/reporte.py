"""Validación de hipótesis contra las tools y renderizado del reporte en Markdown."""
import re
import unicodedata
from datetime import date

from .esquemas import ReporteClinico


def validar_hipotesis(reporte: ReporteClinico, candidatos: list):
    """Une cada hipótesis con su candidato. Código, título y liga salen de la tool, nunca del LLM."""
    por_codigo = {c["codigo"]: c for c in candidatos}
    finales, advertencias, vistos = [], [], set()
    for h in reporte.hipotesis:
        candidato = por_codigo.get(h.codigo)
        if candidato is None:
            advertencias.append(f"Se descartó la hipótesis con código {h.codigo}: no fue obtenido de las tools")
            continue
        if h.codigo in vistos:
            continue
        vistos.add(h.codigo)
        finales.append(
            {
                **candidato,
                "justificacion": h.justificacion,
                "criterios_cumplidos": h.criterios_cumplidos,
                "criterios_no_cumplidos": h.criterios_no_cumplidos,
            }
        )
    return finales, advertencias


ETIQUETAS_GUIAS = {
    "imss": "IMSS (México) · Guías de práctica clínica",
    "apa": "APA · Evaluación, diagnóstico e intervención",
    "oms": "OMS",
}


def _normalizar(texto: str) -> str:
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(re.sub(r"\W+", " ", sin_acentos.lower()).split())


def validar_pruebas(pruebas: list, guias: list):
    """Una prueba queda respaldada solo si la guía existe y su extracto contiene la cita literal que dio el LLM.

    La liga sale de la guía, nunca del LLM. Devuelve ([{nombre, motivo, guia|None, cita}], advertencias)."""
    por_id = {g["id"]: g for g in guias or [] if g.get("id")}
    finales, advertencias = [], []
    for p in pruebas:
        guia, cita = None, (p.cita_textual or "").strip()
        if p.fuente_id:
            candidata = por_id.get(p.fuente_id)
            if candidata is None:
                advertencias.append(f"La prueba {p.nombre} citó la guía {p.fuente_id}, que no existe: queda sin referencia")
            elif not cita or _normalizar(cita) not in _normalizar(candidata.get("extracto", "")):
                advertencias.append(f"La cita de la prueba {p.nombre} no aparece en la guía {p.fuente_id}: queda sin referencia")
            else:
                guia = candidata
        finales.append({"nombre": p.nombre, "motivo": p.motivo, "guia": guia, "cita": cita if guia else ""})
    return finales, advertencias


def _mayuscula_inicial(texto: str) -> str:
    texto = texto.strip()
    return texto[:1].upper() + texto[1:]


NINGUNO_INDICADO = "Ninguno indicado"


def _lista(items, vacio="Ninguno identificado") -> str:
    return "\n".join(f"- {_mayuscula_inicial(i)}" for i in items) if items else f"- {vacio}"


def _linea_prueba(p: dict, hay_guias: bool) -> str:
    base = f"- **{_mayuscula_inicial(p['nombre'])}**: {_mayuscula_inicial(p['motivo'])}"
    if p["guia"]:
        return f"{base} · Referencia: [{p['guia']['titulo']}]({p['guia']['url']}) — «{p['cita']}»"
    return f"{base} · _(sin referencia en las guías consultadas)_" if hay_guias else base


def render_markdown(
    sintomas: dict, hipotesis: list, reporte: ReporteClinico, alternativas: list, fecha: date, guias: list | None = None,
    pruebas: list | None = None,
) -> str:
    partes = [
        "# Reporte de apoyo al psicodiagnóstico",
        "## 1. Datos del caso",
        f"- Paciente: {sintomas.get('paciente_ref') or 'No identificado'}",
        f"- Edad: {sintomas['edad'] if sintomas.get('edad') is not None else 'No indicada'}",
        f"- Sexo: {sintomas.get('sexo') or 'No indicado'}",
        f"- Temporalidad: {sintomas.get('temporalidad') or 'No indicada'}",
        f"- Fecha del reporte: {fecha.isoformat()}",
        "## 2. Síntomas por categoría",
    ]
    for etiqueta, clave in (
        ("Cognitivos", "cognitivos"),
        ("Emocionales", "emocionales"),
        ("Conductuales", "conductuales"),
        ("Afectación social", "afectacion_social"),
    ):
        partes += [f"### {etiqueta}", _lista(sintomas.get(clave) or [])]

    partes.append("## 3. Hipótesis diagnósticas (de la más a la menos plausible)")
    for i, h in enumerate(hipotesis, 1):
        partes += [
            f"### {i}. {_mayuscula_inicial(h['titulo'])} — `{h['codigo']}`",
            f"[Abrir en el navegador OMS]({h['url']})",
            f"**Justificación:** {_mayuscula_inicial(h['justificacion'])}",
            "**Criterios cumplidos:**",
            _lista(h["criterios_cumplidos"], NINGUNO_INDICADO),
            "**Criterios no cumplidos o sin confirmar:**",
            _lista(h["criterios_no_cumplidos"], NINGUNO_INDICADO),
        ]
    if reporte.ambiguedades:
        partes += ["### Ambigüedades", _lista(reporte.ambiguedades)]

    partes += ["## 4. Diferenciales y exclusiones", _lista(reporte.diferenciales, NINGUNO_INDICADO)]
    if alternativas:
        partes.append("### Alternativas consultadas y descartadas")
        partes += [f"- {_mayuscula_inicial(a['titulo'])} (`{a['codigo']}`) — [OMS]({a['url']})" for a in alternativas]

    partes += ["## 5. Datos faltantes por recabar", _lista(reporte.datos_faltantes, NINGUNO_INDICADO)]
    partes += [
        "## 6. Pruebas complementarias sugeridas",
        "> Sugerencias a validar por el profesional. Solo se indica el nombre de la prueba: no se incluyen cuestionarios ni formas de calificación.",
    ]
    if pruebas is None:
        pruebas, _ = validar_pruebas(reporte.pruebas, guias)
    partes += [_linea_prueba(p, bool(guias)) for p in pruebas] or ["- Ninguna sugerida"]
    if guias:
        partes += ["### Guías clínicas consultadas", "> Referencias para consulta del profesional; el sistema no recomienda tratamientos."]
        for tipo, etiqueta in ETIQUETAS_GUIAS.items():
            grupo = [g for g in guias if g.get("tipo", "apa") == tipo]
            if grupo:
                partes.append(f"**{etiqueta}**")
                partes.append("\n".join(f"- [{g['titulo']}]({g['url']})" + (f" — «{g['cita']}»" if g.get("cita") else "") for g in grupo))
    partes += [
        "## 7. Aviso",
        "Este reporte contiene hipótesis de apoyo generadas con ayuda de IA a partir de la CIE-11. No es un diagnóstico: la decisión clínica es del profesional.",
    ]
    return "\n\n".join(partes) + "\n"
