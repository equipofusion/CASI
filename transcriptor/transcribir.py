#!/usr/bin/env python3
"""Transcribe uno o varios archivos a mano.

    python3 transcribir.py "~/Downloads/Reunión Juan Formaro 3-9.m4a"
    python3 transcribir.py *.mov --sin-hablantes --modelo medium
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import config
from proceso import ErrorDeProceso, transcribir_archivo


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transcribe reuniones (audio o video) con Whisper y pyannote.",
    )
    parser.add_argument("archivos", nargs="+", type=Path, help="Archivos a transcribir")
    parser.add_argument("--modelo", help="tiny, base, small, medium, large-v3…")
    parser.add_argument("--idioma", help="Código ISO, por ejemplo 'es'. Vacío = autodetectar")
    parser.add_argument("--salida", type=Path, help="Carpeta donde dejar los resultados")
    parser.add_argument(
        "--sin-hablantes", action="store_true",
        help="Saltea la diarización (más rápido, no requiere token de HuggingFace)",
    )
    parser.add_argument(
        "--hilos", type=int, metavar="N",
        help="Núcleos a usar. Menos hilos = la Mac queda más usable mientras trabaja",
    )
    parser.add_argument(
        "--hablantes", type=int, metavar="N",
        help="Cantidad exacta de personas en la reunión, si la sabés (mejora el corte)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)

    try:
        cfg = config.cargar()
    except config.ErrorDeConfig as error:
        print(f"Error de configuración: {error}", file=sys.stderr)
        return 2

    if args.modelo:
        cfg = replace(cfg, modelo=args.modelo)
    if args.idioma is not None:
        cfg = replace(cfg, idioma=args.idioma)
    if args.salida:
        cfg = replace(cfg, carpeta_salida=args.salida.expanduser())
    if args.hilos:
        cfg = replace(cfg, hilos=args.hilos)
    if args.sin_hablantes:
        cfg = replace(cfg, diarizar=False)
    if args.hablantes:
        cfg = replace(cfg, min_hablantes=args.hablantes, max_hablantes=args.hablantes)

    fallidos = 0
    for archivo in args.archivos:
        ruta = archivo.expanduser()
        print(f"\n=== {ruta.name} ===")
        try:
            for generado in transcribir_archivo(ruta, cfg, informar=print):
                print(f"  → {generado}")
        except ErrorDeProceso as error:
            print(f"  ✗ {error}", file=sys.stderr)
            fallidos += 1

    return 1 if fallidos else 0


if __name__ == "__main__":
    raise SystemExit(main())
