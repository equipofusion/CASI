#!/usr/bin/env python3
"""Normaliza un archivo WebVTT para que sea legible y barato de analizar.

Pensado sobre todo para los subtitulos automaticos de YouTube, que vienen con
"rolling captions": cada cue repite la ultima linea del cue anterior, con tags
de karaoke intercalados. Este script saca los tags, las lineas repetidas y las
directivas de posicionamiento, y deja un cue por bloque de texto nuevo.

Uso: clean_vtt.py <entrada.vtt> [salida.vtt]
Si no se pasa salida, reescribe la entrada en el lugar.
"""

from __future__ import annotations

import re
import sys

TIMESTAMP_RE = re.compile(
    r"^\s*(\d{1,3}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
    r"\s*-->\s*"
    r"(\d{1,3}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
)
TAG_RE = re.compile(r"<[^>]*>")


def normalize_timestamp(value: str) -> str:
    value = value.replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:  # MM:SS.mmm -> HH:MM:SS.mmm
        parts.insert(0, "00")
    hours, minutes, rest = parts
    return f"{int(hours):02d}:{int(minutes):02d}:{rest}"


def parse_cues(text: str):
    """Devuelve una lista de (inicio, fin, [lineas de texto])."""
    cues = []
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        match = TIMESTAMP_RE.match(line)
        if match:
            if current:
                cues.append(current)
            current = (normalize_timestamp(match.group(1)), normalize_timestamp(match.group(2)), [])
            continue
        if current is None:
            continue  # cabecera WEBVTT, NOTE, STYLE, numeros de cue sueltos
        stripped = TAG_RE.sub("", line).strip()
        if stripped:
            current[2].append(stripped)
    if current:
        cues.append(current)
    return cues


def dedupe(cues):
    """Deja solo el texto nuevo de cada cue y descarta los que no aportan nada."""
    out = []
    recent: list[str] = []
    for start, end, lines in cues:
        fresh = []
        for line in lines:
            if line in recent:
                continue
            fresh.append(line)
            recent.append(line)
        del recent[:-8]  # ventana corta: solo evita el solapamiento inmediato
        if not fresh:
            continue
        text = " ".join(fresh)
        if out and out[-1][2] == text:
            out[-1] = (out[-1][0], end, text)  # mismo texto seguido: extender el cue
            continue
        out.append((start, end, text))
    return out


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        print(__doc__, file=sys.stderr)
        return 2
    src = argv[1]
    dst = argv[2] if len(argv) == 3 else argv[1]

    with open(src, encoding="utf-8", errors="replace") as fh:
        cues = dedupe(parse_cues(fh.read()))

    if not cues:
        print(f"[clean_vtt] ERROR: no se encontraron cues en {src}", file=sys.stderr)
        return 1

    with open(dst, "w", encoding="utf-8") as fh:
        fh.write("WEBVTT\n\n")
        for start, end, text in cues:
            fh.write(f"{start} --> {end}\n{text}\n\n")

    print(f"[clean_vtt] {len(cues)} cues escritos en {dst}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
