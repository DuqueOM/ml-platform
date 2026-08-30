# GCP adapter. Everything cloud-specific in this repository's runtime lives
# here and in its AWS sibling — that is the claim `measure_cloud_surface.py`
# checks, and the number it reports is the claim's evidence.

terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Partial configuration: the bucket differs per environment and is supplied
  # by `backend-configs/<env>.hcl`. Hardcoding one bucket is how a dev apply
  # ends up mutating production state.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "runtime" {
  source = "../modules/service-runtime"

  service_name = var.service_name
  environment  = var.environment
  region       = var.region
  node_count   = var.node_count
  machine_size = var.machine_size
  labels       = var.labels
}

resource "google_container_cluster" "primary" {
  name     = module.runtime.resource_prefix
  location = var.region

  # The default node pool is removed and replaced: Terraform cannot manage the
  # default pool's lifecycle properly, so changing its shape later forces a
  # cluster replacement.
  remove_default_node_pool = true
  initial_node_count       = 1

  workload_identity_config {
    # Workload Identity, never a node service-account key. A key is a
    # long-lived credential in a file, which is the thing every incident
    # runbook is written about.
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  release_channel {
    channel = var.environment == "prod" ? "STABLE" : "REGULAR"
  }

  # Explicit, and false on purpose.
  #
  # `hashicorp/google ~> 6.0` defaults this to TRUE, so `terraform destroy`
  # REFUSES to delete the cluster — and the technical plan makes destroy the
  # cost control: "infrastructure exists only inside validation windows;
  # `terraform destroy` is an acceptance criterion, not a follow-up, and the
  # phase is not complete until the billing export shows zero standing spend."
  # A cluster that cannot be destroyed leaves the bill running, which is the
  # one failure the greenfield posture exists to prevent.
  #
  # Written out rather than inherited either way: a default that decides
  # whether the plan's only cost control works is a decision, and it belongs in
  # the file where someone can dispute it. If this repository ever runs a
  # cluster that outlives a window, this line is where that changes.
  deletion_protection = false

  resource_labels = module.runtime.common_labels
}

resource "google_container_node_pool" "service" {
  name       = "${module.runtime.resource_prefix}-pool"
  cluster    = google_container_cluster.primary.id
  node_count = var.node_count

  node_config {
    machine_type = module.runtime.size_map.gcp
    labels       = module.runtime.common_labels

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}
