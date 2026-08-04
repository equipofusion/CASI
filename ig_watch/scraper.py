#!/usr/bin/env python3
"""
IG Watch - CASI
-----------------
Trae los posts nuevos de una lista de cuentas de Instagram usando un actor
de Apify, los compara contra el estado guardado en state.json, y publica en
latest_batch.json SOLO lo que es nuevo desde la última corrida.

Este script NO interpreta ni clasifica nada. Es deliberadamente "tonto":
solo trae datos y detecta qué es nuevo. La interpretación (¿esto es
urgente? ¿a qué eje corresponde?) la hace después la tarea programada de
Claude que lee latest_batch.json.

IMPORTANTE antes de usar en producción:
  - Verificá en https://console.apify.com el ID exacto del actor y el
    esquema de input vigente. Apify actualiza sus actors con frecuencia y
    este script fue escrito según la documentación pública disponible
    hasta mediados de 2025 (actor "apify/instagram-scraper", input con
    directUrls + resultsType=posts). Si cambió el nombre o los parámetros,
    ajustá ACTOR_ID e call_apify() más abajo.
  - Corré una prueba manual (ver README) con tu APIFY_TOKEN antes de
    confiar en el cron de GitHub Actions. Esta corrida no se pudo probar
    contra la API real de Apify porque el entorno donde se escribió no
    tiene salida a internet general.

Variable de entorno requerida:
  APIFY_TOKEN   -> token de API de tu cuenta de Apify
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parent
ACCOUNTS_FILE = ROOT / "accounts.json"
STATE_FILE = ROOT / "state.json"
BATCH_FILE = ROOT / "latest_batch.json"

ACTOR_ID = "apify~instagram-scraper"
APIFY_TOKEN = os.environ.get("APIFY_TOKEN")

RESULTS_LIMIT_PER_ACCOUNT = 6

MAX_SEEN_IDS_PER_ACCOUNT = 50


def load_json(path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def call_apify(direct_urls):
    """Llama al actor de Apify de forma sincrónica y devuelve los items del dataset."""
    if not APIFY_TOKEN:
        print("ERROR: falta la variable de entorno APIFY_TOKEN", file=sys.stderr)
        sys.exit(1)

    url = (
        f"https://api.apify.com/v2/actors/{ACTOR_ID}/run-sync-get-dataset-items"
        f"?token={APIFY_TOKEN}"
    )
    payload = {
        "directUrls": direct_urls,
        "resultsType": "posts",
        "resultsLimit": RESULTS_LIMIT_PER_ACCOUNT,
        "searchType": "user",
        "addParentData": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"ERROR Apify HTTP {e.code}: {body}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"ERROR llamando a Apify: {e}", file=sys.stderr)
        return []


def main():
    accounts = load_json(ACCOUNTS_FILE, [])
    if not accounts:
        print("ERROR: accounts.json vacío o inexistente", file=sys.stderr)
        sys.exit(1)

    state = load_json(STATE_FILE, {})
    direct_urls = [a["instagram_url"] for a in accounts]
    username_by_handle = {
        a["instagram_url"].rstrip("/").split("/")[-1].lower(): a for a in accounts
    }

    print(f"Consultando Apify para {len(direct_urls)} cuentas...")
    items = call_apify(direct_urls)
    print(f"Apify devolvió {len(items)} posts en total (antes de filtrar nuevos).")

    new_batch = []
    for item in items:
        username = (item.get("ownerUsername") or item.get("username") or "").lower()
        debug = item.get("#debug", {})
        post_id = item.get("shortCode") or debug.get("id") or item.get("id") or item.get("url")
        if not username or not post_id:
            continue

        seen_ids = set(state.get(username, {}).get("seen_ids", []))
        if post_id in seen_ids:
            continue

        account_meta = username_by_handle.get(username, {})
        new_batch.append({
            "colegio": account_meta.get("colegio", username),
            "username": username,
            "post_id": post_id,
            "url": item.get("url"),
            "caption": item.get("caption", "") or "",
            "timestamp": item.get("timestamp"),
            "type": item.get("type"),
        })

        seen_ids.add(post_id)
        trimmed = list(seen_ids)[-MAX_SEEN_IDS_PER_ACCOUNT:]
        state.setdefault(username, {})["seen_ids"] = trimmed

    save_json(STATE_FILE, state)
    save_json(BATCH_FILE, {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(new_batch),
        "posts": new_batch,
    })

    print(f"Listo. {len(new_batch)} posts nuevos publicados en {BATCH_FILE.name}.")


if __name__ == "__main__":
    main()
