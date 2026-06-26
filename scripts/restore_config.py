#!/usr/bin/env python3
"""
restore_config.py — Restauración de configuración desde un backup.

Recupera la config de un equipo (o de todos) desde un backup versionado y la
re-aplica: para switches/APs/gateways re-empuja la plantilla/config de grupo vía
Aruba Central; para el firewall importa el XML respaldado en PAN-OS + commit.

Por defecto restaura desde el backup 'latest'. Modo --simulate (determinístico,
sin equipos) o --real (API + secretos).

Uso:
  python3 scripts/restore_config.py --host agg-01            # un equipo, último backup
  python3 scripts/restore_config.py --all --date 2026-06-25  # todo, de una fecha
  python3 scripts/restore_config.py --host fw-perim-01 --real
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUPS = os.path.join(ROOT, "backups")
EVIDENCE = os.path.join(ROOT, "evidence", "restore")
log = logging.getLogger("restore")

# Cómo se restaura cada rol (método real correspondiente)
METHOD = {
    "access": "re-aplicar template group en Central",
    "aggregation": "re-aplicar template group en Central",
    "wireless": "re-aplicar config de grupo (UI group) en Central",
    "firewall": "importar XML en PAN-OS + commit",
}


def resolve_date(date: str | None) -> str:
    if date:
        return date
    latest = os.path.join(BACKUPS, "latest")
    if os.path.exists(latest):
        return open(latest).read().strip()
    raise SystemExit("no hay backups (¿corriste backup_configs.py?)")


def load_manifest(date: str) -> dict:
    path = os.path.join(BACKUPS, date, "manifest.json")
    if not os.path.exists(path):
        raise SystemExit(f"no existe el backup {date}")
    return json.load(open(path))


class SimulatedRestore:
    def apply(self, unit: dict, content: str) -> dict:
        # Determinístico: la restauración "aplica" y verifica OK.
        return {"ok": True, "bytes": len(content)}


class RealRestore:
    def __init__(self):
        need = ("ARUBA_CENTRAL_CLIENT_ID", "PANOS_API_KEY")
        missing = [v for v in need if not os.getenv(v)]
        if missing:
            raise SystemExit(f"[real] faltan secretos: {', '.join(missing)}")

    def apply(self, unit: dict, content: str) -> dict:
        # switch/ap/gw: PUT template/group en Central · firewall: import XML + commit
        raise NotImplementedError("conectar APIs aquí")


def main() -> int:
    ap = argparse.ArgumentParser(description="Restauración desde backup")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--host", help="unidad a restaurar (hostname o grupo de APs)")
    g.add_argument("--all", action="store_true", help="restaurar todas las unidades")
    ap.add_argument("--date", help="fecha del backup (YYYY-MM-DD); por defecto latest")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--simulate", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    date = resolve_date(args.date)
    manifest = load_manifest(date)
    backend = RealRestore() if args.real else SimulatedRestore()

    targets = manifest["units"]
    if args.host:
        targets = [u for u in targets if u["key"] == args.host]
        if not targets:
            raise SystemExit(f"'{args.host}' no está en el backup {date}")

    log.info("restaurando %d unidad(es) desde backup %s (%s)",
             len(targets), date, "real" if args.real else "simulate")

    results = []
    for u in targets:
        content = open(os.path.join(BACKUPS, u["file"])).read()
        res = backend.apply(u, content)
        method = METHOD.get(u["role"], "re-aplicar config")
        status = "restored" if res.get("ok") else "failed"
        results.append({"unit": u["key"], "role": u["role"], "method": method,
                        "status": status, "source": u["file"]})
        log.info("%-9s %-22s · %s", status.upper(), u["key"], method)

    os.makedirs(EVIDENCE, exist_ok=True)
    out = {"restored_from": date,
           "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "mode": "real" if args.real else "simulate", "results": results}
    json.dump(out, open(os.path.join(EVIDENCE, "restore_results.json"), "w"), indent=2)

    failed = sum(1 for r in results if r["status"] == "failed")
    log.info("RESUMEN · %d restored · %d failed", len(results) - failed, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
