"""Configuración del transcriptor.

Los valores por defecto viven acá. `config.toml` (no versionado) los pisa,
y el token de HuggingFace sale de la variable de entorno `HF_TOKEN` o del
archivo `.env` — nunca del TOML, para que no termine en el repo por error.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

# Extensiones que el vigía considera material transcribible. PyAV decodifica
# tanto audio como video, así que un .mov de una reunión grabada entra igual.
EXTENSIONES = frozenset({
    ".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff",
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg",
})

POR_DEFECTO: dict[str, object] = {
    "carpeta_vigilada": "~/Downloads/reuniones",
    "carpeta_salida": "~/Transcripciones",
    "modelo": "large-v3",
    "idioma": "es",
    "computo": "int8",
    "hilos": 0,                      # 0 = todos los núcleos disponibles
    "intervalo_segundos": 20,
    "espera_estabilidad_segundos": 10,
    "diarizar": True,
    "dispositivo_diarizacion": "cpu",
    "min_hablantes": 0,              # 0 = que lo decida el modelo
    "max_hablantes": 0,
    "formatos_salida": ["txt", "srt", "md"],
}


class ErrorDeConfig(Exception):
    """Configuración inválida o incompleta."""


@dataclass(frozen=True)
class Config:
    carpeta_vigilada: Path
    carpeta_salida: Path
    modelo: str
    idioma: str
    computo: str
    hilos: int
    intervalo_segundos: int
    espera_estabilidad_segundos: int
    diarizar: bool
    dispositivo_diarizacion: str
    min_hablantes: int | None
    max_hablantes: int | None
    formatos_salida: tuple[str, ...]
    token_hf: str | None = field(repr=False, default=None)

    @property
    def archivo_estado(self) -> Path:
        return self.carpeta_salida / ".estado.json"


def _leer_dotenv(ruta: Path) -> dict[str, str]:
    """Parser mínimo de .env. Evita sumar una dependencia por tres líneas."""
    if not ruta.is_file():
        return {}
    valores: dict[str, str] = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        valores[clave.strip()] = valor.strip().strip("\"'")
    return valores


def _opcional_positivo(valor: object) -> int | None:
    """0 y None significan 'sin restricción' para el conteo de hablantes."""
    numero = int(valor or 0)
    return numero if numero > 0 else None


def cargar(ruta_config: Path | None = None) -> Config:
    ruta_config = ruta_config or RAIZ / "config.toml"
    valores = dict(POR_DEFECTO)

    if ruta_config.is_file():
        with ruta_config.open("rb") as archivo:
            desconocidas = set(tomllib.load(archivo)) - set(POR_DEFECTO)
        with ruta_config.open("rb") as archivo:
            valores.update(tomllib.load(archivo))
        if desconocidas:
            raise ErrorDeConfig(
                f"Claves no reconocidas en {ruta_config.name}: "
                f"{', '.join(sorted(desconocidas))}"
            )

    entorno = {**_leer_dotenv(RAIZ / ".env"), **os.environ}
    token = entorno.get("HF_TOKEN") or None

    formatos = tuple(valores["formatos_salida"])  # type: ignore[arg-type]
    if invalidos := set(formatos) - {"txt", "srt", "md"}:
        raise ErrorDeConfig(f"Formatos de salida no soportados: {', '.join(sorted(invalidos))}")

    return Config(
        carpeta_vigilada=Path(str(valores["carpeta_vigilada"])).expanduser(),
        carpeta_salida=Path(str(valores["carpeta_salida"])).expanduser(),
        modelo=str(valores["modelo"]),
        idioma=str(valores["idioma"]),
        computo=str(valores["computo"]),
        hilos=int(valores["hilos"]) or (os.cpu_count() or 4),  # type: ignore[arg-type]
        intervalo_segundos=int(valores["intervalo_segundos"]),  # type: ignore[arg-type]
        espera_estabilidad_segundos=int(valores["espera_estabilidad_segundos"]),  # type: ignore[arg-type]
        diarizar=bool(valores["diarizar"]),
        dispositivo_diarizacion=str(valores["dispositivo_diarizacion"]),
        min_hablantes=_opcional_positivo(valores["min_hablantes"]),
        max_hablantes=_opcional_positivo(valores["max_hablantes"]),
        formatos_salida=formatos,
        token_hf=token,
    )
