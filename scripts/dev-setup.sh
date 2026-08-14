#!/usr/bin/env bash
# Developer environment setup: wire the git hooks, and prove they are wired.
#
# scripts/bootstrap.sh owns the environment. This owns the commit path, and it
# is the contract for "your dev environment is set up correctly":
#
#   1. uv and a synced workspace exist (otherwise: run bootstrap.sh first)
#   2. .pre-commit-config.yaml is valid
#   3. .git/hooks/pre-commit AND .git/hooks/commit-msg exist and are pre-commit's
#   4. every hook environment is built, so the first commit is not a five-minute wait
#
# Point 3 is the reason this is a script rather than a line in a README.
# .pre-commit-config.yaml declares conventional-pre-commit with
# `stages: [commit-msg]` and does NOT declare `default_install_hook_types`, so
# a plain `pre-commit install` wires the pre-commit stage only and leaves the
# commit-msg hook unarmed. The config then looks enforced, the CI lane enforces
# it, and the difference shows up as a rejected push. Both hook types are
# installed here explicitly.
#
#   scripts/dev-setup.sh              install and verify the hooks
#   scripts/dev-setup.sh --check      verify only; changes nothing; non-zero if unwired
#   scripts/dev-setup.sh --run-hooks  also run every hook over the whole tree
#   scripts/dev-setup.sh --help
#
# --run-hooks is opt-in because the fixing hooks REWRITE files, and --all-files
# aims them at the whole repository rather than at what you touched. It reports
# everything it changed. The default run touches nothing but .git/hooks/.
#
# Idempotent: `pre-commit install --overwrite` replaces the hook file rather
# than appending to it, so running this ten times leaves one hook, not ten.

set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -t 1 ]]; then
  C_OK=$'\033[0;32m'; C_WARN=$'\033[1;33m'; C_ERR=$'\033[0;31m'; C_HEAD=$'\033[1;34m'; C_OFF=$'\033[0m'
else
  C_OK=''; C_WARN=''; C_ERR=''; C_HEAD=''; C_OFF=''
fi

head_() { printf '\n%s== %s%s\n' "$C_HEAD" "$1" "$C_OFF"; }
ok()    { printf '  %sok%s    %s\n' "$C_OK" "$C_OFF" "$1"; }
warn()  { printf '  %swarn%s  %s\n' "$C_WARN" "$C_OFF" "$1"; }
note()  { printf '        %s\n' "$1"; }
die() {
  printf '\n%sFAIL%s  %s\n' "$C_ERR" "$C_OFF" "$1" >&2
  shift
  for line in "$@"; do printf '      %s\n' "$line" >&2; done
  exit 1
}

on_err() {
  local code=$?
  printf '\n%sFAIL%s  dev-setup aborted at %s line %s (exit %s). The hooks may be half-wired; re-run this script.\n' \
    "$C_ERR" "$C_OFF" "${BASH_SOURCE[1]}" "${BASH_LINENO[0]}" "$code" >&2
}
trap on_err ERR

CHECK_ONLY=false
RUN_HOOKS=false
for arg in "$@"; do
  case "$arg" in
    --check|--check-only) CHECK_ONLY=true ;;
    --run-hooks)          RUN_HOOKS=true ;;
    -h|--help)
      sed -n '2,31p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "unknown argument: $arg" "Run: scripts/dev-setup.sh --help" ;;
  esac
done

cd "$REPO_ROOT"

# --- preconditions ----------------------------------------------------------
head_ "Preconditions"

git rev-parse --git-dir >/dev/null 2>&1 || die \
  "$REPO_ROOT is not a git working tree" \
  "There is nowhere to install a hook. Clone the repository rather than copying the files."
grep -q '^name = "ml-platform"$' pyproject.toml 2>/dev/null || die \
  "$REPO_ROOT is not the ml-platform checkout" \
  "Run this from the repository, not from a copy of the script."
ok "ml-platform working tree at $REPO_ROOT"

[[ -f .pre-commit-config.yaml ]] || die \
  "no .pre-commit-config.yaml at $REPO_ROOT" \
  "There is no hook configuration to install. Restore the file."

command -v uv >/dev/null 2>&1 || die \
  "uv is not installed" \
  "This script runs everything through uv, so there is nothing to run yet." \
  "Run: scripts/bootstrap.sh"

# --no-sync: this script must report an unsynced workspace, not quietly fix
# one. Syncing is bootstrap.sh's job, and a script that silently does another
# script's work hides which one the contributor actually needs to run.
uv run --no-sync pre-commit --version >/dev/null 2>&1 || die \
  "pre-commit is not in the workspace environment" \
  "It is declared in pyproject.toml's dev dependency group, so this means the" \
  "workspace is not synced." \
  "Run: scripts/bootstrap.sh"
ok "$(uv run --no-sync pre-commit --version) available through uv"

# --- config -----------------------------------------------------------------
head_ "Configuration"
uv run --no-sync pre-commit validate-config >/dev/null || die \
  ".pre-commit-config.yaml is not valid" \
  "The output above names the problem. Fix it before installing hooks — an" \
  "invalid config installs a hook that fails on every commit."
ok ".pre-commit-config.yaml is valid"

HOOKS_DIR="$(git rev-parse --git-path hooks)"

# --- install ----------------------------------------------------------------
if [[ "$CHECK_ONLY" == "true" ]]; then
  head_ "Installation (skipped — --check)"
  note "no hook was written"
else
  head_ "Installation"
  # --install-hooks builds every hook's isolated environment now (node for
  # markdownlint, go for gitleaks, python for the rest). It needs the network
  # and can take minutes on a cold cache. Doing it here rather than lazily is
  # the point: a five-minute pause on someone's first `git commit` is where
  # --no-verify habits come from.
  note "building hook environments — several minutes on a cold cache, seconds afterwards"
  uv run --no-sync pre-commit install --install-hooks --overwrite || die \
    "pre-commit install failed" \
    "Most often this is the network: the hook environments are cloned from" \
    "the repositories pinned in .pre-commit-config.yaml." \
    "Nothing partial is left behind — re-run this script when connectivity is back."
  # The second stage. See the header: without this the commit-msg hook is
  # configured and unarmed.
  uv run --no-sync pre-commit install --hook-type commit-msg --overwrite >/dev/null || die \
    "pre-commit install --hook-type commit-msg failed" \
    "Re-run this script; see the output above for the cause."
  ok "hooks installed and their environments built"
fi

# --- verify -----------------------------------------------------------------
# Verified by reading what is on disk, not by trusting that the install command
# exited zero. The failure being guarded against is a hook file that exists but
# belongs to something else — another framework, or a leftover from a previous
# workflow — which silently replaces the gate with a different one.
head_ "Verification"
WIRED=true
for hook in pre-commit commit-msg; do
  if [[ ! -f "$HOOKS_DIR/$hook" ]]; then
    warn "$HOOKS_DIR/$hook is missing"
    WIRED=false
  elif ! grep -q 'pre-commit' "$HOOKS_DIR/$hook"; then
    warn "$HOOKS_DIR/$hook exists but does not reference the pre-commit framework"
    WIRED=false
  else
    ok "$HOOKS_DIR/$hook wired to pre-commit"
  fi
done

if [[ "$WIRED" != "true" ]]; then
  if [[ "$CHECK_ONLY" == "true" ]]; then
    die "the git hooks are not installed" \
      "Run: scripts/dev-setup.sh"
  fi
  die "the git hooks did not land after a successful install" \
    "Check core.hooksPath — if it points elsewhere, pre-commit wrote to a" \
    "directory git does not consult:" \
    "  git config --get core.hooksPath"
fi

# A hook that is installed and cannot execute is still a broken setup, so the
# wiring is proved by running one cheap hook rather than assumed from the file
# contents. trailing-whitespace over a single file costs a moment and fails if
# the environment is not really there.
if [[ "$CHECK_ONLY" != "true" ]]; then
  uv run --no-sync pre-commit run trailing-whitespace --files pyproject.toml >/dev/null || die \
    "the hook framework is installed but cannot execute a hook" \
    "Re-run with a clean cache: rm -rf ~/.cache/pre-commit && scripts/dev-setup.sh"
  ok "the framework executes a hook against a real file"
fi

# --- optional full sweep ----------------------------------------------------
if [[ "$RUN_HOOKS" == "true" ]]; then
  head_ "Full sweep — every hook, every file"
  # Not the default, and this is why: trailing-whitespace, end-of-file-fixer,
  # ruff --fix, ruff-format and uv-lock all REWRITE what they inspect, and
  # --all-files points them at the whole repository rather than at what you
  # touched. Run here once, it silently stripped the two trailing spaces that
  # are a markdown hard line break from an ADR nobody was editing.
  warn "some hooks rewrite files, and --all-files aims them at the whole repository"
  note "Anything changed is listed at the end of this section. Commit or discard it deliberately."
  TREE_BEFORE="$(git status --porcelain)"
  SWEEP_STATUS=0
  # SKIP=no-commit-to-branch: that hook fails BY DESIGN whenever HEAD is main,
  # which is where a fresh clone sits. Including it would make a correct setup
  # report failure, and a setup script that cries wolf is one people stop
  # reading. It still protects real commits; it is only meaningless here.
  SKIP=no-commit-to-branch uv run --no-sync pre-commit run --all-files || SWEEP_STATUS=$?
  TREE_AFTER="$(git status --porcelain)"

  if [[ "$TREE_BEFORE" == "$TREE_AFTER" ]]; then
    ok "the sweep left the working tree unchanged"
  else
    warn "the sweep rewrote the working tree:"
    while IFS= read -r line; do
      [[ -n "$line" ]] && note "$line"
    done < <(comm -13 <(printf '%s\n' "$TREE_BEFORE" | sort) <(printf '%s\n' "$TREE_AFTER" | sort))
    note "review with: git diff"
  fi

  if (( SWEEP_STATUS == 0 )); then
    ok "every hook is green on the current tree"
  else
    warn "some hooks reported findings"
    note "The setup is correct — these are the state of the tree, not a setup failure."
    note "Fix them before your next commit, or the commit will be blocked."
    exit 2
  fi
fi

# --- summary ----------------------------------------------------------------
head_ "Summary"
if [[ "$CHECK_ONLY" == "true" ]]; then
  ok "hooks are installed and wired — nothing was changed"
  exit 0
fi

cat <<'EOF'

  What now happens:
    git commit    ruff (lint + format), mypy on libs/, gitleaks, markdownlint,
                  and the repository invariants — dependency direction, agentic
                  surface parity, doc coherence, derived status.
    the message   must be a conventional commit.

  Useful:
    scripts/dev-setup.sh --run-hooks              every hook over the whole tree
    SKIP=no-commit-to-branch uv run pre-commit run --all-files    the same, by hand
    make verify                                   the full gate suite, as CI runs it

  `git commit --no-verify` skips all of it. CI does not.

EOF
