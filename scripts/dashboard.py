#!/usr/bin/env python3
"""
dashboard.py — Panel CLI de estado de la red (automatización extra).

Lee la evidencia (claim + backup/drift) y muestra un resumen de un vistazo:
cuántos equipos quedaron aprovisionados por tipo y el estado de drift del
último backup. Solo lectura; no toca equipos.

Uso:  python3 scripts/dashboard.py
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(ROOT, "evidence")

ORDER = ["switch_agg", "switch_access", "ap", "gateway", "firewall"]
LABEL = {"switch_agg": "Agregación", "switch_access": "Acceso",
         "ap": "APs", "gateway": "Gateways", "firewall": "Firewall"}


def _load(path: str):
    try:
        return json.load(open(path))
    except FileNotFoundError:
        return None


def line(s: str = "") -> None:
    print(f" {s}")


def main() -> int:
    claim = _load(os.path.join(EV, "claim", "claim_summary.json"))
    drift = _load(os.path.join(EV, "backup", "drift_report.json"))

    bar = "─" * 52
    print(f"┌{bar}┐")
    line("CD-PRINCIPAL · Estado de red")
    print(f"├{bar}┤")

    # --- Aprovisionamiento ---
    if claim:
        run, summ = claim["run"], claim["summary"]
        line(f"Aprovisionamiento  ({run['mode']} · {run['timestamp']})")
        for dt in ORDER:
            st = summ["by_type"].get(dt)
            if not st:
                continue
            total = sum(st.values())
            ok = st.get("claimed", 0)
            extra = " (PAN-OS)" if dt == "firewall" else ""
            mark = "✅" if (ok == total or dt == "firewall") else "⚠️"
            line(f"  {mark} {LABEL[dt]:<11} {ok:>3}/{total:<3} claimed{extra}")
        bs = summ["by_status"]
        line(f"  ── TOTAL {bs.get('claimed',0)} claimed · "
             f"{bs.get('skipped',0)} skipped · {bs.get('failed',0)} failed")
    else:
        line("Aprovisionamiento  · sin evidencia (corré claim_devices.py)")

    print(f"├{bar}┤")

    # --- Backups / Drift ---
    if drift:
        changed = drift.get("changed", [])
        line(f"Backups / Drift    ({drift['date']} vs {drift.get('previous','—')})")
        if drift.get("note"):
            line(f"  {drift['note']}")
        elif not changed:
            line(f"  ✅ sin drift · {drift.get('unchanged',0)} unidades estables")
        else:
            units = ", ".join(c["unit"] for c in changed)
            line(f"  ⚠️  {len(changed)} con cambios · "
                 f"{drift.get('unchanged',0)} sin cambios")
            line(f"     → {units}")
    else:
        line("Backups / Drift    · sin evidencia (corré backup_configs.py)")

    print(f"└{bar}┘")
    return 0


if __name__ == "__main__":
    sys.exit(main())
