# AWS adapter. The mirror of gcp/, consuming the SAME shared module with the
# same inputs — which is the property that makes "one definition, two clouds"
# a fact rather than a slogan.

terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # S3 + DynamoDB, per environment. DynamoDB is the lock: without it two
  # concurrent applies interleave writes and corrupt the state file, and the
  # corruption is discovered on the next plan rather than at the moment.
  backend "s3" {}
}

provider "aws" {
  region = var.region
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

resource "aws_eks_cluster" "primary" {
  name     = module.runtime.resource_prefix
  role_arn = var.cluster_role_arn
  version  = var.kubernetes_version

  vpc_config {
    subnet_ids = var.subnet_ids
    # Private endpoint by default; a public API server is a control plane on
    # the internet, and the value of that convenience is never the risk.
    endpoint_private_access = true
    endpoint_public_access  = var.environment != "prod"
  }

  access_config {
    # API mode: IAM identities map to Kubernetes permissions through EKS access
    # entries rather than the aws-auth ConfigMap, whose one bad edit locks
    # every operator out of the cluster at once.
    authentication_mode = "API"
  }

  tags = module.runtime.common_labels
}

resource "aws_eks_node_group" "service" {
  cluster_name    = aws_eks_cluster.primary.name
  node_group_name = "${module.runtime.resource_prefix}-pool"
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.subnet_ids
  instance_types  = [module.runtime.size_map.aws]

  scaling_config {
    desired_size = var.node_count
    min_size     = var.node_count
    max_size     = var.node_count * 2
  }

  update_config {
    max_unavailable = 1
  }

  tags = module.runtime.common_labels
}

# IRSA, the counterpart to GCP's Workload Identity. Both adapters reach the
# same destination — a pod identity with no long-lived key — through entirely
# different resources, which is precisely why this belongs in an adapter and
# not in the shared module.
resource "aws_iam_openid_connect_provider" "cluster" {
  url             = aws_eks_cluster.primary.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = var.oidc_thumbprints

  tags = module.runtime.common_labels
}
