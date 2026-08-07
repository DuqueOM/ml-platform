# GCP-specific inputs. Everything else comes from the shared module.

variable "project_id" {
  description = <<-EOT
    Target GCP project. Must be NEW and EMPTY (constraint S3).

    Greenfield is what makes teardown verifiable: when every resource in a
    project was created by this configuration, an empty project afterwards is
    proof that nothing survived. A shared project can never produce that proof.
  EOT
  type        = string
}

variable "service_name" { type = string }
variable "environment" { type = string }
variable "region" {
  type    = string
  default = "us-central1"
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
