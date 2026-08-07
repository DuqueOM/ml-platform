# AWS-specific inputs. The asymmetry against gcp/variables.tf is real and worth
# seeing: EKS requires roles, subnets and OIDC thumbprints that GKE creates or
# infers. Hiding that behind a shared variable would make the two configs look
# alike while behaving differently.

variable "service_name" { type = string }
variable "environment" { type = string }
variable "region" {
  type    = string
  default = "us-east-1"
}
variable "node_count" {
  type    = number
  default = 2
}
variable "machine_size" {
  type    = string
  default = "small"
}
variable "labels" {
  type    = map(string)
  default = {}
}

variable "kubernetes_version" {
  type    = string
  default = "1.31"
}
variable "cluster_role_arn" {
  description = "IAM role the EKS control plane assumes."
  type        = string
}
variable "node_role_arn" {
  description = "IAM role the node group assumes."
  type        = string
}
variable "subnet_ids" {
  description = "Subnets for the cluster. At least two AZs, or EKS refuses to create."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "EKS requires subnets in at least two availability zones."
  }
}
variable "oidc_thumbprints" {
  description = "Root CA thumbprints for the cluster's OIDC issuer."
  type        = list(string)
}
