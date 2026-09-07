# Transcriptor de reuniones

Servicio local de transcripción con separación por hablante. Dejás la grabación
en una carpeta y a los minutos aparece la transcripción en otra.

Corre **entero en tu Mac**: el audio nunca sale de la máquina. Para reuniones
con clientes eso no es un detalle menor.

## Qué hace

- Toma audio o video (`.m4a`, `.mp3`, `.wav`, `.mov`, `.mp4`, `.mkv`…). No
  importa el tamaño: un archivo de 30 MB o de 3 GB entran igual.
- Transcribe con **Whisper** (`faster-whisper`), optimizado para español.
- Separa **quién dijo qué** con **pyannote**.
- Escribe tres formatos: `.txt` (para leer), `.srt` (subtítulos) y `.md`
  (para pegar en Notion, Drive o traerme acá para armar la minuta).

## Instalación

Una sola vez:

```sh
cd transcriptor
./instalar.sh
```

El script pide `uv`. Si no lo tenés:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

La primera instalación baja alrededor de 2 GB (PyTorch y compañía). No hace
falta instalar ffmpeg: viene embebido en PyAV.

### Token de HuggingFace (solo para separar hablantes)

Los modelos de pyannote son gratuitos pero piden aceptar sus condiciones:

1. Creá una cuenta en [huggingface.co](https://huggingface.co).
2. Aceptá las condiciones en **las dos** páginas — si falta una, falla:
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
3. Generá un token de lectura en
   [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
4. Pegalo en `transcriptor/.env`:

```
HF_TOKEN=hf_xxxxxxxxxxxxxxxxx
```

Si preferís saltear todo esto, poné `diarizar = false` en `config.toml` y
funciona sin token (texto corrido, sin identificar voces).

## Uso

### Carpeta vigilada

```sh
./.venv/bin/python vigilar.py
```

Queda escuchando `~/Downloads/reuniones`. Arrastrás ahí la grabación y listo:
la transcripción aparece en `~/Transcripciones`. Espera a que el archivo
termine de copiarse antes de agarrarlo, así que podés soltar algo que todavía
se está bajando.

Para que arranque solo al prender la Mac, mirá
`com.casi.transcriptor.plist.ejemplo`.

### Un archivo suelto

```sh
./.venv/bin/python transcribir.py "~/Downloads/Reunión Juan Formaro 3-9.m4a"
```

Opciones útiles:

```sh
--modelo medium      # más rápido, algo menos preciso
--sin-hablantes      # saltea la diarización (y el token)
--hablantes 3        # si sabés cuántos eran, el corte mejora bastante
--salida ~/Escritorio
```

## Configuración

`config.toml` (se crea solo la primera vez, a partir de
`config.ejemplo.toml`). Lo más relevante:

| Clave | Para qué |
|---|---|
| `carpeta_vigilada` | Dónde soltás las grabaciones |
| `carpeta_salida` | Dónde aparecen las transcripciones |
| `modelo` | `large-v3` (mejor) · `medium` · `small` (más rápido) |
| `diarizar` | Separar por hablante (necesita token) |
| `min_hablantes` / `max_hablantes` | Acotar el conteo de voces |

## Cuánto tarda

En un Mac con chip M, `large-v3` corre por encima de tiempo real: una reunión
de una hora ronda los 15–25 minutos. La diarización suma más o menos un tercio
de eso. Si te resulta lento, bajar a `medium` casi lo duplica en velocidad y
en español sigue siendo muy digno.

Whisper corre en CPU siempre: CTranslate2 no soporta Metal. No es un error de
configuración, es una limitación de la librería.

## Verificar que quedó bien instalado

```sh
./.venv/bin/python pruebas.py
```

19 pruebas que cubren decodificación de audio, armado de intervenciones,
formatos de salida, registro de estado y detección de archivos. No requieren
descargar ningún modelo, así que sirven para confirmar la instalación antes de
esperar la primera transcripción larga.

## Si algo falla

| Síntoma | Causa habitual |
|---|---|
| `Could not download pyannote...` o pipeline nula | Falta aceptar las condiciones en **alguna** de las dos páginas de pyannote, o el token no es válido |
| `No module named 'faster_whisper'` | Estás usando el Python del sistema. Usá `./.venv/bin/python` |
| `no se detectó habla` | La pista está muda, o es solo música |
| Todo muy lento | Bajá `modelo` a `medium`, o `diarizar = false` |
| El vigía no ve el archivo | Extensión no listada, empieza con punto, o todavía se está copiando |

Los errores quedan registrados en `.estado.json`, dentro de la carpeta de
salida. Un archivo que falló no se reintenta solo: borrá su entrada de ese
archivo, o volvé a copiarlo a la carpeta.

## Después de la transcripción

El `.md` está pensado para traerlo a Claude y armar desde ahí la minuta, los
temas tratados y los compromisos asumidos. Esa parte es deliberadamente
manual: el servicio transcribe, la interpretación la hacemos aparte.
