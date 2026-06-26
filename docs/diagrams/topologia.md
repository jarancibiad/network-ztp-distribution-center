# Topología general

Arquitectura del nuevo sector del CD: doble ISP directo al firewall (perímetro),
el par **VSX** como agregación y L3 de las VLAN cableadas, el clúster **9012** como
L3 de las VLAN wireless (tráfico en túnel desde los APs), y **Aruba Central**
gestionando todo el fleet desde la nube.

```mermaid
flowchart TB
  ispa["ISP-A"]:::ext
  ispb["ISP-B"]:::ext
  fw["Palo Alto PA-1420 · HA a/p<br/>untrust + perímetro"]:::l3
  vsx["Agregación · 2x CX 8325 en VSX<br/>L3 VLAN cableadas (10/11/12/20)"]:::l3
  gw["Clúster 2x Gateway 9012 · HA<br/>L3 VLAN wireless (30/40/60)"]:::l3
  acc["48x CX 6300 acceso<br/>dual-homed (MC-LAG)"]:::node
  aps["500 APs AOS 10"]:::node
  central["Aruba Central · cloud<br/>gestión + ZTP"]:::mgmt

  ispa -- eBGP --> fw
  ispb -- eBGP --> fw
  fw -- "trust LAG ae1 · iBGP" --> vsx
  vsx -- LAG --> gw
  vsx --> acc
  acc --> aps
  aps -. "túnel GRE" .-> gw
  central -. gestiona .-> vsx
  central -. gestiona .-> acc
  central -. gestiona .-> gw

  classDef l3 fill:#d9f2e6,stroke:#0F6E56,color:#0F6E56;
  classDef node fill:#eef1f4,stroke:#888780,color:#333;
  classDef ext fill:#fde8e8,stroke:#c0392b,color:#c0392b;
  classDef mgmt fill:#e8eefc,stroke:#2c4fb0,color:#2c4fb0;
```

Los tres bloques resaltados en verde (**firewall, VSX, 9012**) son los puntos donde
vive el enrutamiento L3. El tráfico de usuario wireless viaja en **túnel GRE** desde
los APs hasta el clúster 9012; Aruba Central no está en la ruta de datos, solo
gestiona.
