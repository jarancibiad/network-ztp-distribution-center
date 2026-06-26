#!/usr/bin/env python3
"""
render_templates.py — Valida que las 4 plantillas rendericen sin error.

Carga group_vars + un contexto per-equipo representativo y renderiza cada
plantilla. Para la WLAN además valida que el resultado sea JSON parseable.
Sirve de gate en CI: exit != 0 si alguna plantilla falla.

Uso:  python3 tests/render_templates.py
"""
from __future__ import annotations

import json
import os
import sys

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GV = os.path.join(ROOT, "inventory", "group_vars")
TPL = os.path.join(ROOT, "templates")
EVIDENCE = os.path.join(ROOT, "evidence", "rendered")

VAULT = {"vault_breakglass_pass": "REF", "vault_snmp_auth": "REF",
         "vault_snmp_priv": "REF"}


def gv(name: str) -> dict:
    return yaml.safe_load(open(os.path.join(GV, name))) or {}


# Contextos per-equipo representativos (lo que vendría del inventario/host_vars).
HOSTS = {
    "access_switch.j2": ({"access_switch.yml"},
        {"inventory_hostname": "acc-sw-r01-1", "mgmt_ip": "10.20.10.11"}),
    "vsx.j2": ({"core.yml"},
        {"inventory_hostname": "agg-01", "vsx_role": "primary",
         "svi_mgmt_ip": "10.20.10.2", "svi_apmgmt_ip": "10.20.16.2",
         "svi_gwmgmt_ip": "10.20.12.2", "svi_servers_ip": "10.20.20.2",
         "vsx_keepalive_src": "10.20.10.2", "vsx_keepalive_peer": "10.20.10.3",
         "bgp_router_id": "10.20.10.2"}),
    "wlan_gateway.j2": ({"wireless.yml"}, {}),
    "firewall.j2": ({"firewall.yml"},
        {"inventory_hostname": "fw-perim-01", "bgp_router_id": "10.20.200.2"}),
}


def main() -> int:
    env = Environment(loader=FileSystemLoader(TPL), trim_blocks=True,
                      lstrip_blocks=True)
    base = gv("all.yml")
    errors = 0
    os.makedirs(EVIDENCE, exist_ok=True)

    for tpl, (extra_gv, host) in HOSTS.items():
        ctx = dict(base)
        for g in extra_gv:
            ctx.update(gv(g))
        ctx.update(VAULT)
        ctx.update(host)
        try:
            out = env.get_template(tpl).render(**ctx)
            if tpl == "wlan_gateway.j2":
                json.loads(out)  # debe ser JSON válido
            # Vuelca la config renderizada de muestra a evidencia.
            ext = "json" if tpl == "wlan_gateway.j2" else (
                "xml" if tpl == "firewall.j2" else "cfg")
            sample = os.path.join(EVIDENCE, f"{tpl.replace('.j2','')}.{ext}")
            with open(sample, "w") as fh:
                fh.write(out)
            print(f"  ✅ {tpl:<20} render OK ({len(out.splitlines())} líneas) "
                  f"→ {os.path.relpath(sample, ROOT)}")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  ❌ {tpl:<20} {type(exc).__name__}: {exc}")

    print(f"\n{'OK' if not errors else 'FALLÓ'} · {len(HOSTS)-errors}/{len(HOSTS)} plantillas")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
