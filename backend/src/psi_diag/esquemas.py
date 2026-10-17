"""Contratos de salida (Pydantic). El LLM también lee las descripciones: están escritas como instrucciones."""
from typing import Literal, Optional

import re

from pydantic import BaseModel, Field, field_validator

LISTA = "Lista JSON de textos cortos, un elemento por dato (nunca un solo texto con varios datos). "


class SintomasPaciente(BaseModel):
    """Datos clínicos extraídos de la viñeta ya anonimizada."""

    paciente_ref: Optional[str] = Field(
        default=None,
        description="Placeholder de la persona que es el paciente, por ejemplo [PER_1], solo si aparece; si no, null",
    )
    edad: Optional[int] = Field(default=None, description="Edad en años solo si aparece escrita; si no, null")
    sexo: Optional[Literal["femenino", "masculino", "otro"]] = Field(
        default=None, description="Sexo del paciente solo si aparece; si no, null"
    )
    cognitivos: list[str] = Field(default_factory=list, description=LISTA + "Síntomas cognitivos (atención, memoria, pensamiento)", examples=[["dificultad para concentrarse"]])
    emocionales: list[str] = Field(default_factory=list, description=LISTA + "Síntomas emocionales o afectivos", examples=[["tristeza casi todos los días", "sentimientos de culpa"]])
    conductuales: list[str] = Field(default_factory=list, description=LISTA + "Cambios conductuales observables", examples=[["insomnio de conciliación"]])
    fisiologicos: list[str] = Field(
        default_factory=list,
        description=LISTA + "Síntomas fisiológicos o somáticos: patrones de sueño, activación autonómica (taquicardia, sudoración, temblor, falta de aire), cambios en el apetito o el peso, energía y fatiga, dolor, síntomas gastrointestinales, cambios hormonales (ciclo menstrual, posparto, menopausia, tiroides)",
        examples=[["taquicardia y sudoración en situaciones sociales", "pérdida de 5 kg en dos meses", "despierta de madrugada"]],
    )
    afectacion_social: list[str] = Field(
        default_factory=list, description=LISTA + "Afectación en el trabajo, la familia o las relaciones sociales",
        examples=[["falta al trabajo con frecuencia"]],
    )
    condiciones_medicas: list[str] = Field(
        default_factory=list,
        description=LISTA + "Enfermedades o condiciones médicas conocidas del paciente (diagnosticadas, no síntomas) y antecedentes médicos o genéticos familiares relevantes; solo las que el texto menciona",
        examples=[["diabetes tipo 2", "hipotiroidismo", "madre con trastorno bipolar"]],
    )
    medicamentos: list[str] = Field(
        default_factory=list,
        description=LISTA + "Medicamentos, suplementos o sustancias que el paciente usa, tal como aparecen en el texto (con la dosis solo si el texto la da); no inferir uno a partir de una enfermedad",
        examples=[["metformina", "levotiroxina 50 mcg"]],
    )
    temporalidad: Optional[str] = Field(
        default=None, description="Duración o evolución de los síntomas si se menciona; si no, null. No inventar"
    )
    datos_faltantes: list[str] = Field(
        default_factory=list,
        description=LISTA + "Datos clínicos relevantes que no aparecen y deberían recabarse (edad, duración, severidad, etc.)",
        examples=[["severidad de los síntomas", "antecedentes familiares"]],
    )

    def hay_sintomas(self) -> bool:
        return any([self.cognitivos, self.emocionales, self.conductuales, self.fisiologicos, self.afectacion_social])


class HipotesisRedactada(BaseModel):
    codigo: str = Field(description="Código CIE-11 EXACTO de uno de los candidatos recibidos; nunca otro")
    justificacion: str = Field(description="Por qué los síntomas del caso encajan con los criterios de esa entidad")
    criterios_cumplidos: list[str] = Field(default_factory=list, description=LISTA + "Criterios que el caso sí cumple")
    criterios_no_cumplidos: list[str] = Field(
        default_factory=list, description=LISTA + "Criterios que faltan o no se pueden confirmar con la información dada"
    )


class PruebaSugerida(BaseModel):
    nombre: str = Field(description="Solo el nombre de la prueba, por ejemplo Inventario de Ansiedad de Beck")
    motivo: str = Field(description="Una frase sobre por qué sería útil para este caso")
    fuente_id: Optional[str] = Field(
        default=None,
        description="Id (G1, G2...) de la guía recibida cuyo extracto menciona esta prueba; null si ninguna la menciona",
    )
    cita_textual: Optional[str] = Field(
        default=None,
        description="Fragmento copiado literalmente del extracto de esa guía donde aparece la prueba (máximo 200 caracteres); null si no hay fuente",
    )


# A veces el modelo cierra una cadena y le pega el resto del JSON de la llamada (`", "otro_campo": null}]`): se corta ahí.
_RESIDUO_JSON = re.compile(r'"?\s*[,}\]]+\s*"\w+"\s*:.*$|"\s*[}\]]+\s*$', re.DOTALL)


def sin_residuo_json(texto: str) -> str:
    return _RESIDUO_JSON.sub("", texto or "").strip()


class ReporteClinico(BaseModel):
    hipotesis: list[HipotesisRedactada] = Field(description="Lista de objetos, ordenados de la más a la menos plausible")
    ambiguedades: list[str] = Field(default_factory=list, description=LISTA + "Ambigüedades en la búsqueda o en el caso")
    diferenciales: list[str] = Field(default_factory=list, description=LISTA + "Diagnósticos diferenciales y exclusiones a considerar")
    datos_faltantes: list[str] = Field(
        default_factory=list,
        description=LISTA + "Datos a recabar para confirmar o descartar",
        examples=[["duración exacta de los síntomas", "antecedentes personales"]],
    )
    pruebas: list[PruebaSugerida] = Field(default_factory=list, description="Lista de objetos {nombre, motivo}. Pruebas complementarias: solo nombre y motivo")
    conclusion: str = Field(
        default="",
        description=(
            "Tres párrafos cortos separados por una línea en blanco, para el profesional: (1) qué sugiere el cuadro en "
            "conjunto; (2) recomendaciones para la evaluación; (3) siguientes pasos (información por recabar, pruebas a "
            "aplicar, diferenciales a descartar). Sin tratamiento ni dosis y sin afirmar un diagnóstico. Solo texto."
        ),
    )

    @field_validator("conclusion", mode="after")
    @classmethod
    def _limpiar_conclusion(cls, valor: str) -> str:
        return sin_residuo_json(valor)
