"""Transcripción con faster-whisper (CTranslate2), por tramos.

En Mac corre siempre en CPU: CTranslate2 no soporta Metal/MPS.

El audio se procesa en tramos en vez de de una sola vez. Una reunión de cuatro
horas puede llevar varias horas de proceso, y hacerlo en tramos permite guardar
lo hecho a medida que avanza: si se corta, se retoma donde quedó en vez de
volver a empezar.
"""
from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TASA = 16_000
_ESCALA_INT16 = 32768.0


@dataclass(frozen=True)
class Palabra:
    inicio: float
    fin: float
    texto: str


def duracion_wav(wav: Path) -> float:
    with wave.open(str(wav)) as archivo:
        return archivo.getnframes() / archivo.getframerate()


def leer_tramo(wav: Path, inicio: float, duracion: float) -> np.ndarray:
    """Lee un tramo del WAV como forma de onda float32 en [-1, 1].

    Lee solo lo necesario: un WAV de cuatro horas ocupa medio giga y no tiene
    sentido tenerlo entero en memoria.
    """
    with wave.open(str(wav)) as archivo:
        tasa = archivo.getframerate()
        archivo.setpos(min(int(inicio * tasa), archivo.getnframes()))
        crudo = archivo.readframes(int(duracion * tasa))

    return np.frombuffer(crudo, dtype=np.int16).astype(np.float32) / _ESCALA_INT16


class Motor:
    """Envoltorio del modelo de Whisper, cargado una sola vez."""

    def __init__(self, modelo: str, computo: str, hilos: int) -> None:
        from faster_whisper import WhisperModel

        self.nombre = modelo
        self._modelo = WhisperModel(
            modelo, device="cpu", compute_type=computo, cpu_threads=hilos
        )

    def transcribir_tramo(
        self, muestras: np.ndarray, *, idioma: str | None, desplazamiento: float = 0.0
    ) -> tuple[list[Palabra], str]:
        """Transcribe un tramo y corrige las marcas de tiempo al reloj global."""
        segmentos, info = self._modelo.transcribe(
            muestras,
            language=idioma or None,
            beam_size=5,
            word_timestamps=True,
            # El VAD saltea los silencios: en una reunión con pausas largas es
            # la diferencia entre una hora de proceso y varias.
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            # Sin esto, Whisper arrastra el contexto anterior y en tramos mudos
            # entra en bucles repitiendo la última frase. En reuniones pasa
            # seguido, y además es lo que permite cortar en tramos sin perder
            # coherencia.
            condition_on_previous_text=False,
        )

        palabras: list[Palabra] = []
        for segmento in segmentos:
            if segmento.words:
                palabras.extend(
                    Palabra(p.start + desplazamiento, p.end + desplazamiento, p.word.strip())
                    for p in segmento.words
                    if p.word.strip()
                )
            elif texto := (segmento.text or "").strip():
                # Respaldo por si un segmento viene sin desglose de palabras.
                palabras.append(
                    Palabra(
                        segmento.start + desplazamiento,
                        segmento.end + desplazamiento,
                        texto,
                    )
                )

        return palabras, info.language
