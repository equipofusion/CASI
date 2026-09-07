#!/usr/bin/env bash
# Instalación en macOS. Idempotente: se puede volver a correr sin romper nada.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    echo "Falta uv. Instalalo con:"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "…y volvé a correr este script (puede requerir abrir una terminal nueva)."
    exit 1
fi

echo "==> Creando entorno virtual con Python 3.11"
uv venv --python 3.11 .venv

echo "==> Instalando dependencias (descarga ~2 GB la primera vez, tené paciencia)"
uv pip install --python .venv/bin/python -r pyproject.toml

[ -f config.toml ] || { cp config.ejemplo.toml config.toml; echo "==> Creado config.toml"; }
[ -f .env ]        || { cp .env.ejemplo .env;               echo "==> Creado .env"; }

CARPETA_VIGILADA=$(grep -E '^carpeta_vigilada' config.toml | cut -d'"' -f2)
mkdir -p "${CARPETA_VIGILADA/#\~/$HOME}"

cat <<'FIN'

==> Listo.

Pasos que faltan, una sola vez:

  1. Token de HuggingFace (solo si querés separar por hablante):
     - Creá una cuenta en huggingface.co
     - Aceptá las condiciones en estas dos páginas:
         huggingface.co/pyannote/speaker-diarization-3.1
         huggingface.co/pyannote/segmentation-3.0
     - Generá un token de lectura en huggingface.co/settings/tokens
     - Pegalo en el archivo .env  ->  HF_TOKEN=hf_xxxxx

  2. Probá con un archivo:
       ./.venv/bin/python transcribir.py "ruta/a/tu/reunion.m4a"

  3. Dejá el vigía corriendo:
       ./.venv/bin/python vigilar.py

FIN
