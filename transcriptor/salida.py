"""Escritura de los archivos de salida: .txt, .srt y .md."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from asr import Palabra
from audio import formatear_duracion
from hablantes import Bloque

MAX_SEGUNDOS_SUBTITULO = 6.0
MAX_CARACTERES_SUBTITULO = 84


@dataclass(frozen=True)
class Metadatos:
    origen: Path
    duracion: float
    idioma: str
    modelo: str
    con_hablantes: bool
    procesado: datetime


def _reloj(segundos: float) -> str:
    total = int(segundos)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def _reloj_srt(segundos: float) -> str:
    milis = int(round(segundos * 1000))
    horas, resto = divmod(milis, 3_600_000)
    minutos, resto = divmod(resto, 60_000)
    segs, milis = divmod(resto, 1000)
    return f"{horas:02d}:{minutos:02d}:{segs:02d},{milis:03d}"


def _cortar_en_subtitulos(bloque: Bloque) -> list[list[Palabra]]:
    """Parte una intervención larga en fragmentos legibles como subtítulo."""
    fragmentos: list[list[Palabra]] = []
    actual: list[Palabra] = []

    for palabra in bloque.palabras:
        tentativo = actual + [palabra]
        largo = sum(len(p.texto) + 1 for p in tentativo)
        duracion = palabra.fin - tentativo[0].inicio
        if actual and (largo > MAX_CARACTERES_SUBTITULO or duracion > MAX_SEGUNDOS_SUBTITULO):
            fragmentos.append(actual)
            actual = [palabra]
        else:
            actual = tentativo

    if actual:
        fragmentos.append(actual)
    return fragmentos


def escribir_txt(destino: Path, bloques: list[Bloque], meta: Metadatos) -> None:
    lineas = [
        f"{meta.origen.name}",
        f"Duración: {formatear_duracion(meta.duracion)} · "
        f"Idioma: {meta.idioma} · Modelo: {meta.modelo}",
        f"Transcrito el {meta.procesado:%d/%m/%Y a las %H:%M}",
        "=" * 72,
        "",
    ]
    for bloque in bloques:
        prefijo = f"[{_reloj(bloque.inicio)}]"
        if meta.con_hablantes:
            lineas.append(f"{prefijo} {bloque.hablante}: {bloque.texto}")
        else:
            lineas.append(f"{prefijo} {bloque.texto}")
        lineas.append("")

    destino.write_text("\n".join(lineas), encoding="utf-8")


def escribir_srt(destino: Path, bloques: list[Bloque], meta: Metadatos) -> None:
    partes: list[str] = []
    numero = 1
    for bloque in bloques:
        for fragmento in _cortar_en_subtitulos(bloque):
            texto = " ".join(p.texto for p in fragmento)
            if meta.con_hablantes:
                texto = f"{bloque.hablante}: {texto}"
            partes.append(
                f"{numero}\n"
                f"{_reloj_srt(fragmento[0].inicio)} --> {_reloj_srt(fragmento[-1].fin)}\n"
                f"{texto}\n"
            )
            numero += 1

    destino.write_text("\n".join(partes), encoding="utf-8")


def escribir_md(destino: Path, bloques: list[Bloque], meta: Metadatos) -> None:
    intervinientes = sorted({b.hablante for b in bloques})
    lineas = [
        f"# {meta.origen.stem}",
        "",
        f"- **Archivo original:** `{meta.origen.name}`",
        f"- **Duración:** {formatear_duracion(meta.duracion)}",
        f"- **Idioma detectado:** {meta.idioma}",
        f"- **Modelo:** `{meta.modelo}`",
        f"- **Procesado:** {meta.procesado:%d/%m/%Y %H:%M}",
    ]
    if meta.con_hablantes:
        lineas.append(f"- **Voces detectadas:** {len(intervinientes)}")
    lineas += ["", "---", ""]

    for bloque in bloques:
        if meta.con_hablantes:
            lineas.append(f"**{bloque.hablante}** · `{_reloj(bloque.inicio)}`")
        else:
            lineas.append(f"`{_reloj(bloque.inicio)}`")
        lineas += ["", bloque.texto, ""]

    destino.write_text("\n".join(lineas), encoding="utf-8")


ESCRITORES = {"txt": escribir_txt, "srt": escribir_srt, "md": escribir_md}


def escribir_todo(
    carpeta: Path, base: str, bloques: list[Bloque], meta: Metadatos,
    formatos: tuple[str, ...],
) -> list[Path]:
    carpeta.mkdir(parents=True, exist_ok=True)
    generados: list[Path] = []
    for formato in formatos:
        destino = carpeta / f"{base}.{formato}"
        ESCRITORES[formato](destino, bloques, meta)
        generados.append(destino)
    return generados
