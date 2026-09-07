"""Orquestación: de un archivo de reunión a los archivos de transcripción."""
from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import audio
import salida
from config import Config

Informar = Callable[[str], None]


class ErrorDeProceso(Exception):
    """Falla esperable y explicable al usuario (no un bug)."""


def _sin_ruido(_: str) -> None:
    pass


def transcribir_archivo(
    origen: Path, cfg: Config, informar: Informar = _sin_ruido
) -> list[Path]:
    """Transcribe `origen` y devuelve las rutas generadas."""
    if not origen.is_file():
        raise ErrorDeProceso(f"No existe el archivo {origen}")

    quiere_hablantes = cfg.diarizar
    if quiere_hablantes and not cfg.token_hf:
        raise ErrorDeProceso(
            "La diarización está activada pero falta el token de HuggingFace. "
            "Cargalo en transcriptor/.env como HF_TOKEN=..., o desactivala con "
            "diarizar = false en config.toml."
        )

    with tempfile.TemporaryDirectory(prefix="transcriptor-") as temporal:
        wav = Path(temporal) / "audio.wav"

        informar(f"Extrayendo audio de {origen.name}…")
        try:
            duracion = audio.extraer_wav(origen, wav)
        except audio.SinPistaDeAudio as error:
            raise ErrorDeProceso(str(error)) from error
        except Exception as error:  # contenedor corrupto o formato no soportado
            raise ErrorDeProceso(f"No se pudo decodificar {origen.name}: {error}") from error

        informar(f"Duración: {audio.formatear_duracion(duracion)}")

        turnos = []
        if quiere_hablantes:
            import hablantes

            informar("Detectando hablantes (pyannote)…")
            try:
                turnos = hablantes.diarizar(
                    wav,
                    token=cfg.token_hf or "",
                    modelo=cfg.modelo_hablantes,
                    dispositivo=cfg.dispositivo_diarizacion,
                    min_hablantes=cfg.min_hablantes,
                    max_hablantes=cfg.max_hablantes,
                )
            except Exception as error:
                raise ErrorDeProceso(f"Falló la diarización: {error}") from error

            distintos = len({t.hablante for t in turnos})
            informar(f"Voces detectadas: {distintos}")

        informar(f"Transcribiendo con el modelo {cfg.modelo}… (puede tardar)")
        import asr

        ultimo_aviso = 0.0

        def avanzar(segundo: float) -> None:
            nonlocal ultimo_aviso
            # Un aviso cada 10% evita inundar el log de una reunión de una hora.
            if duracion > 0 and segundo - ultimo_aviso >= duracion / 10:
                ultimo_aviso = segundo
                informar(f"  … {min(100, int(100 * segundo / duracion))}%")

        try:
            palabras, idioma = asr.transcribir(
                wav,
                modelo=cfg.modelo,
                idioma=cfg.idioma,
                computo=cfg.computo,
                hilos=cfg.hilos,
                al_avanzar=avanzar,
            )
        except Exception as error:
            raise ErrorDeProceso(f"Falló la transcripción: {error}") from error

    if not palabras:
        raise ErrorDeProceso(
            f"{origen.name}: no se detectó habla. ¿Es una grabación muda o solo música?"
        )

    import hablantes

    bloques = hablantes.asignar(palabras, turnos)

    meta = salida.Metadatos(
        origen=origen,
        duracion=duracion,
        idioma=idioma,
        modelo=cfg.modelo,
        con_hablantes=bool(turnos),
        procesado=datetime.now(),
    )
    generados = salida.escribir_todo(
        cfg.carpeta_salida, origen.stem, bloques, meta, cfg.formatos_salida
    )
    informar(f"Listo: {len(bloques)} intervenciones → {cfg.carpeta_salida}")
    return generados
