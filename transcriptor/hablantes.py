"""Diarización: quién habla en cada tramo, y cómo pegar eso a la transcripción.

pyannote devuelve turnos de voz sin texto; Whisper devuelve texto sin identidad.
Este módulo cruza ambos por solapamiento temporal.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asr import Palabra

SIN_IDENTIFICAR = "Hablante ?"


@dataclass(frozen=True)
class Turno:
    inicio: float
    fin: float
    hablante: str


@dataclass
class Bloque:
    """Una intervención continua de un mismo hablante."""
    hablante: str
    palabras: list[Palabra]

    @property
    def inicio(self) -> float:
        return self.palabras[0].inicio

    @property
    def fin(self) -> float:
        return self.palabras[-1].fin

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)


def diarizar(
    wav: Path,
    *,
    token: str,
    dispositivo: str = "cpu",
    min_hablantes: int | None = None,
    max_hablantes: int | None = None,
) -> list[Turno]:
    """Corre pyannote sobre el WAV y devuelve los turnos ordenados por inicio."""
    import torch
    from pyannote.audio import Pipeline

    tuberia = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", use_auth_token=token
    )
    if tuberia is None:
        raise RuntimeError(
            "pyannote no devolvió una pipeline. Casi siempre es el token: "
            "revisá que sea válido y que hayas aceptado las condiciones de uso "
            "de pyannote/speaker-diarization-3.1 y pyannote/segmentation-3.0 "
            "en huggingface.co."
        )
    tuberia.to(torch.device(dispositivo))

    restricciones = {}
    if min_hablantes:
        restricciones["min_speakers"] = min_hablantes
    if max_hablantes:
        restricciones["max_speakers"] = max_hablantes

    anotacion = tuberia(str(wav), **restricciones)
    turnos = [
        Turno(segmento.start, segmento.end, etiqueta)
        for segmento, _, etiqueta in anotacion.itertracks(yield_label=True)
    ]
    return sorted(turnos, key=lambda t: t.inicio)


def _nombres_legibles(turnos: list[Turno]) -> dict[str, str]:
    """SPEAKER_03 -> "Hablante 1", numerando por orden de aparición."""
    nombres: dict[str, str] = {}
    for turno in turnos:
        if turno.hablante not in nombres:
            nombres[turno.hablante] = f"Hablante {len(nombres) + 1}"
    return nombres


def _hablante_de(palabra: Palabra, turnos: list[Turno], desde: int) -> tuple[str, int]:
    """Elige el turno que más se solapa con la palabra.

    Si ninguno la toca (silencio mal recortado, risa, muletilla suelta), cae al
    turno temporalmente más cercano: continuar al hablante equivocado es peor
    que dejar el bloque sin cortar.
    """
    while desde < len(turnos) and turnos[desde].fin < palabra.inicio:
        desde += 1

    mejor_hablante, mejor_solape = "", 0.0
    candidato_cercano, mejor_distancia = "", float("inf")

    indice = desde
    while indice < len(turnos) and turnos[indice].inicio <= palabra.fin:
        turno = turnos[indice]
        solape = min(turno.fin, palabra.fin) - max(turno.inicio, palabra.inicio)
        if solape > mejor_solape:
            mejor_hablante, mejor_solape = turno.hablante, solape
        indice += 1

    if mejor_hablante:
        return mejor_hablante, desde

    for turno in turnos[max(0, desde - 1): desde + 2]:
        distancia = max(turno.inicio - palabra.fin, palabra.inicio - turno.fin, 0.0)
        if distancia < mejor_distancia:
            candidato_cercano, mejor_distancia = turno.hablante, distancia

    return candidato_cercano or SIN_IDENTIFICAR, desde


def asignar(palabras: list[Palabra], turnos: list[Turno]) -> list[Bloque]:
    """Agrupa las palabras en intervenciones continuas por hablante."""
    if not palabras:
        return []
    if not turnos:
        return [Bloque(SIN_IDENTIFICAR, list(palabras))]

    nombres = _nombres_legibles(turnos)
    bloques: list[Bloque] = []
    cursor = 0

    for palabra in palabras:
        etiqueta, cursor = _hablante_de(palabra, turnos, cursor)
        hablante = nombres.get(etiqueta, SIN_IDENTIFICAR)
        if bloques and bloques[-1].hablante == hablante:
            bloques[-1].palabras.append(palabra)
        else:
            bloques.append(Bloque(hablante, [palabra]))

    return bloques
