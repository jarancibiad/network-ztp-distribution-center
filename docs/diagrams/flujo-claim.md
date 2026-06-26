# Flujo de aprovisionamiento (ZTP + staging)

El equipo se provisiona **en bodega, antes de rackear**: se claimea por número de
serie contra Aruba Central, baja su plantilla, se valida y se apaga. Llega a la nave
ya configurado, de modo que la semana de apertura es "rackear y enchufar".

```mermaid
sequenceDiagram
  participant CSV as devices.csv (serial→identidad)
  participant ENG as Ingeniero / CI
  participant CEN as Aruba Central (cloud)
  participant DEV as Equipo (staging)

  ENG->>CSV: lee la fuente de verdad
  ENG->>CEN: carga mapeo serial→grupo + identidad
  ENG->>DEV: enciende en mesa de staging (DHCP + salida a Central)
  DEV->>CEN: phone-home por número de serie
  CEN-->>DEV: asigna grupo + baja plantilla
  DEV->>DEV: aplica config y valida
  ENG->>DEV: apaga y rackea (ya configurado)
  Note over DEV: En la nave: cablear uplink MC-LAG → sube en producción
```

El claim lo orquesta `scripts/claim_devices.py`, que recorre `devices.csv` y, por
cada equipo, ejecuta el ciclo de arriba contra la API de Central (o el backend
simulado, que genera la evidencia sin equipos reales).
