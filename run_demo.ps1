# run_demo.ps1 — corre el pipeline completo en modo simulación (Windows 11).
# Uso:  powershell -ExecutionPolicy Bypass -File run_demo.ps1
Write-Host "== Demo network-ztp (simulacion, sin equipos) ==" -ForegroundColor Cyan

pip install -r requirements.txt
python inventory/generate_inventory.py
python tests/render_templates.py
python scripts/claim_devices.py --simulate
python scripts/backup_configs.py --simulate
python scripts/notify.py --simulate
python scripts/dashboard.py

Write-Host "== Listo. Evidencia en evidence/  backups en backups/ ==" -ForegroundColor Green
