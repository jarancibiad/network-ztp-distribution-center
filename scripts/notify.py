#!/usr/bin/env python3
"""
notify.py — Notificación a Slack/webhook (automatización extra).

Lee la evidencia generada por claim_devices.py y backup_configs.py y arma un
mensaje de estado. En --simulate (por defecto) escribe el payload a evidencia
(sin webhook); en --real lo postea a SLACK_WEBHOOK_URL.

Eventos:
  provision  -> resultado del aprovisionamiento (evidence/claim/claim_summary.json)
  drift      -> resultado del backup diario     (evidence/backup/drift_report.json)
  auto       -> ambos, según qué evidencia exista (por defecto)

Uso:
  python3 scripts/notify.py                      # simulación, auto
  python3 scripts/notify.py --event drift --real # postea a Slack (requiere webhook)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(ROOT, "evidence")
OUT = os.path.join(EV, "notify")
log = logging.getLogger("notify")


def _load(path: str):
    try:
        return json.load(open(path))
    except FileNotFoundError:
        return None


def msg_provision() -> dict | None:
    data = _load(os.path.join(EV, "claim", "claim_summary.json"))
    if not data:
        return None
    s = data["summary"]["by_status"]
    failed = s.get("failed", 0)
    icon = "❌" if failed else "✅"
    text = (f"{icon} *Aprovisionamiento* ({data['run']['mode']}) · "
            f"{s.get('claimed', 0)} claimed · {s.get('skipped', 0)} skipped · "
            f"{failed} failed")
    return {"event": "provision", "text": text, "alert": bool(failed)}


def msg_drift() -> dict | None:
    data = _load(os.path.join(EV, "backup", "drift_report.json"))
    if not data:
        return None
    changed = data.get("changed", [])
    if not changed:
        text = (f"✅ *Backup diario* {data['date']} · sin drift "
                f"({data.get('unchanged', 0)} unidades estables)")
        return {"event": "drift", "text": text, "alert": False}
    units = ", ".join(c["unit"] for c in changed)
    text = (f"⚠️ *Drift detectado* {data['date']} · "
            f"{len(changed)} unidad(es) cambiaron fuera de IaC: {units}")
    return {"event": "drift", "text": text, "alert": True}


def post(payload: dict) -> None:
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        raise SystemExit("[real] falta SLACK_WEBHOOK_URL")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)


def main() -> int:
    ap = argparse.ArgumentParser(description="Notificación Slack/webhook")
    ap.add_argument("--event", choices=["provision", "drift", "auto"], default="auto")
    ap.add_argument("--real", action="store_true", help="postea a SLACK_WEBHOOK_URL")
    ap.add_argument("--simulate", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    builders = {"provision": [msg_provision], "drift": [msg_drift],
                "auto": [msg_provision, msg_drift]}[args.event]
    messages = [m for b in builders if (m := b())]
    if not messages:
        log.warning("no hay evidencia para notificar (¿corriste claim/backup?)")
        return 0

    os.makedirs(OUT, exist_ok=True)
    for m in messages:
        payload = {"text": m["text"]}
        if args.real:
            post(payload)
            log.info("posteado a Slack: %s", m["event"])
        else:
            f = os.path.join(OUT, f"{m['event']}_message.json")
            json.dump({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       **m, "payload": payload}, open(f, "w"), indent=2)
            log.info("[simulado] %s", m["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
