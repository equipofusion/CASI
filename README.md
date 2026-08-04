# IG Watch — CASI

Radar automático de publicaciones urgentes en Instagram de otros Colegios de
Abogados (índices/valores del ejercicio profesional, suspensión de términos,
caídas de sistemas, cambios en honorarios/facturación, resoluciones de la
SCJBA con impacto en la práctica diaria).

## Cómo funciona (arquitectura en dos partes)

1. **Scraping (este repo, en GitHub Actions):** dos veces al día, un
   workflow trae los posts nuevos de las 21 cuentas listadas en
   `ig_watch/accounts.json`, usando Apify, y publica lo nuevo en
   `ig_watch/latest_batch.json`. Esta parte es deliberadamente "tonta": no
   interpreta nada, solo detecta qué es nuevo desde la última corrida.
2. **Interpretación y aviso (fuera de este repo, en Claude):** una tarea
   programada de Claude lee `latest_batch.json` publicado acá, decide si
   hay algo urgente según los 5 ejes definidos, y entrega el brief. Esa
   parte se configura del lado de Claude, no en este repo.

## Puesta en marcha

### 1. Crear el repositorio

Subí esta carpeta completa a un repositorio de GitHub (puede ser privado).
Estructura esperada:

```
.github/workflows/ig-watch.yml
ig_watch/scraper.py
ig_watch/accounts.json
ig_watch/state.json
```

### 2. Cargar el token de Apify como secret

En el repo: **Settings → Secrets and variables → Actions → New repository
secret**.

- Nombre: `APIFY_TOKEN`
- Valor: tu token de API de Apify (Apify Console → Settings → Integrations)

### 3. Verificar el actor de Apify antes de confiar en el cron

El script usa el actor `apify/instagram-scraper` con el input
`directUrls` + `resultsType: posts`. Apify actualiza sus actors con
frecuencia, así que antes de dejarlo en piloto automático:

1. Corré el workflow manualmente: pestaña **Actions** → "IG Watch -
   Scraping bicotidiano" → **Run workflow**.
2. Revisá los logs de la corrida. Si Apify devuelve un error de actor no
   encontrado o de input inválido, entrá a
   [Apify Console](https://console.apify.com) y confirmá el ID correcto
   del actor y su esquema de input actual, y ajustá `ACTOR_ID` y la
   función `call_apify()` en `ig_watch/scraper.py`.
3. Cuando la corrida manual funcione y `ig_watch/latest_batch.json` se
   actualice con datos razonables (posts con caption, username, url),
   quedate tranquilo de que el cron automático (8:45 y 15:45 hs ART) va a
   funcionar igual.

### 4. Activar el cron

No hace falta nada más — una vez que el workflow corrió bien
manualmente, el `schedule` del archivo `.github/workflows/ig-watch.yml`
ya lo deja corriendo solo, dos veces por día, sin depender de ninguna
computadora prendida.

### 5. Conectar el lado de Claude

Una vez que el repo esté funcionando y tengas al menos una corrida
exitosa, pasame la URL pública del archivo, con este formato:

```
https://raw.githubusercontent.com/<tu-usuario>/<tu-repo>/main/ig_watch/latest_batch.json
```

Con esa URL configuro la tarea programada de Claude que lee ese archivo,
interpreta las novedades y te manda el brief dos veces al día.

## Costos esperados

- **Apify:** pago por uso, centavos por corrida (21 cuentas x 6 posts x 2
  veces al día). Revisá el pricing del actor elegido en Apify Console para
  una estimación exacta antes de dejarlo corriendo indefinidamente.
- **GitHub Actions:** gratis en este volumen (dos corridas cortas por día)
  para repos privados dentro del plan gratuito estándar.
- **Claude:** sin costo adicional — la interpretación corre dentro de tu
  suscripción actual de Cowork, no usa API paga aparte.

## Riesgos a tener presentes

- El scraping de Instagram vía Apify no es un método oficial soportado por
  Meta; existe la posibilidad de que Apify deje de poder acceder a alguna
  cuenta puntual, o que el actor cambie. Si una corrida devuelve 0 posts
  para todas las cuentas de forma sostenida, es señal de que hay que
  revisar el actor.
- Si una cuenta específica cambia de nombre de usuario, hay que actualizar
  `ig_watch/accounts.json` a mano.
