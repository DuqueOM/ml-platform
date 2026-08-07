# What every adapter must produce, so a consumer never branches on the cloud.
#
# A consumer writing `var.cloud == "gcp" ? ... : ...` has moved the difference
# back out of the adapter, which is the failure this interface exists to
# prevent. If something cannot be expressed in both vocabularies it does not
# belong in this list.

output "size_map" {
  description = "The abstract size resolved to a per-cloud instance type."
  value       = local.size_map
}

output "resource_prefix" {
  description = "Naming prefix every resource in an adapter derives from."
  value       = local.resource_prefix
}

output "common_labels" {
  description = "Labels merged with the caller's, including the ones cost reports need."
  value       = local.common_labels
}
