#!/usr/bin/env python3
"""Vigía de carpeta: transcribe solo lo que aparece.

Dejás la grabación en la carpeta vigilada y a los pocos minutos tenés la
transcripción en la carpeta de salida. Corre en primer plano; para dejarlo
andando siempre, ver el launchd del README.
"""
from __future__ import annotations

import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import config
from config import EXTENSIONES
from estado import Estado
from proceso import ErrorDeProceso, transcribir_archivo

_seguir = True


def _detener(*_) -> None:
    global _seguir
    _seguir = False
    print("\nCortando después de la tarea actual…")


def registrar(mensaje: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {mensaje}", flush=True)


def candidatos(carpeta: Path, salida: Path) -> list[Path]:
    """Archivos transcribibles, ignorando ocultos y la propia carpeta de salida."""
    encontrados = []
    for ruta in sorted(carpeta.rglob("*")):
        if not ruta.is_file() or ruta.name.startswith("."):
            continue
        if ruta.suffix.lower() not in EXTENSIONES:
            continue
        if salida in ruta.parents:
            continue
        encontrados.append(ruta)
    return encontrados


def esta_estable(ruta: Path, visto: dict[Path, tuple[int, float]], espera: float) -> bool:
    """¿Terminó de copiarse?

    Un archivo que todavía se está bajando o copiando crece entre vueltas.
    Recién lo tomamos cuando su tamaño no cambió durante `espera` segundos.
    """
    try:
        tamano = ruta.stat().st_size
    except OSError:
        return False

    ahora = time.monotonic()
    anterior = visto.get(ruta)
    if anterior is None or anterior[0] != tamano:
        visto[ruta] = (tamano, ahora)
        return False
    return (ahora - anterior[1]) >= espera


def main() -> int:
    signal.signal(signal.SIGINT, _detener)
    signal.signal(signal.SIGTERM, _detener)

    try:
        cfg = config.cargar()
    except config.ErrorDeConfig as error:
        print(f"Error de configuración: {error}", file=sys.stderr)
        return 2

    cfg.carpeta_vigilada.mkdir(parents=True, exist_ok=True)
    cfg.carpeta_salida.mkdir(parents=True, exist_ok=True)
    estado = Estado(cfg.archivo_estado)
    visto: dict[Path, tuple[int, float]] = {}

    registrar(f"Vigilando  {cfg.carpeta_vigilada}")
    registrar(f"Escribiendo en {cfg.carpeta_salida}")
    registrar(
        f"Modelo {cfg.modelo} · hablantes: {'sí' if cfg.diarizar else 'no'} · "
        f"cada {cfg.intervalo_segundos}s"
    )

    while _seguir:
        for ruta in candidatos(cfg.carpeta_vigilada, cfg.carpeta_salida):
            if not _seguir:
                break
            if estado.ya_procesado(ruta):
                continue
            if not esta_estable(ruta, visto, cfg.espera_estabilidad_segundos):
                continue

            registrar(f"Nuevo: {ruta.name}")
            try:
                generados = transcribir_archivo(ruta, cfg, informar=registrar)
                estado.marcar(ruta, generados)
                registrar(f"✓ {ruta.name} → {', '.join(g.name for g in generados)}")
            except ErrorDeProceso as error:
                # Se registra como procesado para no reintentar en bucle cada
                # 20 segundos con el mismo archivo roto.
                estado.marcar_fallido(ruta, str(error))
                registrar(f"✗ {ruta.name}: {error}")
            except Exception as error:  # noqa: BLE001 - el vigía no debe morirse
                estado.marcar_fallido(ruta, repr(error))
                registrar(f"✗ {ruta.name}: error inesperado: {error!r}")

        for _ in range(cfg.intervalo_segundos):
            if not _seguir:
                break
            time.sleep(1)

    registrar("Vigía detenido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
