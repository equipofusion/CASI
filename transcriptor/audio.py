"""Normalización de audio.

Todo lo que entra (un .m4a de WhatsApp, un .mov del celular, un .mp4 de Zoom)
sale como WAV mono de 16 kHz. Whisper y pyannote esperan exactamente eso, y
unificarlo acá evita que cada uno lidie con contenedores raros por su cuenta.

Usa PyAV, que trae ffmpeg embebido: no hace falta instalar ffmpeg aparte.
"""
from __future__ import annotations

import wave
from pathlib import Path

import av

TASA = 16_000
CANALES = 1
ANCHO_MUESTRA = 2  # 16 bits


class SinPistaDeAudio(Exception):
    """El archivo existe y se puede abrir, pero no tiene audio adentro."""


def extraer_wav(origen: Path, destino: Path) -> float:
    """Decodifica `origen` a un WAV mono 16 kHz en `destino`.

    Devuelve la duración en segundos, calculada sobre las muestras realmente
    escritas (no sobre los metadatos del contenedor, que mienten seguido en
    archivos truncados o grabaciones interrumpidas).
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    muestras = 0

    with av.open(str(origen)) as contenedor:
        if not contenedor.streams.audio:
            raise SinPistaDeAudio(f"{origen.name} no contiene ninguna pista de audio")

        pista = contenedor.streams.audio[0]
        # Descartar cuadros dañados en vez de abortar: una grabación cortada
        # sigue siendo transcribible salvo por el pedazo roto.
        pista.thread_type = "AUTO"
        remuestreador = av.AudioResampler(format="s16", layout="mono", rate=TASA)

        with wave.open(str(destino), "wb") as salida:
            salida.setnchannels(CANALES)
            salida.setsampwidth(ANCHO_MUESTRA)
            salida.setframerate(TASA)

            for cuadro in contenedor.decode(pista):
                for remuestreado in remuestreador.resample(cuadro):
                    datos = remuestreado.to_ndarray().tobytes()
                    salida.writeframes(datos)
                    muestras += len(datos) // ANCHO_MUESTRA

            # El remuestreador guarda muestras en su buffer interno; sin este
            # vaciado se pierde la última fracción de segundo.
            for remuestreado in remuestreador.resample(None):
                datos = remuestreado.to_ndarray().tobytes()
                salida.writeframes(datos)
                muestras += len(datos) // ANCHO_MUESTRA

    if muestras == 0:
        raise SinPistaDeAudio(f"{origen.name} tiene pista de audio pero no se decodificó nada")

    return muestras / TASA


def formatear_duracion(segundos: float) -> str:
    """1h 04m 12s — para los mensajes de progreso y el encabezado del informe."""
    total = int(round(segundos))
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    if horas:
        return f"{horas}h {minutos:02d}m {segs:02d}s"
    if minutos:
        return f"{minutos}m {segs:02d}s"
    return f"{segs}s"
