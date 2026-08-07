terraform {
  required_version = ">= 1.7"
}

locals {
  resource_prefix = "${var.service_name}-${var.environment}"

  # Sizes are named by intent and resolved per cloud. The two columns are the
  # honest form of "multi-cloud": not one instance type that exists on both,
  # but one INTENT with a recorded translation.
  size_map = {
    gcp = {
      small  = "e2-standard-2"
      medium = "e2-standard-4"
      large  = "e2-standard-8"
    }[var.machine_size]
    aws = {
      small  = "t3.medium"
      medium = "m6i.xlarge"
      large  = "m6i.2xlarge"
    }[var.machine_size]
  }

  common_labels = merge(var.labels, {
    service     = var.service_name
    environment = var.environment
    managed_by  = "terraform"
    # Cost attribution is not optional metadata here: the plan makes an empty
    # project after teardown an acceptance criterion, and an unlabelled
    # resource is one nothing can attribute or find.
    cost_center = "ml-platform"
  })
}
