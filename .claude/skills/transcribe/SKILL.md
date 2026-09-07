---
name: transcribe
description: Transcribe y analiza críticamente audio/video. Acepta un archivo .vtt/.srt/.txt ya transcrito, un archivo de audio o video (.m4a, .mp3, .wav, .ogg, .flac, .aac, .mp4, .mov), o una URL (YouTube u otro sitio soportado por yt-dlp). Genera un análisis estructurado en markdown con timestamps, notas de evidencia y falacias lógicas. Usar cuando el usuario pida transcribir, resumir o analizar una charla, entrevista, reunión, video o audio.
argument-hint: <archivo-o-url>
---

Sos un asistente de análisis de transcripciones. Tu trabajo es transcribir (si
hace falta) y después analizar críticamente una transcripción, produciendo un
resumen estructurado en markdown.

El directorio de esta skill (referido más abajo como `SKILL_DIR`) es
`.claude/skills/transcribe/` relativo a la raíz del repositorio.

## Manejo del input

El usuario provee un único argumento: `$ARGUMENTS`

Determiná el tipo de input y actuá en consecuencia:

### 1. Si el input ya es una transcripción (`.vtt`, `.srt`, `.txt`)
- Usalo directamente. Saltá al paso **Análisis**.
- Si es `.srt` o `.txt` sin timestamps, hacé el análisis igual pero omití las
  citas `[HH:MM:SS]` donde no haya información temporal disponible, y aclaralo
  en una nota al pie del análisis.

### 2. Si el input es un archivo de audio/video o una URL
Ejecutá el script de transcripción con Bash desde la raíz del repositorio:

```
.claude/skills/transcribe/transcribe.sh "<archivo-o-url>"
```

- La primera corrida instala las dependencias que falten (ffmpeg, yt-dlp,
  faster-whisper) y descarga el modelo. Puede tardar varios minutos; usá un
  timeout amplio en la llamada de Bash (por ejemplo 600000 ms).
- El script imprime en la última línea de stdout la ruta del `.vtt` generado,
  con el prefijo `VTT_OUTPUT=`. Usá esa ruta; no adivines.
- Para audio en castellano u otro idioma que no sea inglés, pasá el idioma:
  `WHISPER_LANGUAGE=es .claude/skills/transcribe/transcribe.sh "<archivo-o-url>"`.
  Si no se especifica, el modelo autodetecta el idioma.
- Si el script falla porque no puede instalar dependencias o descargar el
  modelo, informale el error al usuario y ofrecele la alternativa de pasar una
  transcripción ya hecha (`.vtt`, `.srt` o `.txt`); no inventes contenido.

Seguí al paso **Análisis**.

## Análisis

Una vez que tenés el archivo de transcripción:

1. **Inferí el título** desde el nombre del archivo. Convertilo a un título
   natural y legible (por ejemplo, `Mi_Video_Copado.vtt` puede ser "Mi Video
   Copado"). Usá tu criterio.

2. **Leé la plantilla del prompt** desde `SKILL_DIR/ANALYSIS_PROMPT.md`.

3. **Reemplazá `[TITLE]`** en el prompt por el título inferido, y **`[SOURCE]`**
   por el valor original de `$ARGUMENTS` (la URL o ruta que dio el usuario).

4. **Leé el archivo de transcripción completo** con la herramienta Read. Si es
   muy grande, leelo por partes con `offset` y `limit` hasta haber ingerido
   todo. No empieces a resumir hasta haber leído todo.

5. **Verificá si el archivo de salida ya existe.** El nombre de salida es el
   mismo que el de la transcripción pero con extensión `.md`. Si ese `.md` ya
   existe, preguntale al usuario si prefiere:
   - **Sobrescribir** el archivo existente
   - **Renombrar** (pedile el nombre nuevo)

6. **Generá el análisis** siguiendo todas las instrucciones de la plantilla.
   Escribí el resultado en el archivo `.md` con la herramienta Write.

## Notas importantes

- El análisis debe seguir exactamente el formato estructurado de la plantilla.
- Citá siempre timestamps en formato `[HH:MM:SS]` o `[HH:MM:SS--HH:MM:SS]`.
- Mantené un tono neutral y descriptivo en todo el análisis.
- El `.md` de salida va en el mismo directorio que el archivo de transcripción.
- Escribí el análisis en el idioma del contenido transcrito, salvo que el
  usuario pida otro.
- Los archivos de media descargados y las transcripciones intermedias no van
  versionados: quedan cubiertos por `.gitignore`.

## Origen

Adaptado de [jftuga/transcript-critic](https://github.com/jftuga/transcript-critic)
(MIT, © 2026 John Taylor). Ver `SKILL_DIR/README.md` para el detalle de qué se
cambió respecto del upstream.
