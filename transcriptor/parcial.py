"""Avance guardado de una transcripción larga.

Una reunión de cuatro horas puede llevar varias horas de proceso. Guardar solo
al final significa que cualquier corte —cerrar la terminal, quedarse sin
batería, dormir la Mac— tira todo a la basura. Acá se guarda tramo por tramo.

Junto al avance se conserva el WAV ya extraído, porque volver a decodificar un
archivo de un giga cada vez que se reanuda es tiempo regalado.
"""
from __future__ import annotations

import json
from pathlib import Path

from asr import Palabra


class Parcial:
    def __init__(self, carpeta: Path, origen: Path) -> None:
        self.carpeta = carpeta
        self.origen = origen
        self.ruta = carpeta / f"{origen.stem}.json"
        self.wav = carpeta / f"{origen.stem}.wav"

    @property
    def _huella(self) -> str:
        """Identifica al archivo de origen, no solo a su nombre.

        Si la grabación se reexporta, el avance viejo deja de aplicar y hay que
        empezar de cero en vez de mezclar dos audios distintos.
        """
        info = self.origen.stat()
        return f"{info.st_size}|{int(info.st_mtime)}"

    def cargar(self) -> tuple[int, list[Palabra], str]:
        """Devuelve (tramos ya hechos, palabras acumuladas, idioma detectado)."""
        if not self.ruta.is_file():
            return 0, [], ""
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0, [], ""

        if datos.get("huella") != self._huella:
            return 0, [], ""

        palabras = [Palabra(i, f, t) for i, f, t in datos.get("palabras", [])]
        return int(datos.get("tramos_hechos", 0)), palabras, str(datos.get("idioma", ""))

    def guardar(self, tramos_hechos: int, palabras: list[Palabra], idioma: str) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        contenido = {
            "origen": str(self.origen),
            "huella": self._huella,
            "tramos_hechos": tramos_hechos,
            "idioma": idioma,
            "palabras": [[p.inicio, p.fin, p.texto] for p in palabras],
        }
        temporal = self.ruta.with_suffix(".json.tmp")
        temporal.write_text(json.dumps(contenido, ensure_ascii=False), encoding="utf-8")
        temporal.replace(self.ruta)  # atómico: un corte nunca deja un JSON a medias

    def limpiar(self) -> None:
        """Se llama al terminar bien: el avance ya no hace falta."""
        for ruta in (self.ruta, self.wav, self.ruta.with_suffix(".json.tmp")):
            ruta.unlink(missing_ok=True)
