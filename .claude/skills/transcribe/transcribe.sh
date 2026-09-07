#!/usr/bin/env bash
#
# Transcribe audio/video a WebVTT.
#
# Acepta un archivo local (audio o video) o una URL soportada por yt-dlp.
# Los archivos locales se convierten a MP3 con ffmpeg; las URLs se descargan y
# se extrae el audio con yt-dlp. La transcripcion la hace whisper.cpp si esta
# instalado, y si no, faster-whisper en un venv cacheado que este script crea
# la primera vez.
#
# Uso: ./transcribe.sh <archivo-o-url>
#
# La ultima linea de stdout es "VTT_OUTPUT=<ruta>" con la ruta del .vtt.
# Todo el resto del output va a stderr.
#
# Variables de entorno:
#   WHISPER_LANGUAGE  Codigo ISO del idioma (ej. "es", "en"). Default: autodetectar.
#   WHISPER_MODEL     Modelo de faster-whisper. Default: "small".
#   WHISPER_ROOT      Raiz de whisper.cpp. Default: $HOME/github.com/ggerganov/whisper.cpp
#   WHISPER_CPP_MODEL Ruta al .bin de whisper.cpp. Default: $WHISPER_ROOT/models/ggml-medium.en.bin
#   OUTPUT_DIR        Donde dejar los archivos generados. Default: directorio actual.
#   PREFER_SUBTITLES  Para URLs, usar los subtitulos publicados si existen en vez
#                     de transcribir. "1" (default) o "0" para forzar whisper.
#   SUB_LANGS         Idiomas de subtitulo preferidos, separados por coma.
#
# Adaptado de https://github.com/jftuga/transcript-critic (MIT, (c) 2026 John Taylor)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE_DIR="${XDG_CACHE_HOME:-${HOME}/.cache}/transcribe-skill"
VENV_DIR="${CACHE_DIR}/venv"
VENV_PY="${VENV_DIR}/bin/python"

WHISPER_MODEL="${WHISPER_MODEL:-small}"
WHISPER_LANGUAGE="${WHISPER_LANGUAGE:-}"
WHISPER_ROOT="${WHISPER_ROOT:-${HOME}/github.com/ggerganov/whisper.cpp}"
WHISPER_CPP_BIN="${WHISPER_ROOT}/build/bin/whisper-cli"
WHISPER_CPP_MODEL="${WHISPER_CPP_MODEL:-${WHISPER_ROOT}/models/ggml-medium.en.bin}"
OUTPUT_DIR="${OUTPUT_DIR:-$PWD}"
PREFER_SUBTITLES="${PREFER_SUBTITLES:-1}"
SUB_LANGS="${SUB_LANGS:-${WHISPER_LANGUAGE:+${WHISPER_LANGUAGE},}es,en}"

log() { echo "[transcribe] $*" >&2; }
die() { echo "[transcribe] ERROR: $*" >&2; exit 1; }

# --- dependencias -----------------------------------------------------------

maybe_sudo() {
    if [[ "$(id -u)" -eq 0 ]]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        return 1
    fi
}

ensure_ffmpeg() {
    command -v ffmpeg >/dev/null 2>&1 && return 0
    log "ffmpeg no encontrado, intentando instalarlo..."
    if command -v apt-get >/dev/null 2>&1; then
        maybe_sudo env DEBIAN_FRONTEND=noninteractive apt-get update -qq >&2 || true
        maybe_sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg >&2 || true
    elif command -v brew >/dev/null 2>&1; then
        brew install ffmpeg >&2 || true
    fi
    command -v ffmpeg >/dev/null 2>&1 \
        || die "no se pudo instalar ffmpeg. Instalalo a mano y volve a intentar."
}

ensure_venv() {
    if [[ -x "${VENV_PY}" ]]; then
        return 0
    fi
    log "creando entorno de Python en ${VENV_DIR} (solo la primera vez)..."
    mkdir -p "${CACHE_DIR}"
    if command -v uv >/dev/null 2>&1; then
        uv venv "${VENV_DIR}" >&2
    else
        python3 -m venv "${VENV_DIR}" >&2
    fi
    [[ -x "${VENV_PY}" ]] || die "no se pudo crear el venv en ${VENV_DIR}"
}

venv_install() {
    # venv_install <paquete> [<paquete>...]
    ensure_venv
    log "instalando: $*"
    if command -v uv >/dev/null 2>&1; then
        VIRTUAL_ENV="${VENV_DIR}" uv pip install --quiet "$@" >&2
    else
        "${VENV_PY}" -m pip install --quiet --upgrade pip >&2
        "${VENV_PY}" -m pip install --quiet "$@" >&2
    fi
}

ensure_ytdlp() {
    if command -v yt-dlp >/dev/null 2>&1; then
        YTDLP=(yt-dlp)
        return 0
    fi
    ensure_venv
    if ! "${VENV_PY}" -c "import yt_dlp" >/dev/null 2>&1; then
        venv_install yt-dlp
    fi
    YTDLP=("${VENV_PY}" -m yt_dlp)
}

# Elige backend de transcripcion. Deja el resultado en WHISPER_BACKEND.
select_backend() {
    if [[ -x "${WHISPER_CPP_BIN}" && -f "${WHISPER_CPP_MODEL}" ]]; then
        WHISPER_BACKEND="whisper.cpp"
    else
        WHISPER_BACKEND="faster-whisper"
        ensure_venv
        if ! "${VENV_PY}" -c "import faster_whisper" >/dev/null 2>&1; then
            venv_install faster-whisper
        fi
    fi
    log "backend de transcripcion: ${WHISPER_BACKEND}"
}

# --- audio ------------------------------------------------------------------

convert_to_mp3() {
    local RAW=$1
    local BASE MP3
    BASE="$(basename "${RAW}")"
    MP3="${OUTPUT_DIR}/${BASE%.*}.mp3"

    if [[ "${RAW}" == *.mp3 && "$(cd "$(dirname "${RAW}")" && pwd)" == "$(cd "${OUTPUT_DIR}" && pwd)" ]]; then
        echo "${RAW}"
        return
    fi
    if [[ -e "${MP3}" ]]; then
        log "el mp3 ya existe, lo reuso: ${MP3}"
        echo "${MP3}"
        return
    fi

    ensure_ffmpeg
    log "convirtiendo a mp3: ${RAW}"
    ffmpeg -nostdin -loglevel error -y -i "${RAW}" -vn -codec:a libmp3lame -q:a 2 "${MP3}" >&2
    echo "${MP3}"
}

download_audio() {
    local URL=$1
    local MARKER="${CACHE_DIR}/.dl-$$"

    ensure_ffmpeg
    ensure_ytdlp
    mkdir -p "${CACHE_DIR}" "${OUTPUT_DIR}"
    log "descargando audio de: ${URL}"

    "${YTDLP[@]}" \
        --no-playlist \
        --restrict-filenames \
        --quiet --no-warnings --progress \
        -o "${OUTPUT_DIR}/%(title).80s.%(ext)s" \
        --extract-audio \
        --audio-format mp3 \
        --audio-quality 0 \
        --print-to-file after_move:filepath "${MARKER}" \
        "${URL}" >&2

    [[ -s "${MARKER}" ]] || die "yt-dlp no produjo ningun archivo de audio."
    local MP3
    MP3="$(tail -1 "${MARKER}")"
    rm -f "${MARKER}"
    [[ -e "${MP3}" ]] || die "el archivo descargado no existe: ${MP3}"
    echo "${MP3}"
}

# Baja los subtitulos ya publicados del video, si existen. Imprime la ruta del
# .vtt en stdout y devuelve 0; devuelve 1 si el video no tiene subtitulos.
try_subtitle_langs() {
    local URL=$1 LANGS=$2 TMPD=$3
    "${YTDLP[@]}" \
        --skip-download \
        --write-subs --write-auto-subs \
        --sub-langs "${LANGS}" \
        --sub-format "vtt/best" --convert-subs vtt \
        --no-playlist --restrict-filenames \
        --quiet --no-warnings \
        -o "${TMPD}/%(title).80s.%(ext)s" \
        "${URL}" >&2 || return 1
    find "${TMPD}" -name '*.vtt' -type f | sort | head -1
}

fetch_subtitles() {
    local URL=$1 TMPD FOUND BASE DEST
    ensure_ytdlp
    mkdir -p "${CACHE_DIR}" "${OUTPUT_DIR}"
    TMPD="$(mktemp -d "${CACHE_DIR}/subs.XXXXXX")"

    log "buscando subtitulos publicados (${SUB_LANGS})..."
    FOUND="$(try_subtitle_langs "${URL}" "${SUB_LANGS}" "${TMPD}" || true)"
    if [[ -z "${FOUND}" ]]; then
        log "sin subtitulos en esos idiomas, probando cualquier idioma..."
        FOUND="$(try_subtitle_langs "${URL}" ".*" "${TMPD}" || true)"
    fi
    if [[ -z "${FOUND}" ]]; then
        rm -rf "${TMPD}"
        return 1
    fi

    # Saca el sufijo de idioma del nombre: "Charla.es.vtt" -> "Charla.vtt"
    BASE="$(basename "${FOUND}")"
    BASE="$(sed -E 's/\.[A-Za-z]{2,3}(-[A-Za-z0-9_-]+)?\.vtt$/.vtt/' <<< "${BASE}")"
    DEST="${OUTPUT_DIR}/${BASE}"
    mv -f "${FOUND}" "${DEST}"
    rm -rf "${TMPD}"

    # Los subtitulos automaticos vienen con tags de karaoke y lineas repetidas.
    python3 "${SCRIPT_DIR}/clean_vtt.py" "${DEST}" >&2 || return 1
    log "usando subtitulos publicados: ${DEST}"
    echo "${DEST}"
}

# --- transcripcion ----------------------------------------------------------

transcribe() {
    local MP3=$1
    local BASENAME="${MP3%.*}"
    local VTT="${BASENAME}.vtt"

    if [[ -s "${VTT}" ]]; then
        log "el .vtt ya existe, lo reuso: ${VTT}"
        echo "${VTT}"
        return
    fi

    log "transcribiendo (esto puede tardar): ${MP3}"

    if [[ "${WHISPER_BACKEND}" == "whisper.cpp" ]]; then
        local LANG_ARGS=()
        [[ -n "${WHISPER_LANGUAGE}" ]] && LANG_ARGS=(--language "${WHISPER_LANGUAGE}")
        "${WHISPER_CPP_BIN}" \
            --output-txt \
            --output-vtt \
            --output-file "${BASENAME}" \
            --model "${WHISPER_CPP_MODEL}" \
            "${LANG_ARGS[@]}" \
            "${MP3}" >&2
    else
        "${VENV_PY}" "${SCRIPT_DIR}/whisper_vtt.py" \
            --audio "${MP3}" \
            --output "${VTT}" \
            --model "${WHISPER_MODEL}" \
            ${WHISPER_LANGUAGE:+--language "${WHISPER_LANGUAGE}"} >&2
    fi

    [[ -s "${VTT}" ]] || die "la transcripcion no genero ${VTT}"

    # Saca lineas vacias del .vtt para reducir tokens en el analisis.
    local TMP="${VTT}.tmp"
    grep -v '^[[:space:]]*$' "${VTT}" > "${TMP}" && mv -f "${TMP}" "${VTT}"

    log "listo: ${VTT}"
    echo "${VTT}"
}

# --- main -------------------------------------------------------------------

main() {
    [[ $# -ge 1 ]] || { echo "Uso: $0 <archivo-o-url>" >&2; exit 1; }
    local INPUT=$1
    mkdir -p "${OUTPUT_DIR}"

    local MP3 VTT
    if [[ "${INPUT}" == http://* || "${INPUT}" == https://* ]]; then
        if [[ "${PREFER_SUBTITLES}" != "0" ]]; then
            VTT="$(fetch_subtitles "${INPUT}" || true)"
            if [[ -n "${VTT}" && -s "${VTT}" ]]; then
                echo "VTT_OUTPUT=${VTT}"
                return 0
            fi
            log "no hay subtitulos publicados; transcribo el audio."
        fi
        MP3="$(download_audio "${INPUT}")"
    else
        [[ -e "${INPUT}" ]] || die "archivo no encontrado: ${INPUT}"
        MP3="$(convert_to_mp3 "${INPUT}")"
    fi

    select_backend

    VTT="$(transcribe "${MP3}")"
    echo "VTT_OUTPUT=${VTT}"
}

main "$@"
