# Automatización de red — Nuevo sector del CD

Aprovisionamiento, configuración y entrega operacional **zero-touch** de un sector
crítico del Centro de Distribución: **48 switches de acceso, 500 access points,
firewalls perimetrales en HA y doble enlace de Internet**, habilitado en una ventana
de **1 semana**, con operación 24×7, tolerancia a fallas y mínima intervención manual.

> **Stack:** Aruba Central (AOS 10, gestión cloud) · Aruba CX 6300/8325 (switching) ·
> Aruba Gateways 9012 + APs en túnel (wireless) · Palo Alto PA-1420 (perímetro HA) ·
> Python + Jinja2 · Terraform (política del firewall) · GitHub Actions (CI/CD).
> *(Ansible: ver §11, evolución.)*

**Idea rectora:** la fuente de verdad es **Git**, no el equipo. Toda la red es
*configuration-as-code*; los equipos se aprovisionan por **ZTP** y heredan su estado.
Un equipo es desechable: si falla, se reemplaza y vuelve a su config sin tocar la CLI.

---

## 1. Arquitectura

|Capa|Equipos|Detalle|
|-|-|-|
|Acceso|48× **CX 6300** (24p PoE+)|~10 APs c/u · independientes, **dual-homed** por MC-LAG|
|Agregación|2× **CX 8325-48Y8C** en **VSX**|48× 25G a accesos · 100G para ISL/9012/firewall|
|Wireless|APs AOS 10 en **túnel** → 2× **Gateway 9012** (HA)|3 SSIDs · gateway = L3 de las VLAN wireless|
|Firewall|2× **PA-1420** (HA activo/pasivo)|perímetro + cruces sensibles · Internet directo al FW|
|Gestión|**Aruba Central** (cloud)|ZTP por número de serie|

**Enrutamiento (L3 dividido):** el **VSX** enruta las VLAN cableadas (MGMT, AP-MGMT,
GW-MGMT, SERVERS); el **clúster 9012** enruta las VLAN de usuario wireless (WMS, CORP,
GUEST). El **Palo Alto** hace perímetro a Internet y los cruces este-oeste derivados.

**Routing dinámico (BGP de punta a punta):** **iBGP** entre el VSX y el firewall
(anuncio dinámico de las subredes internas) + **eBGP** del firewall a ambos ISP
(failover automático). El VSX alcanza las VLAN wireless por **rutas estáticas** vía el
clúster 9012 (stub), por simplicidad.

**VLANs:** 10 MGMT · 11 AP-MGMT · 12 GW-MGMT · 20 SERVERS · 30 WMS · 40 CORP ·
60 GUEST · 99 NATIVE (blackhole). **Supernet:** `10.20.0.0/16`.

Diagramas en `docs/diagrams/`: topología general, fabric MC-LAG/VSX y flujo de claim.

### Conectividad clave

* **Acceso → agregación:** cada switch sube por **MC-LAG** (2 enlaces de fibra, uno a
cada nodo VSX; ambos activos). Cada 8325 termina 48 enlaces (uno por switch).
* **Internet → firewall directo** (interfaces `untrust`, **eBGP** a cada ISP); el `trust`
del PA conecta al VSX por un **enlace de tránsito en LAG** (`ae1`, un miembro a cada
nodo VSX, /30 `10.20.200.0/30`, **iBGP**).
* **APs → clúster 9012** por **túnel GRE**; el puerto del switch es de acceso a la
VLAN 11 (el tráfico de usuario no se trunkea al borde, va tunelizado).
* **Mapa de puertos del acceso (24p):** `1–12` APs (VLAN 11, PoE+, LLDP-MED), `13–24`
cableados (deshabilitados por defecto), `25–26` uplink **MC-LAG** en fibra.

---

## 2. Decisiones de diseño y justificación

|Decisión|Por qué (y qué descarté)|
|-|-|
|**AOS 10 gestionado por Central (cloud)**|Un solo plano de control para switching y wireless · ZTP nativo. Cloud porque el escenario solo exige provisionar (Internet ya operativo).|
|**ZTP por serial + *staging* antes de rackear**|La semana de apertura se vuelve "rackear y enchufar", no configurar contra reloj. Bajo riesgo.|
|**Acceso: 48× 6300 independientes, dual-homed**|Cada switch se provisiona por su cuenta y es su propio dominio de falla. |
|**Agregación: 2× 8325-48Y8C en VSX**|Elegido por **densidad de fibra**: 48 puertos para los 48 accesos dual-homed. |
|**Wireless en túnel a clúster 9012**|**Roaming sin cortes** (el cliente mantiene IP/VLAN al moverse), política por rol y RADIUS-proxy. Descarté **AP-only/bridge** (roaming duro) y el **9240** (sobredimensionado para 500 APs).|
|**3 SSIDs (CORP/WMS/GUEST)**|Simplicidad y eficiencia de RF (menos airtime de beacons).|
|**L3 dividido (VSX cableado / 9012 wireless)**|Rendimiento a velocidad de línea en lo cableado y segmentación donde aporta; evita *hairpinning* de todo el este-oeste por el firewall.|
|**Firewall PA-1420 HA**|Dimensionado a **campus** (perímetro + cruces), no a datacenter. |
|**Internet directo al firewall**|El tráfico externo se inspecciona en el perímetro antes de entrar al fabric.|
|**Routing iBGP + eBGP**|iBGP VSX↔firewall (anuncio dinámico de subredes) + eBGP a los ISP (failover automático sin path-monitoring artesanal). Reemplaza rutas estáticas en el perímetro.|
|**Tránsito `trust` en LAG**|El enlace VSX↔firewall es un LAG (`ae1`, un miembro a cada nodo VSX): el PA-1420 tiene puertos SFP+ de sobra y se elimina el punto único.|
|**Servicios "todo en Aruba"**|NTP→VSX, DHCP→VSX (con exclusión de gateway y nodos), syslog/SNMP→Central; **DNS→resolver público**|
|**AAA admin = Central + break-glass**|Operación vía Aruba Central (RBAC/SSO de GreenLake); cuenta local solo de emergencia. Sin RADIUS/TACACS+ (ClearPass solo entraría con 802.1X).|
|**RF: AirMatch + banda por SSID**|Canales automáticos (asignación manual inviable a 500 APs); ancho angosto en alta densidad. WMS visible 2.4/5 (pistolas RF antiguas roamean mejor), CORP 5/6, GUEST 2.4/5.|
|**`mgmt` bloqueada a Internet excepto Aruba Central**|El plano de gestión solo conversa con Central (por FQDN/App-ID); todo lo demás, denegado y logueado.|
|**Backups: export diario API→Git + diff/drift**|Versionado, auditable, y detecta cambios fuera de IaC.|
|**CI/CD GitHub Actions + modo simulación**|Pipeline ejecutable y evidencia reproducible **sin equipos reales**.|

---

## 3. Supuestos declarados

* **Internet ya operativo** — el alcance es provisionar equipos, no contratar enlaces.
* **Uplinks acceso→agregación en fibra** (10/25G) por las distancias del CD; cobre solo
en el borde (APs/dispositivos).
* **~10 APs por switch** (500/48); la distribución real la define el *RF survey*.
* **Switches de acceso de 24 puertos PoE+** — decisión de diseño (el enunciado no
especifica puertos por switch).
* **Cableado físico exacto** (metrajes, transceivers) no especificado → supuesto.
* **Sin tenant/equipos reales** → modo simulación para generar logs/outputs/evidencia.
* **Seriales y MACs de ejemplo** — reemplazar por los reales de la orden de compra.

---

## 4. Aprovisionamiento (ZTP + staging)

**Patrón:** Zero-Touch Provisioning gestionado por Aruba Central, con *staging* previo
al rackeo. **Fuente de verdad:** inventario que mapea cada **número de serie →
hostname, IP de gestión, rol, grupo de Central**.

**Flujo:**

1. **Pre-staging (en bodega):** se carga en Central el mapeo serial→identidad. Cada
equipo se enciende en una red de staging con DHCP + salida a Central, se **claimea**,
baja su plantilla, **se valida** y se apaga. Llega a la nave ya configurado.
2. **Switches (AOS-CX):** heredan su plantilla del **template group** de Central
(VLANs, MC-LAG uplink, SNMPv3, seguridad de borde).
3. **APs + gateways (AOS 10):** toman su config de **grupo** desde Central; los APs
levantan el túnel al clúster 9012.
4. **Firewall (PAN-OS):** bootstrap + registro; recibe su política.
5. **Validación post-provisión:** comprobación automática de estado/conectividad como
*gate* (`scripts/validate_provisioning.py`): si algún equipo no quedó sano, el pipeline falla.
6. se rackea primero el **VSX**, luego los accesos (cablear MC-LAG) y
el wireless; como todo viene preconfigurado, levanta solo.

---

## 5. Estructura del repositorio

```
network-ztp/
├── README.md
├── Makefile                # make setup/validate/provision/backup/dashboard/ci
├── requirements.txt
├── inventory/
│   ├── devices.csv         # fuente de verdad: serial → identidad (554 equipos)
│   ├── generate_inventory.py   # generador reproducible del CSV
│   └── group_vars/         # all · access_switch · core · wireless · firewall
├── templates/              # Jinja2: access_switch · vsx · wlan_gateway · firewall
├── scripts/                # claim_devices · validate_provisioning · backup_configs · restore_config · notify · dashboard
├── terraform/              # política del firewall como código (provider panos)
├── tests/                  # render_templates (gate de plantillas)
├── backups/                # configs versionadas <fecha>/<rol>/<unidad> + manifest
├── evidence/               # run.log · dashboard.txt · JSON (claim/validación/backup/drift)
├── docs/                   # diagrams/ (Mermaid) · cuestionario-defensa.md
└── .github/workflows/      # ci.yml + nightly-backup.yml
```

---

## 6. Cómo ejecutar

**Requisitos:** Python 3.12+ · `make setup` instala las dependencias (Jinja2, PyYAML).

**Modo simulación (sin equipos — por defecto):**

```bash
make setup         # instala dependencias
make ci            # pipeline completo: valida, provisiona, backup, dashboard, notify
# o por pasos:
make validate      # render de las 4 plantillas (gate)
make provision     # claim/ZTP de los 554 equipos (simulado)
make backup        # export de config + diff/drift
make dashboard     # panel CLI de estado
```

Todo corre end-to-end sin gear y deja evidencia en `evidence/`.

**Modo real (contra Central + PAN-OS):**

1. Cargar secretos (variables de entorno / GitHub Secrets): credenciales de Central y
PAN-OS, y el webhook de Slack.
2. Ejecutar con `MODE=real`, p. ej. `make provision MODE=real` (pasa `--real` a los
scripts). Misma lógica, mismo código.

---

## 7. Backups y restauración

**Estrategia en dos capas:**

1. **Git como fuente de verdad** de la config intencional (plantillas/IaC).
2. **Export diario de la config real** vía API (Aruba Central para switches/APs/gateways
· PAN-OS para el firewall), versionado en Git.

**Estructura:** `backups/<fecha>/<rol>/<hostname>` + puntero `latest` + `manifest.json`.

**Diff diario:** cada backup se compara con el anterior; si hay cambios, se genera un
**reporte de drift** (qué equipo cambió, qué líneas) y se notifica. Si no hay cambios,
no genera ruido.

**Restauración (ejecutable):** `make restore HOST=<hostname>` (un equipo) o
`make restore ALL=1` (todo), desde el backup `latest` o `--date`. Por rol:

|Equipo|Cómo|
|-|-|
|Switch (AOS-CX)|Re-aplicar plantilla del grupo en Central y/o push del `.cfg` respaldado|
|APs / gateways|Re-aplicar config de grupo respaldada vía API de Central|
|Firewall (PAN-OS)|Importar XML respaldado + `commit`|

**Programación:** pipeline diario (`nightly-backup.yml`).

---

## 8. CI/CD y evidencia

**Plataforma:** GitHub Actions · dos workflows.

**`ci.yml`** (con cada push/PR):

```
lint → validar plantillas + tests → terraform validate →
provisión simulada → validación (gate) → backup → diff →
notificar (Slack) → subir evidencia como artifact
```

**`nightly-backup.yml`** (diario): export + diff + commit + notifica si hay drift.

**Modo simulación:** cada script corre con `--simulate` y un backend determinístico que
responde como los equipos, produciendo salidas realistas (claim de 48 switches + 500
APs + 2 gateways + 2 firewalls, validación, backup, diff) **sin gear**. Para infra real:
`MODE=real` + cargar secretos. Misma lógica, mismo código.

**Evidencia generada** (`evidence/`): `run.log` (corrida completa de `make ci`),
`dashboard.txt` (captura del panel de estado), outputs JSON (claim, validación, manifest),
`drift_report` del día y config renderizada de muestra (`evidence/rendered/`).

**Secretos:** credenciales de Central/PAN-OS como GitHub Secrets, nunca en el repo
(validado por una prueba).

---

## 9. Automatizaciones extra

El enunciado pide al menos una automatización adicional. Esta solución incluye **tres**,
ya integradas en el flujo:

* **Notificación automática** (Slack/webhook) del resultado de provisión y de drift.
* **Dashboard de estado** (CLI simple): resumen "X/552 equipos provisionados, Y con
error" para una vista de un vistazo.
* **Detección de drift**: el diff diario del backup detecta cambios fuera de IaC y los
reporta.

Además, la **validación post-provisión como gate** cubre el criterio de "proactividad
en comprobar".

---

## 10. Razonamiento de herramientas

|Herramienta|Por qué|
|-|-|
|**Aruba Central**|Plano de control único (switching + wireless), ZTP nativo, API REST|
|**Jinja2 + group_vars**|Plantillas parametrizadas: config-as-code, una plantilla por rol para N equipos|
|**Python** (pycentral, API PAN-OS)|Claim masivo por lotes, backup, notificación, dashboard|
|**GitHub Actions**|CI/CD: validación + provisión simulada (gate) + evidencia + backup diario|
|**Terraform** (provider `panos`)|Política del firewall como código declarativo (zonas, objetos, reglas, NAT), con state y autocorrección de drift|
|**Git**|Fuente de verdad, versionado, base del diff/drift|
|**Make**|Comandos reproducibles (`make ci`) para ejecutar y evaluar el repo|

*Terraform se aplica donde aporta (política del firewall, provider maduro); los
switches/wireless se gestionan por template groups de Central (modelo nativo AOS 10).
**Ansible** se deja como evolución (ver §11): el resto del flujo ya se cubre con scripts + CI.*

---

## 11. Evolución futura (fuera de alcance del entregable)

Opciones evaluadas y **deliberadamente descartadas** para no inflar el alcance de lo
solicitado; se documentan para dejar constancia del criterio:

* **Monitoreo con Prometheus/Grafana** — otro stack a montar; el dashboard simple basta.
* **Actualización de firmware automatizada** — lo cubre Aruba Central. 
* **802.1X con ClearPass** — autenticación de red; el enunciado no la pide.
* **IPSec site-to-site a la red corporativa** — el PA-1420 lo soporta; integración no
solicitada.
* **QoS de aplicación**
* **Ansible (orquestación)** — el aprovisionamiento, validación, backup y restore ya se
cubren con scripts Python + CI. Un playbook envolvería esos scripts para orquestación
idiomática; se deja como evolución para no replicar lo ya funcional. (**Terraform** sí se
incluye, para la política del firewall — ver `terraform/` y §10 —, porque ahí el provider
`panos` aplica de verdad; en switches/wireless no hay provider maduro y se usa Central.)

---

> **Nota:** este repositorio es ejecutable de extremo a extremo en **modo simulación**
> (sin tenant ni equipos reales), produciendo la evidencia que pide el entregable. La
> estructura, plantillas, scripts y pipeline son idénticos al apuntar a infra real; solo
> cambia `MODE=real` y la carga de secretos.

