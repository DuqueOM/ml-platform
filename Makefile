# ml-platform — entry points.
#
# Every target here is also a CI step or an acceptance criterion. A target that
# only works on the author's machine is not an entry point, it is a note.

SHELL := /bin/bash
.DEFAULT_GOAL := help
CLUSTER := ml-platform-local
CTX := kind-$(CLUSTER)
LOCAL := platform/local
# Kept in step with `images:` in platform/kubernetes/overlays/local, which is
# what the pod actually pulls — and with imagePullPolicy: Never, a tag that
# does not match here fails as ErrImageNeverPull rather than as a typo.
SERVICE_IMAGE := ml-platform/demand-forecast:local
SERVICE_NS := demand-forecast-local

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	 awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

# --- gates ------------------------------------------------------------------

# `verify` must be a SUPERSET of the gate commands in ci.yml, and
# tests/test_verify_parity.py fails when it is not.
#
# It claimed to be "what CI runs" while running 10 of 26, with `mypy libs/`
# where CI checks `libs/ scripts/ projects/…` — the narrow-type-gate defect
# this repository had already found, fixed in CI and left here. QA-4 round
# seven found it by planting an untyped function in `scripts/` and watching
# `make verify` pass while CI failed.
#
# Kept as an explicit list rather than generated from the workflow: a target
# that computes itself cannot be read, and reading it is the point. The test is
# what keeps the list honest.
.PHONY: verify
verify: ## Run every repository gate (superset of CI's; see RUNBOOK for what it still omits)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy libs/ scripts/ projects/demand-forecast/src/ projects/rag-assistant/src/ projects/store-assistant/src/ orchestration/
	uv run bandit -c pyproject.toml -r libs/ scripts/ projects/ orchestration/ -ll -q
	uv run python scripts/sync_agentic_adapters.py --check
	uv run python scripts/validate_agentic_surface.py --strict
	uv run python scripts/validate_quality_gates.py
	uv run python scripts/check_doc_coherence.py
	uv run python scripts/check_ci_references.py
	uv run python scripts/check_action_pins.py
	uv run python scripts/check_artifact_compatibility.py
	uv run python scripts/check_serving_can_load_artifact.py
	uv run python scripts/check_baselines_expiry.py
	uv run python scripts/check_contract_deviations.py --check
	uv run python scripts/check_dashboard_inventory.py
	uv run python scripts/check_gitleaks_pin.py
	uv run python scripts/check_library_reuse.py
	uv run python scripts/check_mcp_registry.py
	uv run python scripts/check_test_clock_isolation.py
	uv run python scripts/check_template_render_safety.py
	uv run python scripts/check_thresholds.py
	uv run python scripts/check_upstream_parity.py
	uv run python scripts/check_version_consistency.py
	uv run python scripts/ci_verify_yaml.py
	uv run python scripts/measure_cloud_surface.py --check
	uv run python scripts/check_technology_inventory.py --check
	uv run python scripts/check_implementation_status.py --check
	uv run python scripts/check_readme.py
	@# The suite, measured exactly as CI measures it: one run, then every
	@# coverage floor. A single run, so the floors cost the tracing overhead
	@# rather than a second pass of the suite.
	uv run coverage erase
	uv run coverage run --branch --source=libs,projects,orchestration,scripts -m pytest -q
	uv run coverage combine
	uv run python scripts/check_coverage_floors.py --xml coverage.xml

.PHONY: sync
sync: ## Re-render agentic surfaces and refresh derived docs
	uv run python scripts/sync_agentic_adapters.py
	uv run python scripts/check_technology_inventory.py --write
	uv run python scripts/check_contract_deviations.py --write
	uv run python scripts/check_implementation_status.py --write
	uv run python scripts/check_readme.py --write

# --- local validation stack (Phase 1b) --------------------------------------

.PHONY: local-preflight
local-preflight: ## Check the stack fits in measured memory before creating anything
	uv run python scripts/local/preflight.py

.PHONY: local-up
local-up: local-preflight ## Create the local cluster and bring up the full stack
	@kind get clusters 2>/dev/null | grep -qx "$(CLUSTER)" \
	  && echo "cluster $(CLUSTER) already exists" \
	  || kind create cluster --config $(LOCAL)/kind-cluster.yaml
	@# The stack's MinIO, retired by R15-20 for an image that can be pulled. `apply`
	@# never deletes, and its Service holds the NodePort the object store takes.
	@kubectl --context $(CTX) -n ml-platform delete --ignore-not-found \
	  deployment/minio service/minio secret/minio-credentials
	kubectl --context $(CTX) apply -f $(LOCAL)/manifests/
	@echo "waiting for the stack to become ready…"
	@# On a timeout `kubectl wait --all` reports every deployment it had not yet
	@# confirmed, so a single failing one is named alongside five healthy ones
	@# (QA-4 round eighteen). explain_unavailable.py names only the unavailable
	@# ones, with each pod's reason.
	@kubectl --context $(CTX) -n ml-platform wait --for=condition=available \
	  --timeout=300s deployment --all >/dev/null \
	  || { uv run python scripts/local/explain_unavailable.py; exit 1; }
	@# The buckets the lakehouse and DVC address. Nothing created them, so they
	@# existed only while someone had made them by hand (R15-20's remediation).
	@uv run python scripts/local/provision_object_store.py
	@$(MAKE) --no-print-directory local-endpoints

.PHONY: local-endpoints
local-endpoints: ## Print the local stack's URLs
	@echo ""
	@echo "  postgres   localhost:15432   (db/user: mlplatform)"
	@echo "  s3 api     http://localhost:19000   (object store: RustFS)"
	@echo "  s3 console http://localhost:19001"
	@echo "  jaeger     http://localhost:16686"
	@echo "  prometheus http://localhost:19090"
	@echo "  grafana    http://localhost:13000"
	@echo ""

.PHONY: local-dashboards
local-dashboards: ## Sync platform/observability/dashboards/ into Grafana
	kubectl --context $(CTX) -n ml-platform create configmap grafana-dashboards \
	  --from-file=platform/observability/dashboards/ \
	  --dry-run=client -o yaml | kubectl --context $(CTX) apply -f -
	kubectl --context $(CTX) -n ml-platform rollout restart deploy/grafana
	kubectl --context $(CTX) -n ml-platform rollout status deploy/grafana --timeout=180s

.PHONY: local-serve
local-serve: ## Build the service image, load it into kind, roll the Deployment onto it, and wait for Ready
	docker build -t $(SERVICE_IMAGE) services/demand-forecast-serving
	kind load docker-image $(SERVICE_IMAGE) --name $(CLUSTER)
	kubectl --context $(CTX) apply -k platform/kubernetes/overlays/local
	@# The tag is fixed, so a rebuilt image changes nothing `apply` can see: the
	@# Deployment is identical, no rollout happens, and the running pod keeps the
	@# OLD binary while this target reports success. Measured 2026-09-30: after a
	@# rebuild from ml-service-template v0.30.2 the pod still ran the image loaded
	@# a week earlier, and every L3 measurement taken after it measured that.
	@# Restarting the rollout is what makes a rebuild reach the cluster, and
	@# tests/local/test_service_runs.py checks that it did.
	kubectl --context $(CTX) -n $(SERVICE_NS) rollout restart deployment/demand-forecast
	kubectl --context $(CTX) -n $(SERVICE_NS) rollout status deployment/demand-forecast --timeout=300s
	@echo "waiting for a Ready pod — the first claim in this repository that is not about YAML…"
	kubectl --context $(CTX) -n $(SERVICE_NS) wait --for=condition=ready \
	  pod -l app=demand-forecast --timeout=300s
	@echo ""
	@echo "  port-forward:  kubectl --context $(CTX) -n $(SERVICE_NS) port-forward svc/demand-forecast 18080:80"
	@echo "  then:          curl -fsS localhost:18080/ready"
	@echo ""

.PHONY: local-serve-down
local-serve-down: ## Remove the service, leaving the rest of the local stack up
	kubectl --context $(CTX) delete -k platform/kubernetes/overlays/local --ignore-not-found

.PHONY: local-verify
local-verify: ## Assert the local stack actually works (not merely that it started)
	uv run pytest tests/local -q -m local

.PHONY: local-down
local-down: ## Destroy the local cluster completely
	kind delete cluster --name $(CLUSTER)
