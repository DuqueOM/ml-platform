# ml-platform — entry points.
#
# Every target here is also a CI step or an acceptance criterion. A target that
# only works on the author's machine is not an entry point, it is a note.

SHELL := /bin/bash
.DEFAULT_GOAL := help
CLUSTER := ml-platform-local
CTX := kind-$(CLUSTER)
LOCAL := platform/local

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	 awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

# --- gates ------------------------------------------------------------------

.PHONY: verify
verify: ## Run every repository gate (what CI runs)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy libs/
	uv run python scripts/sync_agentic_adapters.py --check
	uv run python scripts/validate_agentic_surface.py --strict
	uv run python scripts/check_doc_coherence.py
	uv run python scripts/check_ci_references.py
	uv run python scripts/check_implementation_status.py --check
	uv run pytest -q

.PHONY: sync
sync: ## Re-render agentic surfaces and refresh derived docs
	uv run python scripts/sync_agentic_adapters.py
	uv run python scripts/check_implementation_status.py --write

# --- local validation stack (Phase 1b) --------------------------------------

.PHONY: local-preflight
local-preflight: ## Check the stack fits in measured memory before creating anything
	uv run python scripts/local/preflight.py

.PHONY: local-up
local-up: local-preflight ## Create the local cluster and bring up the full stack
	@kind get clusters 2>/dev/null | grep -qx "$(CLUSTER)" \
	  && echo "cluster $(CLUSTER) already exists" \
	  || kind create cluster --config $(LOCAL)/kind-cluster.yaml
	kubectl --context $(CTX) apply -f $(LOCAL)/manifests/
	@echo "waiting for the stack to become ready…"
	kubectl --context $(CTX) -n ml-platform wait --for=condition=available \
	  --timeout=300s deployment --all
	@$(MAKE) --no-print-directory local-endpoints

.PHONY: local-endpoints
local-endpoints: ## Print the local stack's URLs
	@echo ""
	@echo "  postgres   localhost:15432   (db/user: mlplatform)"
	@echo "  minio api  http://localhost:19000"
	@echo "  minio ui   http://localhost:19001"
	@echo "  jaeger     http://localhost:16686"
	@echo "  prometheus http://localhost:19090"
	@echo "  grafana    http://localhost:13000"
	@echo ""

.PHONY: local-verify
local-verify: ## Assert the local stack actually works (not merely that it started)
	uv run pytest tests/local -q -m local

.PHONY: local-down
local-down: ## Destroy the local cluster completely
	kind delete cluster --name $(CLUSTER)
