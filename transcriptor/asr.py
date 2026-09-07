"""Transcripción con faster-whisper (CTranslate2).

En Mac corre siempre en CPU: CTranslate2 no soporta Metal/MPS. Con `int8` y
un chip de la serie M, `large-v3` rinde bastante por encima de tiempo real.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Palabra:
    inicio: float
    fin: float
    texto: str


def transcribir(
    wav: Path,
    *,
    modelo: str,
    idioma: str,
    computo: str,
    hilos: int,
    al_avanzar: Callable[[float], None] | None = None,
) -> tuple[list[Palabra], str]:
    """Devuelve las palabras con marca de tiempo y el idioma detectado.

    `al_avanzar` recibe el segundo de audio ya procesado, para poder mostrar
    progreso en reuniones largas sin que parezca colgado.
    """
    from faster_whisper import WhisperModel

    motor = WhisperModel(modelo, device="cpu", compute_type=computo, cpu_threads=hilos)

    segmentos, info = motor.transcribe(
        str(wav),
        language=idioma or None,
        beam_size=5,
        word_timestamps=True,
        # El VAD saltea los silencios: en una reunión con pausas largas es la
        # diferencia entre veinte minutos de proceso y una hora.
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        # Sin esto, Whisper arrastra el contexto anterior y en tramos mudos
        # entra en bucles repitiendo la última frase. En reuniones pasa seguido.
        condition_on_previous_text=False,
    )

    palabras: list[Palabra] = []
    for segmento in segmentos:
        if segmento.words:
            palabras.extend(
                Palabra(p.start, p.end, p.word.strip())
                for p in segmento.words
                if p.word.strip()
            )
        elif texto := (segmento.text or "").strip():
            # Respaldo por si un segmento viene sin desglose de palabras.
            palabras.append(Palabra(segmento.start, segmento.end, texto))

        if al_avanzar:
            al_avanzar(segmento.end)

    return palabras, info.language
