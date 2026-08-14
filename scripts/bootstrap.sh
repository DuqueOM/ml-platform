#!/usr/bin/env bash
# First-run setup for ml-platform on a machine that has nothing.
#
# The contract is narrow on purpose. This script owns exactly one thing: the
# Python environment every gate runs inside — `uv`, the interpreter pinned by
# .python-version, and the synced workspace. Everything else it INSPECTS and
# reports, because everything else needs sudo, a daemon, or a package manager
# whose behaviour on an unknown distribution is a guess.
#
# Why that split, specifically: a bootstrap that half-installs a container
# runtime leaves a machine worse than untouched — a broken daemon is harder to
# diagnose than an absent one, and the person who has to diagnose it did not
# choose to. So the rule here is: install only what is user-scoped (under
# $HOME, no sudo) and verifiable afterwards by running it. For the rest, print
# the exact command and let the human decide.
#
#   scripts/bootstrap.sh            set up: install uv if absent, sync the workspace
#   scripts/bootstrap.sh --check    report only; changes nothing; non-zero if a requirement is missing
#   scripts/bootstrap.sh --yes      non-interactive; assume yes to the one install prompt
#   scripts/bootstrap.sh --help
#
# Idempotent. The second run installs nothing and prints the same inventory.

set -euo pipefail

# uv installs to $HOME/.local/bin, which is not on PATH in a non-login shell.
# Without this, a run that installs uv cannot then call it.
export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Pinned rather than `latest`: a bootstrap whose output depends on the day it
# ran is not a reproducible environment. Bump this deliberately.
UV_VERSION="0.11.19"

# --- output -----------------------------------------------------------------
# Colour only on a terminal. Piped into a log file or a CI step, escape codes
# make the one line that matters harder to find, not easier.
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

# An unexpected non-zero must name where it happened. `set -e` alone exits
# silently, which is the "died halfway with no message" failure this script is
# supposed to be the opposite of.
on_err() {
  local code=$?
  printf '\n%sFAIL%s  bootstrap aborted at %s line %s (exit %s). Nothing further was attempted.\n' \
    "$C_ERR" "$C_OFF" "${BASH_SOURCE[1]}" "${BASH_LINENO[0]}" "$code" >&2
}
trap on_err ERR

# --- arguments --------------------------------------------------------------
CHECK_ONLY=false
ASSUME_YES=false
for arg in "$@"; do
  case "$arg" in
    --check|--check-only) CHECK_ONLY=true ;;
    --yes|-y)             ASSUME_YES=true ;;
    -h|--help)
      sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "unknown argument: $arg" "Run: scripts/bootstrap.sh --help" ;;
  esac
done

# --- identity ---------------------------------------------------------------
# This script syncs $REPO_ROOT/.venv. Copied into another tree it would sync
# the wrong workspace and report success for it, so it refuses to run anywhere
# that is not this repository.
head_ "Repository"
[[ -f "$REPO_ROOT/pyproject.toml" ]] || die "no pyproject.toml at $REPO_ROOT" \
  "This script must stay in scripts/ inside the ml-platform checkout."
grep -q '^name = "ml-platform"$' "$REPO_ROOT/pyproject.toml" || die \
  "$REPO_ROOT/pyproject.toml is not ml-platform's" \
  "Run this from the ml-platform checkout, not from a copy of the script."
[[ -f "$REPO_ROOT/.python-version" ]] || die "no .python-version at $REPO_ROOT" \
  "The interpreter pin is what makes local and CI agree. Restore the file."
PY_PINNED="$(tr -d '[:space:]' < "$REPO_ROOT/.python-version")"
ok "ml-platform at $REPO_ROOT"
ok "interpreter pinned to $PY_PINNED by .python-version"

# --- package manager (for advice only) --------------------------------------
# Detected so the "install it with this" lines are correct rather than
# plausible. Nothing here installs anything; when the manager is unknown the
# advice falls back to the project's own instructions.
detect_pm() {
  local pm
  for pm in brew apt-get dnf yum pacman apk; do
    if command -v "$pm" >/dev/null 2>&1; then printf '%s' "$pm"; return; fi
  done
  printf 'unknown'
}
PKG_MANAGER="$(detect_pm)"

pm_install() {
  case "$PKG_MANAGER" in
    brew)    printf 'brew install %s' "$1" ;;
    apt-get) printf 'sudo apt-get update && sudo apt-get install -y %s' "$1" ;;
    dnf)     printf 'sudo dnf install -y %s' "$1" ;;
    yum)     printf 'sudo yum install -y %s' "$1" ;;
    pacman)  printf 'sudo pacman -S --needed %s' "$1" ;;
    apk)     printf 'sudo apk add %s' "$1" ;;
    *)       printf '' ;;
  esac
}

# How to get each tool. Where a distribution package exists the detected
# manager is used; where it does not (kubectl, kind, trivy on most distros)
# the upstream instruction is printed instead of a package name that will not
# resolve.
install_hint() {
  local tool="$1" pm
  case "$tool" in
    git)
      pm="$(pm_install git)"
      printf '%s' "${pm:-see https://git-scm.com/downloads}"
      ;;
    make)
      pm="$(pm_install make)"
      printf '%s' "${pm:-install the build tools for your platform; on macOS: xcode-select --install}"
      ;;
    curl)
      pm="$(pm_install curl)"
      printf '%s' "${pm:-see https://curl.se/download.html}"
      ;;
    shellcheck)
      pm="$(pm_install shellcheck)"
      printf '%s' "${pm:-uvx --from shellcheck-py shellcheck --version}"
      ;;
    node)
      if [[ "$PKG_MANAGER" == "brew" ]]; then printf 'brew install node'
      elif [[ "$PKG_MANAGER" == "apt-get" ]]; then printf 'sudo apt-get install -y nodejs npm'
      else printf 'see https://nodejs.org/en/download'; fi
      ;;
    docker)
      printf 'see https://docs.docker.com/engine/install/ — installing a container daemon is not something this script will guess at'
      ;;
    kubectl)
      if [[ "$PKG_MANAGER" == "brew" ]]; then printf 'brew install kubectl'
      else printf 'see https://kubernetes.io/docs/tasks/tools/#kubectl'; fi
      ;;
    kind)
      if [[ "$PKG_MANAGER" == "brew" ]]; then printf 'brew install kind'
      else printf 'see https://kind.sigs.k8s.io/docs/user/quick-start/#installation — or .devcontainer/post-create.sh, which pins a version and verifies its checksum'; fi
      ;;
    terraform)
      if [[ "$PKG_MANAGER" == "brew" ]]; then printf 'brew install hashicorp/tap/terraform'
      else printf 'see https://developer.hashicorp.com/terraform/install — CI pins 1.15.5'; fi
      ;;
    gitleaks)
      if [[ "$PKG_MANAGER" == "brew" ]]; then printf 'brew install gitleaks'
      else printf 'see https://github.com/gitleaks/gitleaks/releases'; fi
      ;;
    trivy)
      if [[ "$PKG_MANAGER" == "brew" ]]; then printf 'brew install trivy'
      else printf 'see https://trivy.dev/latest/getting-started/installation/'; fi
      ;;
    checkov)
      printf 'uv tool install checkov'
      ;;
    gh)
      if [[ "$PKG_MANAGER" == "brew" ]]; then printf 'brew install gh'
      else printf 'see https://github.com/cli/cli#installation'; fi
      ;;
    *) printf 'no instruction recorded for %s' "$tool" ;;
  esac
}

# --version is not universal, and a wrong flag prints a usage page that reads
# like a version. Each tool gets the invocation that actually reports one.
#
# Captured whole and trimmed here rather than piped through `head -1`: under
# `pipefail`, head closing the pipe hands the tool a SIGPIPE, the pipeline
# reports failure, and the caller's fallback prints "version unavailable"
# directly underneath the version it just read successfully. terraform, whose
# output is four lines, did exactly that.
tool_version() {
  local raw
  case "$1" in
    gitleaks)  raw="$(gitleaks version 2>&1)" ;;
    kubectl)   raw="$(kubectl version --client 2>&1)" ;;
    terraform) raw="$(terraform version 2>&1)" ;;
    docker)    raw="$(docker --version 2>&1)" ;;
    *)         raw="$("$1" --version 2>&1)" ;;
  esac
  raw="${raw%%$'\n'*}"
  # curl reports every protocol and library it was built against. The
  # inventory is read by a human deciding what to install, not archived.
  if (( ${#raw} > 64 )); then raw="${raw:0:61}..."; fi
  printf '%s' "$raw"
}

MISSING_REQUIRED=()
MISSING_OPTIONAL=()

# tier: required = nothing works without it. optional = a named capability is
# lost, and the report says which one. Nothing is silently degraded.
report_tool() {
  local tool="$1" tier="$2" unlocks="$3"
  if command -v "$tool" >/dev/null 2>&1; then
    # `|| printf` guard: a tool that is installed but answers its version
    # query with a non-zero status must still be reported as present, not
    # abort the inventory it is one line of.
    ok "$(printf '%-10s %s' "$tool" "$(tool_version "$tool" 2>/dev/null || printf 'version unavailable')")"
  elif [[ "$tier" == "required" ]]; then
    warn "$(printf '%-10s MISSING — %s' "$tool" "$unlocks")"
    note "install: $(install_hint "$tool")"
    MISSING_REQUIRED+=("$tool")
  else
    warn "$(printf '%-10s absent  — without it: %s' "$tool" "$unlocks")"
    note "install: $(install_hint "$tool")"
    MISSING_OPTIONAL+=("$tool")
  fi
}

head_ "Required"
report_tool git      required "git history is an input to the derived documents and to the coherence gate"
report_tool make     required "make help / make verify are the entry points; CI runs the same commands"
# curl earns "required" only when uv is absent, which is the one thing it is
# needed for. Marking it required unconditionally would fail a machine that
# already has uv and is missing nothing that matters.
if command -v uv >/dev/null 2>&1; then
  report_tool curl   optional "the uv installer cannot be fetched — uv is already present, so nothing here needs it"
else
  report_tool curl   required "fetching the uv installer, which is the next step"
fi

head_ "Local validation stack — make local-up, make local-serve, pytest -m local"
report_tool docker   optional "the local stack and the service image cannot be built or run"
# The binary being present says nothing about the daemon being up, and the two
# fail very differently: an absent docker is obvious, an unreachable daemon
# reports a connection error from inside `kind create cluster`, several minutes
# in. This repository has already lost most of a session to it.
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    ok "$(printf '%-10s daemon reachable' 'docker')"
  else
    warn "$(printf '%-10s daemon NOT reachable — the binary is installed, nothing is listening' 'docker')"
    note "start Docker Desktop, or: sudo systemctl start docker"
    MISSING_OPTIONAL+=("docker-daemon")
  fi
fi
report_tool kind     optional "there is no local Kubernetes cluster to apply manifests to"
report_tool kubectl  optional "the local stack cannot be applied or queried"

head_ "Gate parity with CI"
report_tool terraform optional "tests/test_cloud_surface.py SKIPS ENTIRELY — terraform validate never runs, and a skipped test reports success for doing nothing"
report_tool node      optional "no 'npx markdownlint-cli2', the linter .github/workflows/docs-quality.yml runs"
report_tool gitleaks  optional "no ad-hoc secret scan outside the commit path — pre-commit still builds its own copy for the hook"
report_tool shellcheck optional "the shell in scripts/ and .devcontainer/ is unlinted"
report_tool trivy     optional "no local filesystem vulnerability or secret scan"
report_tool checkov   optional "no local IaC scan over platform/ (advisory in CI)"
report_tool gh        optional "scripts/setup_branch_protection.sh cannot talk to GitHub"

if (( ${#MISSING_REQUIRED[@]} > 0 )); then
  die "missing required tools: ${MISSING_REQUIRED[*]}" \
    "Install them with the commands printed above, then run this script again." \
    "Nothing has been changed on this machine."
fi

# --- uv ---------------------------------------------------------------------
head_ "Package manager (uv)"
if command -v uv >/dev/null 2>&1; then
  ok "uv $(uv --version 2>&1 | awk '{print $2}') at $(command -v uv)"
elif [[ "$CHECK_ONLY" == "true" ]]; then
  warn "uv is not installed"
  note "install: curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | sh"
  die "uv is required and --check does not install" \
    "Run scripts/bootstrap.sh (without --check) to install it under \$HOME/.local/bin."
else
  warn "uv is not installed"
  note "It installs to \$HOME/.local/bin. No sudo, nothing outside your home directory."
  if [[ "$ASSUME_YES" != "true" ]]; then
    if [[ -t 0 ]]; then
      read -rp "  Install uv ${UV_VERSION} now? [y/N] " reply
      [[ "$reply" =~ ^[Yy]$ ]] || die "declined" \
        "Install it yourself with:" \
        "  curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | sh" \
        "then run this script again."
    else
      die "uv is missing and there is no terminal to ask on" \
        "Re-run with --yes to install it non-interactively, or install it yourself:" \
        "  curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | sh"
    fi
  fi
  # INSTALLER_NO_MODIFY_PATH: the installer edits shell profiles by default.
  # Rewriting someone's .bashrc as a side effect of a setup script is a change
  # they did not ask for and will not find later, so the export line is
  # PRINTED below instead and they decide where it goes.
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | env INSTALLER_NO_MODIFY_PATH=1 sh
  hash -r
  command -v uv >/dev/null 2>&1 || die "uv installed but is not on PATH" \
    "Expected \$HOME/.local/bin/uv. Add this to your shell profile and re-run:" \
    "  export PATH=\"\$HOME/.local/bin:\$PATH\""
  ok "uv $(uv --version 2>&1 | awk '{print $2}') installed at $(command -v uv)"
  note "Add this to your shell profile so future shells find it:"
  note "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# --- interpreter ------------------------------------------------------------
head_ "Interpreter"
if uv python find "$PY_PINNED" >/dev/null 2>&1; then
  ok "a Python $PY_PINNED is available to uv"
elif [[ "$CHECK_ONLY" == "true" ]]; then
  warn "no Python $PY_PINNED visible to uv"
  note "fix: uv python install $PY_PINNED"
else
  warn "no Python $PY_PINNED visible to uv — installing a uv-managed one"
  # uv-managed interpreters live under $HOME; this does not touch the system
  # Python, which is what makes it safe to do without asking.
  uv python install "$PY_PINNED"
  ok "Python $PY_PINNED installed (uv-managed, under \$HOME)"
fi

# --- workspace --------------------------------------------------------------
head_ "Workspace"
if [[ "$CHECK_ONLY" == "true" ]]; then
  if [[ -d "$REPO_ROOT/.venv" ]] && (cd "$REPO_ROOT" && uv run --no-sync python -c 'import yaml' >/dev/null 2>&1); then
    ok ".venv exists and imports the root dependencies"
  else
    warn ".venv is absent or incomplete"
    note "fix: uv sync --all-packages --all-extras"
    die "workspace is not synced and --check does not sync" \
      "Run scripts/bootstrap.sh (without --check)."
  fi
else
  # --all-packages, not --all-extras alone: without it uv installs the ROOT
  # project's dependencies only and every workspace member's are missing, so
  # mypy reports "cannot find <lib>" for code that runs. This is the exact
  # command .github/workflows/ci.yml runs, and the two must not diverge.
  note "uv sync --all-packages --all-extras (first run pulls Airflow and its 81 packages)"
  (cd "$REPO_ROOT" && uv sync --all-packages --all-extras) || die \
    "uv sync failed" \
    "The output above names the package. Common causes: no network, or a" \
    "lockfile that disagrees with pyproject.toml (uv lock --check will say so)."
  ok "workspace synced"
fi

# --- proof ------------------------------------------------------------------
# The pin is verified by asking the environment, not by trusting the file that
# declares it. CI has already been bitten once by resolving 3.12 where local
# resolved 3.11: everything stayed green locally and meant nothing.
head_ "Verification"
PY_ACTUAL="$(cd "$REPO_ROOT" && uv run --no-sync python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$PY_PINNED" == "$PY_ACTUAL" || "$PY_PINNED" == "$PY_ACTUAL".* ]]; then
  ok "environment runs Python $PY_ACTUAL, matching the $PY_PINNED pin"
else
  die "environment runs Python $PY_ACTUAL but .python-version pins $PY_PINNED" \
    "Local green would mean nothing about CI. Remove .venv and re-run:" \
    "  rm -rf .venv && scripts/bootstrap.sh"
fi
if (cd "$REPO_ROOT" && uv run --no-sync ruff --version >/dev/null 2>&1); then
  ok "the dev toolchain resolves (ruff runs inside the environment)"
else
  die "ruff is not installed in the environment" \
    "The dev dependency group did not install. Re-run: uv sync --all-packages --all-extras"
fi

# --- summary ----------------------------------------------------------------
head_ "Summary"
if (( ${#MISSING_OPTIONAL[@]} > 0 )); then
  warn "absent, each with the capability it costs, listed above: ${MISSING_OPTIONAL[*]}"
  note "None of these block 'make verify'. Install them when you need what they unlock."
else
  ok "every tool this repository uses is present"
fi

if [[ "$CHECK_ONLY" == "true" ]]; then
  ok "check complete — nothing on this machine was changed"
  exit 0
fi

cat <<'EOF'

  Next:
    scripts/dev-setup.sh    install the git hooks (do this before your first commit)
    make help               every entry point
    make verify             the full gate suite, exactly what CI runs
    make local-up           the local stack — needs docker, kind and kubectl

EOF
