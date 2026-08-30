# Cloud-specific surface

How much of the infrastructure differs per cloud, measured rather than asserted.
The generated block below is derived from `platform/terraform/`; see
`scripts/measure_cloud_surface.py` for what counts and why.

<!-- BEGIN GENERATED -->
<!-- Populated by scripts/measure_cloud_surface.py -->

**68% of Terraform is cloud-specific** (184 of 269 significant lines), against a ceiling of 75%.

| Component | Lines | Share |
| --- | --: | --: |
| `modules/` (shared) | 85 | 32% |
| `aws/` (adapter) | 100 | 37% |
| `gcp/` (adapter) | 84 | 31% |

Blank lines and comments are excluded: counting them would let a well-explained adapter read as a leaking abstraction, and would reward deleting the explanation.

<!-- END GENERATED -->
