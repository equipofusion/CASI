"""Orquestación: de un archivo de reunión a los archivos de transcripción.

El trabajo se hace por tramos y se guarda el avance después de cada uno, para
que una corrida de varias horas se pueda retomar donde quedó.
"""
from __future__ import annotations

import math
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import audio
import salida
from config import Config
from parcial import Parcial

Informar = Callable[[str], None]


class ErrorDeProceso(Exception):
    """Falla esperable y explicable al usuario (no un bug)."""


def _sin_ruido(_: str) -> None:
    pass


def _bajar_prioridad(informar: Informar) -> None:
    """Cede CPU al resto del sistema.

    Sin esto, transcribir cuatro horas de audio deja la máquina inutilizable
    durante todo ese tiempo.
    """
    try:
        os.nice(10)
    except (AttributeError, OSError):
        informar("No se pudo bajar la prioridad del proceso; sigue igual.")


def _preparar_wav(origen: Path, parcial: Parcial, informar: Informar) -> float:
    """Devuelve la duración del WAV de trabajo, reutilizándolo si ya existe."""
    if parcial.wav.is_file():
        try:
            duracion = audio.duracion_wav(parcial.wav)
            informar(f"Reutilizando el audio ya extraído ({audio.formatear_duracion(duracion)})")
            return duracion
        except Exception:
            parcial.wav.unlink(missing_ok=True)  # quedó a medias, se rehace

    informar(f"Extrayendo audio de {origen.name}…")
    try:
        duracion = audio.extraer_wav(origen, parcial.wav)
    except audio.SinPistaDeAudio as error:
        raise ErrorDeProceso(str(error)) from error
    except Exception as error:  # contenedor corrupto o formato no soportado
        raise ErrorDeProceso(f"No se pudo decodificar {origen.name}: {error}") from error

    informar(f"Duración: {audio.formatear_duracion(duracion)}")
    return duracion


def transcribir_archivo(
    origen: Path, cfg: Config, informar: Informar = _sin_ruido
) -> list[Path]:
    """Transcribe `origen` y devuelve las rutas generadas."""
    if not origen.is_file():
        raise ErrorDeProceso(f"No existe el archivo {origen}")

    if cfg.diarizar and not cfg.token_hf:
        raise ErrorDeProceso(
            "La diarización está activada pero falta el token de HuggingFace. "
            "Cargalo en transcriptor/.env como HF_TOKEN=..., o desactivala con "
            "diarizar = false en config.toml."
        )

    if cfg.prioridad_baja:
        _bajar_prioridad(informar)

    import asr

    parcial = Parcial(cfg.carpeta_salida / ".parciales", origen)
    duracion = _preparar_wav(origen, parcial, informar)

    segundos_por_tramo = cfg.minutos_por_tramo * 60
    total_tramos = max(1, math.ceil(duracion / segundos_por_tramo))

    hechos, palabras, idioma = parcial.cargar()
    if hechos:
        informar(f"Retomando: {hechos} de {total_tramos} tramos ya estaban hechos.")

    if hechos < total_tramos:
        informar(
            f"Transcribiendo con el modelo {cfg.modelo} en {total_tramos} tramos "
            f"de {cfg.minutos_por_tramo} min, con {cfg.hilos} hilos…"
        )
        try:
            motor = asr.Motor(cfg.modelo, cfg.computo, cfg.hilos)
        except Exception as error:
            raise ErrorDeProceso(f"No se pudo cargar el modelo {cfg.modelo}: {error}") from error

        for indice in range(hechos, total_tramos):
            inicio = indice * segundos_por_tramo
            reloj = audio.formatear_duracion(inicio)
            informar(f"  tramo {indice + 1}/{total_tramos} (desde {reloj})…")
            try:
                muestras = asr.leer_tramo(parcial.wav, inicio, segundos_por_tramo)
                nuevas, detectado = motor.transcribir_tramo(
                    muestras, idioma=cfg.idioma or idioma or None, desplazamiento=inicio
                )
            except Exception as error:
                raise ErrorDeProceso(
                    f"Falló la transcripción en el tramo {indice + 1}: {error}. "
                    f"El avance quedó guardado: volvé a lanzarlo y retoma desde ahí."
                ) from error

            palabras.extend(nuevas)
            idioma = idioma or detectado
            # Guardar acá es lo que hace que un corte no cueste horas.
            parcial.guardar(indice + 1, palabras, idioma)

    if not palabras:
        parcial.limpiar()
        raise ErrorDeProceso(
            f"{origen.name}: no se detectó habla. ¿Es una grabación muda o solo música?"
        )

    turnos = []
    if cfg.diarizar:
        import hablantes

        informar("Detectando hablantes (pyannote)… esto también lleva su tiempo.")
        try:
            turnos = hablantes.diarizar(
                parcial.wav,
                token=cfg.token_hf or "",
                modelo=cfg.modelo_hablantes,
                dispositivo=cfg.dispositivo_diarizacion,
                min_hablantes=cfg.min_hablantes,
                max_hablantes=cfg.max_hablantes,
            )
            informar(f"Voces detectadas: {len({t.hablante for t in turnos})}")
        except Exception as error:
            # La transcripción ya está hecha y puede haber costado horas: no se
            # tira por un fallo en la diarización. Se avisa fuerte y se sigue.
            informar(f"⚠ Falló la diarización ({error}).")
            informar("⚠ Se guarda la transcripción SIN separar por hablante.")

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
    parcial.limpiar()
    informar(f"Listo: {len(bloques)} intervenciones → {cfg.carpeta_salida}")
    return generados
