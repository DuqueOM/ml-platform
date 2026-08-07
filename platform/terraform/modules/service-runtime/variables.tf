# The cloud-agnostic contract every service runtime satisfies.
#
# This file is the measured boundary. Phase 2's deliverable is not "it runs on
# two clouds" — anything runs on two clouds if you write it twice. It is that
# the DIFFERENCE is small, isolated and counted, which is why
# `scripts/measure_cloud_surface.py` reports lines of cloud-specific code per
# component and the plan records the number.
#
# A variable belongs here when both clouds need it and neither names it in its
# own vocabulary. `region` qualifies. `network_self_link` does not, because it
# is a GCP concept with no AWS counterpart, and smuggling it in would move the
# difference from a visible adapter into an invisible one.

variable "service_name" {
  description = "Service this runtime hosts. Used for resource names and labels."
  type        = string

  validation {
    # Both clouds accept this shape; GCP is the stricter of the two, so
    # satisfying it satisfies AWS. Rejecting here rather than at apply time
    # turns a fifteen-minute failure into an immediate one.
    condition     = can(regex("^[a-z]([-a-z0-9]{0,38}[a-z0-9])?$", var.service_name))
    error_message = "service_name must be lowercase alphanumeric with hyphens, 1-40 chars, starting with a letter."
  }
}

variable "environment" {
  description = "Deployment environment. Drives naming, sizing and the state prefix."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "region" {
  description = "Cloud region. The one geography concept both clouds share."
  type        = string
}

variable "node_count" {
  description = "Nodes in the service pool."
  type        = number
  default     = 2

  validation {
    # A floor of 2, not 1: a single node makes a PodDisruptionBudget
    # unsatisfiable, so a drain during an upgrade blocks forever rather than
    # failing visibly.
    condition     = var.node_count >= 2
    error_message = "node_count must be at least 2; one node makes a PodDisruptionBudget unsatisfiable."
  }
}

variable "machine_size" {
  description = <<-EOT
    Abstract size — "small", "medium", "large" — mapped to each cloud's own
    instance vocabulary inside its adapter.

    Deliberately NOT a machine type. Accepting "e2-standard-4" here would put a
    GCP identifier in the shared contract, and the AWS adapter would then
    either translate it or ignore it. Both are worse than naming the intent.
  EOT
  type        = string
  default     = "small"

  validation {
    condition     = contains(["small", "medium", "large"], var.machine_size)
    error_message = "machine_size must be one of: small, medium, large."
  }
}

variable "labels" {
  description = "Labels applied to every resource. Cost attribution depends on them."
  type        = map(string)
  default     = {}
}
