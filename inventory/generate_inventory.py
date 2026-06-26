#!/usr/bin/env python3
"""
generate_inventory.py — Genera inventory/devices.csv (fuente de verdad).

Mapea, por cada equipo: número de serie → identidad (hostname, IP de gestión,
rol, grupo de Central). Es lo que consume el ZTP y los scripts de claim.

A escala del diseño:
  -  48 switches de acceso      (Aruba CX 6300, 24p PoE+)   → grp-acceso
  -   2 switches de agregación  (Aruba CX 8325-48Y8C, VSX)  → grp-core
  - 500 access points           (AOS 10, túnel a 9012)      → grp-aps-<zona>
  -   2 gateways                (Aruba 9012, clúster HA)    → grp-gateways
  -   2 firewalls               (Palo Alto PA-1420, HA)     → n/a (gestión PAN-OS)

Idempotente: produce siempre el mismo CSV. Seriales/MACs son placeholders;
reemplazar por los reales de la orden de compra antes del claim.

Uso:  python3 inventory/generate_inventory.py
"""
import csv
import os

OUT = os.path.join(os.path.dirname(__file__), "devices.csv")
SITE = "CD-PRINCIPAL"
HEADER = ["serial", "mac", "device_type", "model", "role", "site",
          "central_group", "hostname", "mgmt_ip", "zone"]

# Zonas de APs (grupos de Central por RF) — suman 500
AP_ZONES = [
    ("bodega-principal", 280),
    ("andenes", 80),
    ("oficinas", 60),
    ("zonas-comunes", 50),
    ("perimetro", 30),
]


def mac(prefix: str, n: int) -> str:
    h = f"{n:06x}"
    return f"{prefix}:{h[0:2]}:{h[2:4]}:{h[4:6]}"


def main() -> None:
    rows = []

    # --- 2 agregación VSX (CX 8325-48Y8C) ---
    for i in range(1, 3):
        rows.append([
            f"CN83{i:03d}AGGX", mac("a8:b3:25", 0xF000 + i), "switch_agg",
            "8325-48Y8C", "aggregation", SITE, "grp-core",
            f"agg-{i:02d}", f"10.20.10.{1 + i}", "",     # .2 / .3 (también NTP)
        ])

    # --- 48 switches de acceso (CX 6300) ---
    for i in range(1, 49):
        rack = ((i - 1) // 4) + 1          # 12 racks, 4 switches por rack
        slot = ((i - 1) % 4) + 1
        rows.append([
            f"CN63{i:03d}ACCX", mac("a6:b3:00", i), "switch_access",
            "6300-24p-PoE", "access", SITE, "grp-acceso",
            f"acc-sw-r{rack:02d}-{slot}", f"10.20.10.{10 + i}", f"rack{rack:02d}",
        ])

    # --- 500 APs (AOS 10) por zona ---
    ap_i = 0
    for zone, count in AP_ZONES:
        z3 = zone[:3]
        for _ in range(count):
            ap_i += 1
            rows.append([
                f"CNAP{ap_i:05d}", mac("b4:c5:d6", ap_i), "ap",
                "AP-635", "ap", SITE, f"grp-aps-{zone}",
                f"ap-{z3}-{ap_i:04d}", "dhcp", zone,
            ])

    # --- 2 gateways (Aruba 9012, clúster HA) ---
    for i in range(1, 3):
        rows.append([
            f"CN90{i:03d}GWMB", mac("c9:01:20", i), "gateway",
            "9012", "gateway", SITE, "grp-gateways",
            f"gw-mob-{i:02d}", f"10.20.12.{1 + i}", "",   # GW-MGMT VLAN 12
        ])

    # --- 2 firewalls (PA-1420, HA) — gestión directa PAN-OS (API / HA), no Central ---
    for i in range(1, 3):
        rows.append([
            f"PA14{i:03d}FWPB", mac("d1:42:00", i), "firewall",
            "PA-1420", "perimeter", SITE, "n/a",
            f"fw-perim-{i:02d}", f"10.20.10.{3 + i}", "",  # .4 / .5
        ])

    with open(OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)

    n = {dt: sum(1 for r in rows if r[2] == dt) for dt in
         ("switch_access", "switch_agg", "ap", "gateway", "firewall")}
    print(f"[ok] {len(rows)} equipos escritos en {OUT}")
    print(f"     acceso={n['switch_access']} agregacion={n['switch_agg']} "
          f"aps={n['ap']} gateways={n['gateway']} firewalls={n['firewall']}")


if __name__ == "__main__":
    main()
