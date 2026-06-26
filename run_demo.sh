#!/usr/bin/env bash
# run_demo.sh — corre el pipeline completo en modo simulación (WSL/Linux/macOS).
# Uso:  bash run_demo.sh
set -e
echo "== Demo network-ztp (simulación, sin equipos) =="

pip install -r requirements.txt -q
python3 inventory/generate_inventory.py
python3 tests/render_templates.py
python3 scripts/claim_devices.py --simulate
python3 scripts/backup_configs.py --simulate
python3 scripts/notify.py --simulate
python3 scripts/dashboard.py

echo "== Listo. Evidencia en evidence/  ·  backups en backups/ =="
