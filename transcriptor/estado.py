"""Registro de lo ya transcrito.

Evita que el vigía reprocese el mismo archivo en cada vuelta. La clave incluye
tamaño y fecha de modificación: si volvés a exportar la grabación, cambia la
clave y se transcribe de nuevo, que es lo que uno espera.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class Estado:
    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        self._registros: dict[str, dict] = {}
        if ruta.is_file():
            try:
                self._registros = json.loads(ruta.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # Un estado corrupto no debe frenar el servicio: peor caso,
                # se retranscribe algo que ya estaba hecho.
                self._registros = {}

    @staticmethod
    def clave(archivo: Path) -> str:
        info = archivo.stat()
        return f"{archivo.resolve()}|{info.st_size}|{int(info.st_mtime)}"

    def ya_procesado(self, archivo: Path) -> bool:
        return self.clave(archivo) in self._registros

    def marcar(self, archivo: Path, salidas: list[Path]) -> None:
        self._registros[self.clave(archivo)] = {
            "archivo": str(archivo),
            "salidas": [str(s) for s in salidas],
            "fecha": datetime.now().isoformat(timespec="seconds"),
        }
        self._guardar()

    def marcar_fallido(self, archivo: Path, motivo: str) -> None:
        self._registros[self.clave(archivo)] = {
            "archivo": str(archivo),
            "error": motivo,
            "fecha": datetime.now().isoformat(timespec="seconds"),
        }
        self._guardar()

    def _guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = self.ruta.with_suffix(".json.tmp")
        temporal.write_text(
            json.dumps(self._registros, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporal.replace(self.ruta)  # atómico: nunca queda un JSON a medio escribir
