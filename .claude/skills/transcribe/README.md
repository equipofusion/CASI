# Skill `/transcribe`

Transcribe y analiza críticamente audio/video, y deja un análisis estructurado
en markdown (resumen, términos clave, resumen sección por sección con
timestamps, notas de evidencia, falacias lógicas y puntos flojos).

Adaptado de [jftuga/transcript-critic](https://github.com/jftuga/transcript-critic)
(MIT, © 2026 John Taylor), commit `d34ec0d`. El texto del análisis
(`ANALYSIS_PROMPT.md`) es el del upstream, sin cambios.

## Uso

```
/transcribe https://www.youtube.com/watch?v=XXXX
/transcribe reunion_comision.m4a
/transcribe charla.vtt
```

## Cómo resuelve la transcripción

En orden, de más barato a más caro:

1. **¿Ya es una transcripción?** (`.vtt`, `.srt`, `.txt`) → se analiza directo.
2. **¿Es una URL con subtítulos publicados?** → los baja con `yt-dlp`, los
   limpia con `clean_vtt.py` y los analiza. No descarga audio ni modelo.
3. **Si no** → baja/convierte el audio y lo transcribe con Whisper.

Para el paso 3 usa `whisper.cpp` si está instalado (mismas rutas y variables
que el upstream); si no, arma un venv en `~/.cache/transcribe-skill/` con
`faster-whisper` y baja el modelo la primera vez.

## Variables de entorno

| Variable | Default | Para qué |
| --- | --- | --- |
| `WHISPER_LANGUAGE` | autodetectar | Idioma del audio (`es`, `en`, …) |
| `WHISPER_MODEL` | `small` | Modelo de faster-whisper (`tiny`…`large-v3`) |
| `PREFER_SUBTITLES` | `1` | `0` fuerza transcribir aunque haya subtítulos |
| `SUB_LANGS` | `es,en` | Idiomas de subtítulo preferidos |
| `OUTPUT_DIR` | directorio actual | Dónde dejar los archivos generados |
| `WHISPER_ROOT` | `~/github.com/ggerganov/whisper.cpp` | Raíz de whisper.cpp |
| `WHISPER_CPP_MODEL` | `$WHISPER_ROOT/models/ggml-medium.en.bin` | Modelo de whisper.cpp |

Ejemplo: `WHISPER_LANGUAGE=es WHISPER_MODEL=medium .claude/skills/transcribe/transcribe.sh audio.m4a`

## Diferencias respecto del upstream

- **Skill de proyecto, no global.** Vive en `.claude/skills/transcribe/` dentro
  del repo, así viaja con él y sobrevive a las sesiones efímeras de Claude Code
  on the web. El `install.sh` del upstream copiaba a `~/.claude/skills/`, que en
  esos entornos se pierde al terminar la sesión.
- **Sin rutas hardcodeadas.** El upstream apuntaba a
  `~/github.com/jftuga/transcript-critic/`; acá todo se resuelve relativo al
  directorio de la skill.
- **Dependencias automáticas.** `transcribe.sh` instala lo que falte (ffmpeg,
  yt-dlp, faster-whisper) en vez de exigir whisper.cpp compilado a mano.
- **Backend de respaldo.** `whisper_vtt.py` transcribe con faster-whisper cuando
  no hay whisper.cpp.
- **Atajo de subtítulos.** `clean_vtt.py` + el paso 2 de arriba: para videos que
  ya tienen subtítulos, se saltea la transcripción entera.
- **Multi-idioma.** El upstream fijaba `ggml-medium.en.bin` (solo inglés). Acá
  el idioma se autodetecta o se fija con `WHISPER_LANGUAGE`.
- **Contrato de salida explícito.** El script imprime `VTT_OUTPUT=<ruta>` en la
  última línea, en vez de que Claude adivine cuál es el `.vtt` más reciente del
  directorio.

## Requisitos de red

Los pasos 2 y 3 salen a internet: `yt-dlp` al sitio del video, y faster-whisper
a `huggingface.co` para bajar el modelo la primera vez. Si el entorno tiene una
política de red restrictiva que bloquea esos hosts, la skill igual sirve para el
paso 1: pasale un `.vtt`, `.srt` o `.txt` ya transcrito y hace el análisis.

## Limitaciones conocidas

- `clean_vtt.py` deduplica líneas repetidas dentro de una ventana corta, que es
  lo que hace falta para los subtítulos automáticos de YouTube. Si el hablante
  repite literalmente la misma frase en cues consecutivos, esa repetición se
  colapsa.
- Los subtítulos automáticos no traen puntuación ni distinguen hablantes. Para
  material donde eso importe, conviene `PREFER_SUBTITLES=0`.
