# State for prod only, with a DynamoDB lock table. Separate buckets per
# environment for the same reason as GCP: a prefix typo must not be able to
# read another environment's state.
bucket         = "ml-platform-tfstate-prod"
key            = "aws/service-runtime.tfstate"
dynamodb_table = "ml-platform-tflock-prod"
encrypt        = true
