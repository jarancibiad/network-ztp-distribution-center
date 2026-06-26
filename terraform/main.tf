# ===========================================================================
# Terraform — Política del firewall Palo Alto (PA-1420) como código declarativo.
# Aplica donde Terraform aporta de verdad: PAN-OS tiene provider maduro (panos),
# con state y autocorrección de drift de los objetos. Los switches/wireless NO
# se hacen con Terraform (se gestionan por template groups de Aruba Central,
# el modelo nativo de AOS 10, donde no hay provider maduro).
#
# Este módulo declara: zonas, objetos de dirección, las reglas de seguridad
# (mismo orden que firewall.j2, con la excepción mgmt→Central ANTES del deny) y
# el source-NAT. Es un módulo representativo, coherente con el resto del repo.
#
# Uso (modo real, requiere acceso al firewall):
#   terraform init
#   terraform plan      # muestra el diff contra el estado real (detección de drift)
#   terraform apply     # converge el firewall a lo declarado
# ===========================================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    panos = {
      source  = "PaloAltoNetworks/panos"
      version = "~> 1.11"
    }
  }
}

provider "panos" {
  # Credenciales por variables de entorno (nunca en el repo):
  #   PANOS_HOSTNAME, PANOS_API_KEY
  hostname = var.panos_hostname
  api_key  = var.panos_api_key
}

variable "panos_hostname" {
  description = "IP/FQDN de gestión del firewall"
  type        = string
  default     = "10.20.10.4"
}

variable "panos_api_key" {
  description = "API key de PAN-OS (vía env PANOS_API_KEY)"
  type        = string
  sensitive   = true
  default     = ""
}
