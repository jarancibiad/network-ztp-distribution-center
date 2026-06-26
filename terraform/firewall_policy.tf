# ===========================================================================
# Política del firewall — zonas, objetos, reglas y NAT (declarativo).
# Espejo de templates/firewall.j2: misma intención, expresada como recursos
# Terraform. Si alguien cambia una regla a mano, `terraform apply` la corrige.
# ===========================================================================

# ---------------- Zonas ----------------
resource "panos_zone" "untrust" {
  name = "untrust"
  mode = "layer3"
}

resource "panos_zone" "trust" {
  name = "trust"
  mode = "layer3"
}

# ---------------- Objetos de dirección ----------------
locals {
  subnets = {
    subnet-corp    = "10.20.40.0/22"
    subnet-wms     = "10.20.30.0/23"
    subnet-guest   = "10.20.60.0/22"
    subnet-servers = "10.20.20.0/24"
    subnet-mgmt    = "10.20.10.0/24"
    subnet-apmgmt  = "10.20.16.0/22"
    subnet-gwmgmt  = "10.20.12.0/24"
  }
}

resource "panos_address_object" "subnets" {
  for_each = local.subnets
  name     = each.key
  value    = each.value
  type     = "ip-netmask"
}

# FQDN de Aruba Central (destino permitido del plano de gestión)
resource "panos_address_object" "aruba_activate" {
  name  = "fqdn-aruba-activate"
  value = "device.arubanetworks.com"
  type  = "fqdn"
}

resource "panos_address_group" "aruba_central" {
  name             = "grp-aruba-central"
  static_addresses = [panos_address_object.aruba_activate.name]
}

# ---------------- Security policy (ORDEN: excepción mgmt→Central ANTES del deny) ----------------
resource "panos_security_policy" "rules" {
  rule {
    name                  = "mgmt-to-aruba-central"
    source_zones          = [panos_zone.trust.name]
    destination_zones     = [panos_zone.untrust.name]
    source_addresses      = ["subnet-mgmt", "subnet-apmgmt", "subnet-gwmgmt"]
    destination_addresses = [panos_address_group.aruba_central.name]
    applications          = ["ssl", "dns", "ntp"]
    services              = ["application-default"]
    action                = "allow"
  }
  rule {
    name                  = "corp-to-internet"
    source_zones          = [panos_zone.trust.name]
    destination_zones     = [panos_zone.untrust.name]
    source_addresses      = ["subnet-corp"]
    destination_addresses = ["any"]
    applications          = ["web-browsing", "ssl", "dns"]
    services              = ["application-default"]
    action                = "allow"
  }
  rule {
    name                  = "guest-to-internet"
    source_zones          = [panos_zone.trust.name]
    destination_zones     = [panos_zone.untrust.name]
    source_addresses      = ["subnet-guest"]
    destination_addresses = ["any"]
    applications          = ["web-browsing", "ssl", "dns"]
    services              = ["application-default"]
    action                = "allow"
  }
  rule {
    name                  = "servers-updates"
    source_zones          = [panos_zone.trust.name]
    destination_zones     = [panos_zone.untrust.name]
    source_addresses      = ["subnet-servers"]
    destination_addresses = ["any"]
    applications          = ["ssl"]
    services              = ["application-default"]
    action                = "allow"
  }
  rule {
    name                  = "deny-wms-internet"
    source_zones          = [panos_zone.trust.name]
    destination_zones     = [panos_zone.untrust.name]
    source_addresses      = ["subnet-wms"]
    destination_addresses = ["any"]
    applications          = ["any"]
    services              = ["any"]
    action                = "deny"
  }
  rule {
    name                  = "deny-mgmt-internet"
    source_zones          = [panos_zone.trust.name]
    destination_zones     = [panos_zone.untrust.name]
    source_addresses      = ["subnet-mgmt", "subnet-apmgmt", "subnet-gwmgmt"]
    destination_addresses = ["any"]
    applications          = ["any"]
    services              = ["any"]
    action                = "deny"
  }
  rule {
    name                  = "deny-inbound"
    source_zones          = [panos_zone.untrust.name]
    destination_zones     = ["any"]
    source_addresses      = ["any"]
    destination_addresses = ["any"]
    applications          = ["any"]
    services              = ["any"]
    action                = "deny"
  }
}

# ---------------- NAT (source PAT a la interfaz del ISP activo) ----------------
resource "panos_nat_policy" "src_internet" {
  rule {
    name                  = "src-nat-internet"
    source_zones          = [panos_zone.trust.name]
    destination_zone      = panos_zone.untrust.name
    source_addresses      = ["any"]
    destination_addresses = ["any"]
    service               = "any"

    source_translation {
      type      = "dynamic-ip-and-port"
      interface = "ethernet1/1"
    }
  }
}
