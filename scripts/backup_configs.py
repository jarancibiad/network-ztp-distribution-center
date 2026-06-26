#!/usr/bin/env python3
"""
backup_configs.py — Export diario de configuraciones + diff/drift.

Por cada equipo exporta su config (vía API de Aruba Central para switches/APs/
gateways; PAN-OS para el firewall) y la guarda versionada:

    backups/<fecha>/<rol>/<unidad>.<ext>   +  manifest.json   +  latest

Luego compara contra el backup anterior (normalizando líneas volátiles) y emite
un REPORTE DE DRIFT: qué unidades cambiaron y en qué líneas. Si no hay cambios,
no genera ruido.

Granularidad correcta por tipo:
  - switches (acceso/agregación) -> por equipo (.cfg)
  - APs (AOS 10)                 -> por GRUPO de Central (.json)  [no por AP]
  - gateways 9012                -> por equipo (.cfg)
  - firewall (PAN-OS)            -> por equipo (.xml)

Modos: --simulate (por defecto, determinístico) / --real (API + secretos).

Uso:
  python3 scripts/backup_configs.py                              # hoy (UTC)
  python3 scripts/backup_configs.py --as-of 2026-06-25           # fecha fija (evidencia)
  python3 scripts/backup_configs.py --drift-sample 2             # inyecta 2 cambios (demo)
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVENTORY = os.path.join(ROOT, "inventory", "devices.csv")
BACKUPS = os.path.join(ROOT, "backups")
EVIDENCE = os.path.join(ROOT, "evidence", "backup")

log = logging.getLogger("backup")

ROLE_DIR = {"switch_access": "access", "switch_agg": "aggregation",
            "ap": "wireless", "gateway": "wireless", "firewall": "firewall"}
EXT = {"switch_access": "cfg", "switch_agg": "cfg", "ap": "json",
       "gateway": "cfg", "firewall": "xml"}

# Patrones de líneas volátiles que NO deben contar como drift.
VOLATILE = [re.compile(p) for p in (
    r"^! generado:",        # timestamp del export
    r"uptime",
    r"ntp clock-period",
    r"last-change",
)]


# --------------------------------------------------------------------------- #
# Backends                                                                     #
# --------------------------------------------------------------------------- #
class SimulatedBackend:
    """Genera config determinística por unidad (para diffs reproducibles)."""

    def __init__(self, drift_keys: set[str] | None = None):
        self.drift_keys = drift_keys or set()

    def fetch(self, unit: dict, ts: str) -> str:
        key, role = unit["key"], unit["device_type"]
        # Línea volátil (cambia cada corrida) -> la normalización debe ignorarla.
        head = f"! generado: {ts}\n! unidad: {key}\n"
        if role == "firewall":
            body = (f'<config><hostname>{key}</hostname>'
                    f'<zones><zone>untrust</zone><zone>trust</zone></zones>'
                    f'<bgp local-as="65010"/></config>\n')
        elif role == "ap":
            body = json.dumps({"group": key, "ssids": ["MELI-CORP", "MELI-WMS",
                              "MELI-GUEST"], "forward_mode": "tunnel"}, indent=2) + "\n"
        else:
            body = (f"hostname {key}\nvlan 10\n    name MGMT\n"
                    f"spanning-tree mode mstp\nssh server vrf default\n")
        # Inyección de drift para demo: una línea extra determinística.
        if key in self.drift_keys:
            body += "vlan 30\n    name WMS-OPS   ! cambio fuera de IaC\n"
        return head + body


class RealBackend:
    """Backend real (Central + PAN-OS). Stubs marcados donde van las llamadas."""

    def __init__(self):
        need = ("ARUBA_CENTRAL_CLIENT_ID", "ARUBA_CENTRAL_CLIENT_SECRET",
                "PANOS_API_KEY")
        missing = [v for v in need if not os.getenv(v)]
        if missing:
            raise SystemExit(f"[real] faltan secretos: {', '.join(missing)}")

    def fetch(self, unit: dict, ts: str) -> str:
        # switches/aps/gateways: GET config de Central; firewall: 'show config running' PAN-OS
        raise NotImplementedError("conectar APIs aquí")


# --------------------------------------------------------------------------- #
# Lógica                                                                       #
# --------------------------------------------------------------------------- #
def units_from_inventory(path: str) -> list[dict]:
    """Colapsa el inventario en UNIDADES de backup (APs por grupo, resto por equipo)."""
    seen, units = set(), []
    with open(path, newline="") as fh:
        for d in csv.DictReader(fh):
            dt = d["device_type"]
            key = d["central_group"] if dt == "ap" else d["hostname"]
            uid = (dt, key)
            if uid in seen:
                continue
            seen.add(uid)
            units.append({"key": key, "device_type": dt,
                          "role": ROLE_DIR[dt], "ext": EXT[dt]})
    return units


def normalize(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        if any(p.search(line) for p in VOLATILE):
            continue
        out.append(line.rstrip())
    return out


def previous_backup_date(current: str) -> str | None:
    if not os.path.isdir(BACKUPS):
        return None
    dates = sorted(d for d in os.listdir(BACKUPS)
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and d < current)
    return dates[-1] if dates else None


def run_backup(units, backend, date: str) -> dict:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    day_dir = os.path.join(BACKUPS, date)
    manifest = {"date": date, "generated": ts, "units": []}

    for u in units:
        text = backend.fetch(u, ts)
        d = os.path.join(day_dir, u["role"])
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{u['key']}.{u['ext']}")
        with open(path, "w") as fh:
            fh.write(text)
        manifest["units"].append({
            "key": u["key"], "role": u["role"],
            "file": os.path.relpath(path, BACKUPS),
            "sha256": hashlib.sha256(text.encode()).hexdigest()[:16],
            "bytes": len(text),
        })

    with open(os.path.join(day_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    with open(os.path.join(BACKUPS, "latest"), "w") as fh:
        fh.write(date + "\n")
    return manifest


def diff_against_previous(units, date: str) -> dict:
    prev = previous_backup_date(date)
    report = {"date": date, "previous": prev, "changed": [], "unchanged": 0}
    if not prev:
        report["note"] = "línea base establecida (sin backup anterior)"
        return report

    for u in units:
        rel = os.path.join(u["role"], f"{u['key']}.{u['ext']}")
        f_now = os.path.join(BACKUPS, date, rel)
        f_old = os.path.join(BACKUPS, prev, rel)
        if not (os.path.exists(f_now) and os.path.exists(f_old)):
            continue
        a = normalize(open(f_old).read())
        b = normalize(open(f_now).read())
        if a == b:
            report["unchanged"] += 1
            continue
        delta = list(difflib.unified_diff(a, b, lineterm="",
                     fromfile=f"{prev}/{rel}", tofile=f"{date}/{rel}"))
        report["changed"].append({"unit": u["key"], "role": u["role"],
                                  "diff": delta})
    return report


def write_evidence(report: dict) -> None:
    os.makedirs(EVIDENCE, exist_ok=True)
    with open(os.path.join(EVIDENCE, "drift_report.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    # Reporte legible
    lines = [f"DRIFT · {report['date']} (vs {report['previous']})", "─" * 40]
    if report.get("note"):
        lines.append(report["note"])
    for c in report["changed"]:
        lines.append(f"\n{c['unit']} ({c['role']})")
        lines += [f"  {d}" for d in c["diff"] if d and d[0] in "+-"
                  and not d.startswith(("+++", "---"))]
    lines.append(f"\n{len(report['changed'])} unidad(es) con cambios · "
                 f"{report['unchanged']} sin cambios")
    with open(os.path.join(EVIDENCE, "drift_report.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup diario + diff/drift")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--inventory", default=INVENTORY)
    ap.add_argument("--as-of", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    help="fecha del backup (YYYY-MM-DD); por defecto hoy UTC")
    ap.add_argument("--drift-sample", type=int, default=0,
                    help="(simulación) inyecta cambios en N unidades para demo")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    mode = "real" if args.real else "simulate"
    units = units_from_inventory(args.inventory)
    log.info("unidades de backup: %d · fecha=%s · modo=%s", len(units), args.as_of, mode)

    if args.real:
        backend = RealBackend()
    else:
        drift = {u["key"] for u in units[:args.drift_sample]} if args.drift_sample else set()
        backend = SimulatedBackend(drift_keys=drift)

    run_backup(units, backend, args.as_of)
    report = diff_against_previous(units, args.as_of)
    write_evidence(report)

    n = len(report["changed"])
    log.info("backup OK · drift: %d unidad(es) con cambios · %d sin cambios",
             n, report["unchanged"])
    return 2 if n else 0   # exit 2 = hubo drift (lo usa el CI para notificar)


if __name__ == "__main__":
    sys.exit(main())
