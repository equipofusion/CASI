#!/usr/bin/env python3
"""
IG Watch - Notificador por email (Resend)
------------------------------------------
Lee latest_batch.json, filtra los posts que corresponden a los 5 ejes
de interés de CASI, arma un brief y lo envía por email vía Resend.

Variable de entorno requerida:
  RESEND_API_KEY  -> API key de Resend (resend.com)
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
BATCH_FILE = ROOT / "latest_batch.json"

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
FROM_EMAIL = "IG Watch CASI <onboarding@resend.dev>"
TO_EMAIL = "contacto@pisosiete.com.ar"

EJES = [
    {
        "nombre": "Actualización de índices o valores del ejercicio profesional",
        "keywords": [
            r"\bjus\b", r"\buma\b", r"\bbono\b", r"tasa de justicia",
            r"valor arancelario", r"jus arancelario", r"arancel",
            r"valor del jus", r"valor de referencia", r"concursos y quiebras",
            r"decreto.ley 8904",
        ],
    },
    {
        "nombre": "Suspensión de términos procesales",
        "keywords": [
            r"suspensi[óo]n de (los )?t[ée]rminos",
            r"t[ée]rminos procesales",
            r"suspender.*t[ée]rminos",
        ],
    },
    {
        "nombre": "Interrupción de sistemas",
        "keywords": [
            r"mesa de entradas virtual", r"\bmev\b",
            r"portal de presentaciones", r"contingencia operativa",
            r"ca[íi]da del sistema", r"sistema.*(ca[íi]do|fuera de servicio|interrump)",
            r"gesti[óo]n judicial.*(ca[íi]|interrup|falla)",
        ],
    },
    {
        "nombre": "Cambios en honorarios, facturación o impuestos",
        "keywords": [
            r"honorarios", r"facturaci[óo]n", r"comprobante",
            r"impuesto.*ejercicio", r"aportes?.*(colegiatura|matr[íi]cula)",
            r"derecho fijo", r"contribuci[óo]n.*obligatoria",
        ],
    },
    {
        "nombre": "Resoluciones SCJBA con impacto operativo",
        "keywords": [
            r"\bscba\b", r"\bscjba\b", r"suprema corte",
            r"acordada.*scba", r"resoluci[óo]n.*(scba|suprema corte)",
        ],
    },
]

NOISE_KEYWORDS = [
    r"curso\b", r"capacitaci[óo]n", r"jornada\b", r"congreso\b",
    r"d[íi]a del abogado", r"feliz", r"saludo", r"aniversario",
    r"torneo", r"f[úu]tbol", r"campeonato", r"inscripci[óo]n abierta",
    r"taller\b", r"charla\b", r"seminario", r"diplomatura",
    r"biblioteca", r"homenaje",
]


def matches_eje(caption, eje):
    text = caption.lower()
    for kw in eje["keywords"]:
        if re.search(kw, text, re.IGNORECASE):
            return True
    return False


def is_noise(caption):
    text = caption.lower()
    for kw in NOISE_KEYWORDS:
        if re.search(kw, text, re.IGNORECASE):
            return True
    return False


def classify_posts(posts):
    results = {i: [] for i in range(len(EJES))}
    seen_ids = set()

    for post in posts:
        caption = post.get("caption", "") or ""
        post_id = post.get("post_id", "")

        if not caption.strip():
            continue

        for i, eje in enumerate(EJES):
            if matches_eje(caption, eje) and post_id not in seen_ids:
                results[i].append(post)
                seen_ids.add(post_id)
                break

    return results


def format_brief(classified, generated_at, total_count):
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    lines = [
        f"BRIEF IG WATCH — CASI",
        f"{today} (scraping: {generated_at})",
        f"{total_count} posts relevados de 21 cuentas.",
        "",
        "---",
        "",
    ]

    any_finding = False
    for i, eje in enumerate(EJES):
        posts = classified[i]
        if not posts:
            continue
        any_finding = True
        lines.append(f"EJE {i+1} — {eje['nombre'].upper()}")
        lines.append("")
        for post in posts:
            colegio = post.get("colegio", post.get("username", "?"))
            caption = (post.get("caption", "") or "").strip()
            if len(caption) > 300:
                caption = caption[:297] + "..."
            url = post.get("url", "")
            lines.append(f"• {colegio}")
            lines.append(f"  {caption}")
            if url:
                lines.append(f"  {url}")
            lines.append("")
        lines.append("---")
        lines.append("")

    if not any_finding:
        lines.append("Sin novedades urgentes en esta revisión.")
        lines.append("")
        lines.append("---")
        lines.append("")

    ejes_sin_novedad = [
        EJES[i]["nombre"] for i in range(len(EJES)) if not classified[i]
    ]
    if ejes_sin_novedad:
        lines.append("Sin novedades: " + "; ".join(ejes_sin_novedad) + ".")
        lines.append("")

    lines.append("---")
    lines.append("Generado automáticamente por IG Watch — CASI.")
    return "\n".join(lines)


def send_email(subject, body):
    if not RESEND_API_KEY:
        print("ERROR: falta RESEND_API_KEY", file=sys.stderr)
        sys.exit(1)

    payload = json.dumps({
        "from": FROM_EMAIL,
        "to": [TO_EMAIL],
        "subject": subject,
        "text": body,
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

    with open(BATCH_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    generated_at = data.get("generated_at_utc", "?")
    total_count = data.get("count", 0)
    posts = data.get("posts", [])

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
                    f"\n\nADVERTENCIA: la última corrida del scraping fue hace más de "
                    f"24 horas ({generated_at}). Posible falla — revisar el workflow "
                    f"en GitHub Actions."
                )

        today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
        subject = f"IG Watch CASI — Brief {today}"
        body = (
            f"BRIEF IG WATCH — CASI\n"
            f"{today} (scraping: {generated_at})\n\n"
            f"Sin novedades urgentes en esta revisión.{stale}\n\n"
            f"---\n"
            f"Generado automáticamente por IG Watch — CASI."
        )
        if not send_email(subject, body):
            sys.exit(1)
        print("Sin posts nuevos. Brief vacío enviado.")
        return

    classified = classify_posts(posts)
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    subject = f"IG Watch CASI — Brief {today}"
    body = format_brief(classified, generated_at, total_count)
    if not send_email(subject, body):
        sys.exit(1)

    total_findings = sum(len(v) for v in classified.values())
    print(f"Brief enviado. {total_findings} hallazgos de {total_count} posts.")


if __name__ == "__main__":
    main()
