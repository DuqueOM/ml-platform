# State for prod only. Separate BUCKETS, not separate prefixes in one bucket:
# a prefix typo inside a shared bucket silently reads another environment's
# state, and the first symptom is a plan proposing to destroy production.
bucket = "ml-platform-tfstate-prod"
prefix = "gcp/service-runtime"
