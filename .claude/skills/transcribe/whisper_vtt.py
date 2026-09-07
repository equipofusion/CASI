#!/usr/bin/env python3
"""Transcribe un archivo de audio a WebVTT usando faster-whisper.

Backend de respaldo de transcribe.sh cuando whisper.cpp no esta instalado.
Se ejecuta dentro del venv cacheado que crea transcribe.sh.
"""

from __future__ import annotations

import argparse
import sys


def format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, help="archivo de audio de entrada")
    parser.add_argument("--output", required=True, help="archivo .vtt de salida")
    parser.add_argument("--model", default="small", help="modelo de faster-whisper")
    parser.add_argument("--language", default=None, help="codigo ISO del idioma; omitir para autodetectar")
    args = parser.parse_args()

    from faster_whisper import WhisperModel

    print(f"[whisper_vtt] cargando modelo '{args.model}' (se descarga la primera vez)...", file=sys.stderr)
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    segments, info = model.transcribe(
        args.audio,
        language=args.language,
        vad_filter=True,
        beam_size=5,
    )
    print(
        f"[whisper_vtt] idioma: {info.language} (confianza {info.language_probability:.2f}), "
        f"duracion: {info.duration:.0f}s",
        file=sys.stderr,
    )

    written = 0
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write("WEBVTT\n\n")
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            fh.write(f"{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}\n")
            fh.write(f"{text}\n\n")
            written += 1
            if written % 25 == 0:
                print(f"[whisper_vtt] {written} segmentos...", file=sys.stderr)

    if written == 0:
        print("[whisper_vtt] ERROR: no se genero ningun segmento.", file=sys.stderr)
        return 1

    print(f"[whisper_vtt] {written} segmentos escritos en {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
