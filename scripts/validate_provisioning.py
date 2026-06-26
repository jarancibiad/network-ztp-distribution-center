#!/usr/bin/env python3
"""
validate_provisioning.py — Validación post-provisión (gate).

Tras el claim, verifica que cada equipo quedó en el estado esperado:
  - alcance de gestión (la IP de gestión responde)
  - estado de configuración "sincronizado" con Aruba Central / PAN-OS
  - rol/grupo correcto según el inventario

Lee la evidencia del claim (evidence/claim/claim_results.json) y el inventario,
y produce un reporte de salud. Es un GATE: exit != 0 si algún equipo no cumple.

Modos: --simulate (determinístico) / --real (sondeo vía API + ICMP/SSH).

Uso:
  python3 scripts/validate_provisioning.py                 # simulación
  python3 scripts/validate_provisioning.py --real          # contra equipos
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVENTORY = os.path.join(ROOT, "inventory", "devices.csv")
CLAIM = os.path.join(ROOT, "evidence", "claim", "claim_results.json")
EVIDENCE = os.path.join(ROOT, "evidence", "validate")
log = logging.getLogger("validate")

# Checks por rol: qué se espera comprobar en cada tipo de equipo.
CHECKS = {
    "access":      ["mgmt_reachable", "central_synced", "uplink_up"],
    "aggregation": ["mgmt_reachable", "central_synced", "vsx_paired"],
    "wireless":    ["central_synced", "tunnels_up"],
    "gateway":     ["mgmt_reachable", "central_synced", "cluster_up"],
    "firewall":    ["mgmt_reachable", "panos_synced", "ha_up"],
}
ROLE_OF = {"switch_access": "access", "switch_agg": "aggregation",
           "ap": "wireless", "gateway": "gateway", "firewall": "firewall"}


class SimulatedProbe:
    """Sondeo determinístico: todo sano salvo seriales marcados para fallar."""

    def __init__(self, fail: set[str] | None = None):
        self.fail = fail or set()

    def check(self, dev: dict, name: str) -> bool:
        return dev["serial"] not in self.fail


class RealProbe:
    def __init__(self):
        # Requiere conectividad/credenciales; aquí van ICMP/SSH/API reales.
        if not os.getenv("ARUBA_CENTRAL_CLIENT_ID"):
            raise SystemExit("[real] faltan secretos de Central")

    def check(self, dev: dict, name: str) -> bool:
        # mgmt_reachable -> ping; central_synced -> GET estado en Central; etc.
        raise NotImplementedError("conectar sondeo real aquí")


def load_inventory() -> dict[str, dict]:
    with open(INVENTORY, newline="") as fh:
        return {d["serial"]: d for d in csv.DictReader(fh)}


def load_claimed() -> list[dict]:
    if not os.path.exists(CLAIM):
        raise SystemExit("no hay evidencia de claim (corré claim_devices.py primero)")
    data = json.load(open(CLAIM))
    # Solo validamos lo que se intentó claimar (los firewalls van por PAN-OS).
    return data["results"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Validación post-provisión (gate)")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--fail-sample", type=int, default=0,
                    help="(simulación) marca N equipos como no-sanos para demo")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    inv = load_inventory()
    claimed = load_claimed()

    if args.real:
        probe = RealProbe()
    else:
        serials = [r["serial"] for r in claimed]
        probe = SimulatedProbe(fail=set(serials[:args.fail_sample]))

    results, unhealthy = [], 0
    for r in claimed:
        dev = inv.get(r["serial"], {})
        role = ROLE_OF.get(r["device_type"], "access")
        # Los firewalls se gestionan por PAN-OS (claim los marca 'skipped'): igual se validan.
        checks = CHECKS.get(role, [])
        passed = {c: probe.check({**dev, "serial": r["serial"]}, c) for c in checks}
        healthy = all(passed.values())
        if not healthy:
            unhealthy += 1
        results.append({"hostname": r["hostname"], "role": role,
                        "healthy": healthy, "checks": passed})
        mark = "OK  " if healthy else "FAIL"
        log.info("%s %-16s %s", mark, r["hostname"],
                 ",".join(k for k, v in passed.items() if not v) or "todos los checks ✓")

    os.makedirs(EVIDENCE, exist_ok=True)
    summary = {"total": len(results), "healthy": len(results) - unhealthy,
               "unhealthy": unhealthy}
    out = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "mode": "real" if args.real else "simulate",
           "summary": summary, "results": results}
    json.dump(out, open(os.path.join(EVIDENCE, "validation_report.json"), "w"), indent=2)

    log.info("RESUMEN · %d sanos · %d con problemas (de %d)",
             summary["healthy"], unhealthy, summary["total"])
    return 1 if unhealthy else 0   # gate: falla el pipeline si algo no quedó sano


if __name__ == "__main__":
    sys.exit(main())
