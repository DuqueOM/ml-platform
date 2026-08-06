#!/usr/bin/env bash
# Branch protection as code, so it is reviewable rather than remembered.
#
# Protection configured by clicking is protection nobody can diff, and the
# first sign it was loosened is usually a merge that should not have happened.
# This script is idempotent and prints what it would change.
#
# It is CONSULT in the permissions matrix: it mutates repository settings, and
# a mistake here silently removes a control everything else assumes.
#
#   ./scripts/setup_branch_protection.sh --dry-run
#   ./scripts/setup_branch_protection.sh --apply
set -euo pipefail

REPO="${REPO:-DuqueOM/ml-platform}"
BRANCH="${BRANCH:-main}"
MODE="${1:---dry-run}"

# Every required check must be a job that actually exists in a workflow.
# Requiring a check that never reports leaves a PR permanently unmergeable,
# which is how required checks get removed wholesale instead of fixed.
REQUIRED_CHECKS=("Repository invariants" "Secret scan")

payload() {
  cat <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": [$(printf '"%s",' "${REQUIRED_CHECKS[@]}" | sed 's/,$//')]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
}

echo "repository : $REPO"
echo "branch     : $BRANCH"
echo "checks     : ${REQUIRED_CHECKS[*]}"
echo

if [[ "$MODE" == "--apply" ]]; then
  gh api -X PUT "repos/$REPO/branches/$BRANCH/protection" \
    -H "Accept: application/vnd.github+json" --input - <<<"$(payload)" >/dev/null
  echo "applied. verifying…"
  gh api "repos/$REPO/branches/$BRANCH/protection" \
    --jq '{linear: .required_linear_history.enabled, force_push: .allow_force_pushes.enabled, checks: .required_status_checks.contexts}'
else
  echo "DRY RUN — would apply:"
  payload
  echo
  echo "Re-run with --apply to write. Note: enforce_admins=true means this"
  echo "applies to you too, which is the point."
fi
