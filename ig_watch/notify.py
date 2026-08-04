#!/usr/bin/env python3
"""
IG Watch - Notificador por email (Resend + Claude)
---------------------------------------------------
Lee latest_batch.json, envía los posts a Claude para análisis
inteligente, y manda un brief HTML por email vía Resend.

Variables de entorno requeridas:
  RESEND_API_KEY    -> API key de Resend (resend.com)
  ANTHROPIC_API_KEY -> API key de Anthropic (Claude)
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
BATCH_FILE = ROOT / "latest_batch.json"

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
FROM_EMAIL = "IG Watch CASI <contacto@pisosiete.com.ar>"
TO_EMAILS = [
    "equipo@agenciafusion.com",
    "solangenarbar@gmail.com",
]

CLAUDE_MODEL = "claude-haiku-4-5-20251001"

ANALYSIS_PROMPT = """\
Sos un analista de comunicación institucional para CASI (Colegio de Abogados de San Isidro) \
y Piso 7, su agencia de comunicación. Tu tarea es revisar publicaciones de Instagram de \
Colegios de Abogados y detectar información relevante para la estrategia de comunicación.

## Posts a analizar

{posts_json}

## Ejes de interés (solo reportar posts que correspondan a estos)

1. **Actualización de índices o valores del ejercicio profesional** — JUS, UMA, bono, \
tasa de justicia, valor arancelario, u otro valor de referencia usado para honorarios \
o costos del ejercicio.
2. **Suspensión de términos procesales.**
3. **Interrupción del funcionamiento de sistemas** — mesa de entradas virtual, portal \
de presentaciones, sistemas de gestión judicial, etc.
4. **Cambios relevantes en honorarios, comprobantes, facturación o impuestos** que \
afecten el ejercicio profesional.
5. **Resoluciones o sentencias de la SCJBA** — SOLO si modifican o actualizan alguna \
cuestión de la práctica diaria de trabajo de los abogados. NO reportar jurisprudencia \
de fondo/doctrina sin impacto práctico y operativo directo.

## Qué IGNORAR (no reportar)

- Cursos, capacitaciones, jornadas, seminarios, talleres, diplomaturas, congresos
- Actividades académicas, reuniones de institutos
- Saludos, efemérides, homenajes, aniversarios
- Torneos, eventos deportivos, actividades sociales
- Agenda institucional rutinaria
- Publicaciones sin caption o con caption irrelevante

## Instrucciones de salida

Respondé ÚNICAMENTE con un JSON válido (sin markdown, sin backticks, sin texto antes \
ni después) con esta estructura:

{{
  "hallazgos": [
    {{
      "eje": 1,
      "posts": [
        {{
          "colegio": "Nombre del colegio",
          "resumen": "Qué dice el post en 1-2 oraciones",
          "relevancia": "Por qué le importa a CASI (1 oración)",
          "url": "URL del post"
        }}
      ]
    }}
  ],
  "propuestas": [
    {{
      "tema": "Sobre qué publicar",
      "textos_imagen": ["Texto 1 para imagen/carrusel", "Texto 2 si aplica"],
      "copy": "Texto completo del caption propuesto para Instagram"
    }}
  ]
}}

Reglas:
- Si no hay hallazgos, "hallazgos" debe ser un array vacío [].
- Si hay hallazgos, agrupa los posts del mismo tema bajo el mismo eje.
- En "propuestas", sugerí qué debería publicar CASI en base a los hallazgos. \
Si no hay hallazgos relevantes, podés proponer contenido de valor general para abogados.
- Los textos_imagen son frases cortas para sobreimprimir en una imagen o usar como \
slides de un carrusel. Deben ser impactantes y concisos.
- El copy debe incluir hashtags relevantes y estar escrito en español de Argentina, \
profesional pero cercano.
- Ante la duda sobre si algo es relevante, incluilo.
"""


def call_claude(posts):
    posts_for_prompt = []
    for p in posts:
        posts_for_prompt.append({
            "colegio": p.get("colegio", p.get("username", "?")),
            "caption": (p.get("caption", "") or "")[:1000],
            "url": p.get("url", ""),
        })

    prompt = ANALYSIS_PROMPT.format(posts_json=json.dumps(posts_for_prompt, ensure_ascii=False, indent=2))

    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "User-Agent": "ig-watch-casi/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    text = result["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text)


EJE_NAMES = {
    1: "Actualización de índices o valores",
    2: "Suspensión de términos procesales",
    3: "Interrupción de sistemas",
    4: "Honorarios, facturación o impuestos",
    5: "Resoluciones SCJBA",
}

EJE_COLORS = {
    1: "#2563eb",
    2: "#dc2626",
    3: "#ea580c",
    4: "#059669",
    5: "#7c3aed",
}


def build_html(analysis, generated_at, total_count):
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    hallazgos = analysis.get("hallazgos", [])
    propuestas = analysis.get("propuestas", [])

    html = f"""\
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 640px; margin: 0 auto; color: #1a1a1a;">

  <div style="background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%); padding: 28px 24px; border-radius: 12px 12px 0 0;">
    <h1 style="color: #ffffff; margin: 0; font-size: 22px; font-weight: 700; letter-spacing: 0.5px;">IG Watch — CASI</h1>
    <p style="color: #bfdbfe; margin: 6px 0 0; font-size: 14px;">{today} &nbsp;·&nbsp; {total_count} posts relevados de 21 cuentas</p>
  </div>

  <div style="background: #ffffff; padding: 24px; border: 1px solid #e5e7eb; border-top: none;">
"""

    if not hallazgos:
        html += """\
    <div style="text-align: center; padding: 32px 16px;">
      <p style="font-size: 16px; color: #6b7280; margin: 0;">Sin novedades urgentes en esta revisión.</p>
    </div>
    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
"""
    else:
        for grupo in hallazgos:
            eje_num = grupo.get("eje", 0)
            eje_name = EJE_NAMES.get(eje_num, f"Eje {eje_num}")
            eje_color = EJE_COLORS.get(eje_num, "#6b7280")
            posts = grupo.get("posts", [])

            html += f"""\
    <div style="margin-bottom: 24px;">
      <div style="display: inline-block; background: {eje_color}; color: #ffffff; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; padding: 4px 10px; border-radius: 4px; margin-bottom: 12px;">Eje {eje_num} — {eje_name}</div>
"""
            for post in posts:
                colegio = post.get("colegio", "?")
                resumen = post.get("resumen", "")
                relevancia = post.get("relevancia", "")
                url = post.get("url", "")
                html += f"""\
      <div style="background: #f9fafb; border-left: 3px solid {eje_color}; padding: 14px 16px; margin-bottom: 8px; border-radius: 0 6px 6px 0;">
        <p style="margin: 0 0 4px; font-weight: 600; font-size: 14px; color: #111827;">{colegio}</p>
        <p style="margin: 0 0 6px; font-size: 14px; color: #374151; line-height: 1.5;">{resumen}</p>
        <p style="margin: 0; font-size: 13px; color: #6b7280; font-style: italic;">→ {relevancia}</p>
"""
                if url:
                    html += f"""\
        <p style="margin: 6px 0 0;"><a href="{url}" style="font-size: 13px; color: {eje_color}; text-decoration: none;">Ver post ↗</a></p>
"""
                html += """\
      </div>
"""
            html += """\
    </div>
"""

    if propuestas:
        html += """\
    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
    <div style="margin-bottom: 16px;">
      <h2 style="font-size: 16px; font-weight: 700; color: #111827; margin: 0 0 16px;">💡 Propuestas de contenido para CASI</h2>
"""
        for i, prop in enumerate(propuestas, 1):
            tema = prop.get("tema", "")
            textos = prop.get("textos_imagen", [])
            copy = prop.get("copy", "")

            html += f"""\
      <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
        <p style="margin: 0 0 10px; font-weight: 600; font-size: 14px; color: #92400e;">Propuesta {i}: {tema}</p>
"""
            if textos:
                html += """\
        <p style="margin: 0 0 6px; font-size: 12px; font-weight: 600; color: #78716c; text-transform: uppercase; letter-spacing: 0.5px;">Textos para imagen / carrusel:</p>
        <ul style="margin: 0 0 12px; padding-left: 18px;">
"""
                for t in textos:
                    html += f"""\
          <li style="font-size: 14px; color: #1c1917; margin-bottom: 4px; font-weight: 500;">{t}</li>
"""
                html += """\
        </ul>
"""
            if copy:
                html += f"""\
        <p style="margin: 0 0 6px; font-size: 12px; font-weight: 600; color: #78716c; text-transform: uppercase; letter-spacing: 0.5px;">Copy propuesto:</p>
        <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px; font-size: 14px; color: #374151; line-height: 1.6; white-space: pre-wrap;">{copy}</div>
"""
            html += """\
      </div>
"""
        html += """\
    </div>
"""

    html += f"""\
  </div>

  <div style="background: #f3f4f6; padding: 16px 24px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb; border-top: none;">
    <p style="margin: 0; font-size: 12px; color: #9ca3af; text-align: center;">
      Generado automáticamente por IG Watch — CASI &nbsp;·&nbsp; Scraping: {generated_at}
    </p>
  </div>

</div>
"""
    return html


def send_email(subject, html_body):
    if not RESEND_API_KEY:
        print("ERROR: falta RESEND_API_KEY", file=sys.stderr)
        sys.exit(1)

    payload = json.dumps({
        "from": FROM_EMAIL,
        "to": TO_EMAILS,
        "subject": subject,
        "html": html_body,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "ig-watch-casi/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"Email enviado. ID: {result.get('id', '?')}")
            return True
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace")
        print(f"ERROR Resend HTTP {e.code}: {body_err}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"ERROR enviando email: {e}", file=sys.stderr)
        return False


def main():
    if not BATCH_FILE.exists():
        print("ERROR: latest_batch.json no existe", file=sys.stderr)
        sys.exit(1)

    if not ANTHROPIC_API_KEY:
        print("ERROR: falta ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)

    with open(BATCH_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    generated_at = data.get("generated_at_utc", "?")
    total_count = data.get("count", 0)
    posts = data.get("posts", [])
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    subject = f"IG Watch CASI — Brief {today}"

    if total_count == 0:
        gen_dt = None
        try:
            gen_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except Exception:
            pass

        stale = ""
        if gen_dt:
            age_hours = (datetime.now(timezone.utc) - gen_dt).total_seconds() / 3600
            if age_hours > 24:
                stale = (
                    "<br><br><strong>⚠️ ADVERTENCIA:</strong> la última corrida del scraping "
                    f"fue hace más de 24 horas ({generated_at}). Posible falla — revisar "
                    "el workflow en GitHub Actions."
                )

        empty_analysis = {"hallazgos": [], "propuestas": []}
        html = build_html(empty_analysis, generated_at, total_count)
        if stale:
            html = html.replace("Sin novedades urgentes en esta revisión.", f"Sin novedades urgentes en esta revisión.{stale}")
        if not send_email(subject, html):
            sys.exit(1)
        print("Sin posts nuevos. Brief vacío enviado.")
        return

    print(f"Analizando {total_count} posts con Claude...")
    try:
        analysis = call_claude(posts)
    except Exception as e:
        print(f"ERROR llamando a Claude: {e}", file=sys.stderr)
        sys.exit(1)

    hallazgos_count = sum(len(g.get("posts", [])) for g in analysis.get("hallazgos", []))
    propuestas_count = len(analysis.get("propuestas", []))
    print(f"Claude: {hallazgos_count} hallazgos, {propuestas_count} propuestas.")

    html = build_html(analysis, generated_at, total_count)
    if not send_email(subject, html):
        sys.exit(1)

    print(f"Brief enviado. {hallazgos_count} hallazgos de {total_count} posts.")


if __name__ == "__main__":
    main()
