# ===========================================================================
# Makefile — Nuevo sector del CD (network-ztp)
# Ata las piezas en comandos simples. Por defecto, MODO SIMULACIÓN (sin equipos).
# Para apuntar a infra real:  make provision MODE=real   (requiere secretos)
# ===========================================================================
PYTHON ?= python3
MODE   ?= simulate

# --simulate (por defecto) o --real según MODE
FLAG := $(if $(filter real,$(MODE)),--real,--simulate)

.DEFAULT_GOAL := help

.PHONY: help setup inventory validate provision verify backup restore notify dashboard ci clean

help:  ## Muestra esta ayuda
	@echo "Targets disponibles (MODE=simulate|real):"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:  ## Instala dependencias (modo simulación)
	$(PYTHON) -m pip install -r requirements.txt

inventory:  ## Regenera la fuente de verdad (inventory/devices.csv)
	$(PYTHON) inventory/generate_inventory.py

validate:  ## Valida que las 4 plantillas rendericen (gate)
	$(PYTHON) tests/render_templates.py

provision:  ## Claim/ZTP de los equipos contra Central
	$(PYTHON) scripts/claim_devices.py $(FLAG)

verify:  ## Validación post-provisión (gate: estado + conectividad)
	$(PYTHON) scripts/validate_provisioning.py $(FLAG)

backup:  ## Export de config + diff/drift
	$(PYTHON) scripts/backup_configs.py $(FLAG)

restore:  ## Restaura desde el último backup (HOST=<hostname> o ALL=1)
	$(PYTHON) scripts/restore_config.py $(if $(ALL),--all,--host $(HOST)) $(FLAG)

notify:  ## Notifica a Slack/webhook (según evidencia)
	$(PYTHON) scripts/notify.py $(FLAG)

dashboard:  ## Panel CLI de estado
	$(PYTHON) scripts/dashboard.py

ci: validate provision verify backup dashboard notify  ## Pipeline completo (lo que corre el CI)
	@echo "== pipeline simulado completo =="

clean:  ## Borra evidencia generada (no toca backups versionados)
	rm -rf evidence/
	@echo "evidencia limpiada"
