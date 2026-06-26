#!/usr/bin/env python3
"""
claim_devices.py — Aprovisionamiento ZTP por número de serie contra Aruba Central.

Recorre inventory/devices.csv y, por cada equipo: lo CLAIMEA por serial, lo
ASIGNA a su grupo de Central (template/UI group) y registra el resultado.
Los firewalls (Palo Alto) NO van a Central: se gestionan directo por PAN-OS (su API / el par HA);
se marcan aparte). El claim real es bajo demanda (staging), no por horario.

Modos:
  --simulate (por defecto): backend determinístico, SIN equipos ni secretos.
      Produce evidencia reproducible en evidence/claim/.
  --real: usa pycentral + secretos (variables de entorno). Mismas llamadas.

Uso:
  python3 scripts/claim_devices.py                 # simulación (evidencia)
  python3 scripts/claim_devices.py --real          # contra Central (requiere secretos)
  python3 scripts/claim_devices.py --fail-sample 3 # inyecta 3 fallos (demo de manejo de error)
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
EVIDENCE = os.path.join(ROOT, "evidence", "claim")

log = logging.getLogger("claim")


# --------------------------------------------------------------------------- #
# Backends de Aruba Central                                                    #
# --------------------------------------------------------------------------- #
class SimulatedCentral:
    """Backend determinístico: responde como Central sin tocar la red."""

    def __init__(self, fail_serials: set[str] | None = None):
        self.fail_serials = fail_serials or set()

    def claim(self, dev: dict) -> dict:
        # Determinístico: éxito salvo que el serial esté marcado para fallar.
        if dev["serial"] in self.fail_serials:
            return {"ok": False, "step": "claim",
                    "error": "device not found in license pool (simulado)"}
        return {"ok": True, "central_device_id": f"SIM-{dev['serial']}"}

    def assign_group(self, dev: dict) -> dict:
        return {"ok": True, "group": dev["central_group"]}


class RealCentral:
    """Backend real (pycentral + secretos). Stubs marcados donde van las llamadas."""

    def __init__(self):
        missing = [v for v in ("ARUBA_CENTRAL_CLIENT_ID",
                               "ARUBA_CENTRAL_CLIENT_SECRET",
                               "ARUBA_CENTRAL_CUSTOMER_ID") if not os.getenv(v)]
        if missing:
            raise SystemExit(f"[real] faltan secretos: {', '.join(missing)}")
        # from pycentral.base import ArubaCentralBase
        # self.central = ArubaCentralBase(token_info=...)
        log.info("[real] sesión Central inicializada (pycentral)")

    def claim(self, dev: dict) -> dict:
        # POST /platform/device_inventory/v1/devices  (claim por serial)
        raise NotImplementedError("conectar pycentral aquí")

    def assign_group(self, dev: dict) -> dict:
        # POST /configuration/v1/devices/{serial}/group
        raise NotImplementedError("conectar pycentral aquí")


# --------------------------------------------------------------------------- #
# Orquestación                                                                 #
# --------------------------------------------------------------------------- #
def load_inventory(path: str) -> list[dict]:
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def provision(devices: list[dict], backend) -> list[dict]:
    results = []
    for dev in devices:
        # Los firewalls no van a Central: se gestionan directo por PAN-OS (API / HA).
        if dev["central_group"] == "n/a" or dev["device_type"] == "firewall":
            results.append({**_id(dev), "status": "skipped",
                            "reason": "gestión directa PAN-OS (no Central)"})
            log.info("SKIP  %-16s %s (PAN-OS)", dev["hostname"], dev["serial"])
            continue

        claim = backend.claim(dev)
        if not claim.get("ok"):
            results.append({**_id(dev), "status": "failed", **claim})
            log.error("FAIL  %-16s %s · %s", dev["hostname"], dev["serial"],
                      claim.get("error"))
            continue

        assign = backend.assign_group(dev)
        status = "claimed" if assign.get("ok") else "partial"
        results.append({**_id(dev), "status": status,
                        "central_group": dev["central_group"]})
        log.info("OK    %-16s %s -> %s", dev["hostname"], dev["serial"],
                 dev["central_group"])
    return results


def _id(dev: dict) -> dict:
    return {k: dev[k] for k in ("serial", "hostname", "device_type", "role")}


def summarize(results: list[dict]) -> dict:
    by_status, by_type = {}, {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_type.setdefault(r["device_type"], {})
        s = r["status"]
        by_type[r["device_type"]][s] = by_type[r["device_type"]].get(s, 0) + 1
    return {"total": len(results), "by_status": by_status, "by_type": by_type}


def write_evidence(results: list[dict], summary: dict, mode: str) -> None:
    os.makedirs(EVIDENCE, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {"run": {"timestamp": ts, "mode": mode}, "summary": summary,
               "results": results}
    with open(os.path.join(EVIDENCE, "claim_results.json"), "w") as fh:
        json.dump(payload, fh, indent=2)
    with open(os.path.join(EVIDENCE, "claim_summary.json"), "w") as fh:
        json.dump({"run": payload["run"], "summary": summary}, fh, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser(description="Claim/ZTP de equipos contra Aruba Central")
    ap.add_argument("--real", action="store_true", help="contra Central (requiere secretos)")
    ap.add_argument("--simulate", action="store_true", help="modo simulación (por defecto)")
    ap.add_argument("--inventory", default=INVENTORY)
    ap.add_argument("--fail-sample", type=int, default=0,
                    help="(simulación) inyecta N fallos determinísticos para demo")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    mode = "real" if args.real else "simulate"

    devices = load_inventory(args.inventory)
    log.info("inventario: %d equipos · modo=%s", len(devices), mode)

    if args.real:
        backend = RealCentral()
    else:
        # Fallos determinísticos: los primeros N seriales claimables (no firewalls).
        claimable = [d["serial"] for d in devices
                     if d["central_group"] != "n/a" and d["device_type"] != "firewall"]
        fail = set(claimable[:args.fail_sample]) if args.fail_sample else set()
        backend = SimulatedCentral(fail_serials=fail)

    results = provision(devices, backend)
    summary = summarize(results)
    write_evidence(results, summary, mode)

    log.info("RESUMEN · total=%d · %s", summary["total"], summary["by_status"])
    # Exit code != 0 si hubo fallos (sirve de gate en CI)
    return 1 if summary["by_status"].get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
