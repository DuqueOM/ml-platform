#!/usr/bin/env bash
# Devcontainer provisioning, run once by postCreateCommand.
#
# This file is the other half of devcontainer.json: features supply the tools
# that have features, this supplies the two that do not, and then it hands off
# to the SAME scripts a contributor on a bare machine runs. That hand-off is
# deliberate — if the container provisioned itself its own way, "works in the
# devcontainer" and "works on my machine" would be two claims with nothing in
# common, and only one of them would be tested.
#
# Idempotent: rebuilding the container, or running this by hand afterwards,
# installs nothing twice.

set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Pinned, with the checksum published by the release. `latest` in a container
# image means two people who built the same devcontainer.json a month apart get
# different clusters, and the difference surfaces as a manifest that applies
# for one of them.
KIND_VERSION="v0.30.0"
KIND_SHA256_amd64="517ab7fc89ddeed5fa65abf71530d90648d9638ef0c4cde22c2c11f8097b8889"
KIND_SHA256_arm64="7ea2de9d2d190022ed4a8a4e3ac0636c8a455e460b9a13ccf19f15d07f4f00eb"

step() { printf '\n\033[1;34m== %s\033[0m\n' "$1"; }
ok()   { printf '  ok    %s\n' "$1"; }
die()  { printf '\n\033[0;31mFAIL\033[0m  %s\n' "$1" >&2; exit 1; }

on_err() {
  local code=$?
  printf '\n\033[0;31mFAIL\033[0m  post-create aborted at line %s (exit %s). Rebuild the container, or run this file by hand to see where it stops.\n' \
    "${BASH_LINENO[0]}" "$code" >&2
}
trap on_err ERR

# The base image is Debian bookworm with passwordless sudo for the vscode user.
# Both are assumptions, and an assumption that is wrong should say so rather
# than produce a confusing apt error two lines later.
command -v apt-get >/dev/null 2>&1 || die "no apt-get: this script assumes the Debian-based devcontainer base image"
sudo -n true 2>/dev/null || die "no passwordless sudo: this script assumes the standard devcontainer 'vscode' user"

# --- cache volumes ----------------------------------------------------------
# Named volumes are created root-owned. Left that way, uv's first write fails
# with EACCES on a path nobody put in the config by hand — chowning here is
# cheaper than the bug report.
step "Cache volumes"
for dir in "$HOME/.cache/uv" "$HOME/.cache/pre-commit"; do
  mkdir -p "$dir"
  if [[ ! -w "$dir" ]]; then
    sudo chown -R "$(id -u):$(id -g)" "$dir"
  fi
  ok "$dir writable"
done

# --- shellcheck -------------------------------------------------------------
# scripts/bootstrap.sh will not install this: on an unknown machine it needs
# sudo it cannot assume. Here both the package manager and sudo are known, so
# installing it is a verified action rather than a guess.
step "shellcheck"
if command -v shellcheck >/dev/null 2>&1; then
  ok "already present: $(shellcheck --version | awk '/^version:/ {print $2}')"
else
  sudo apt-get update -qq
  sudo apt-get install -y -qq --no-install-recommends shellcheck
  command -v shellcheck >/dev/null 2>&1 || die "apt reported success but shellcheck is not on PATH"
  ok "installed: $(shellcheck --version | awk '/^version:/ {print $2}')"
fi

# --- kind -------------------------------------------------------------------
# No devcontainers-org feature publishes kind, and the third-party ones are an
# unpinned supply chain in exchange for four lines. Downloaded and checksum-
# verified instead — the binary is not moved into place until it matches.
step "kind"
if command -v kind >/dev/null 2>&1 && [[ "$(kind --version | awk '{print $3}')" == "${KIND_VERSION#v}" ]]; then
  ok "already at ${KIND_VERSION}"
else
  case "$(dpkg --print-architecture)" in
    amd64) KIND_ARCH=amd64; KIND_SHA256="$KIND_SHA256_amd64" ;;
    arm64) KIND_ARCH=arm64; KIND_SHA256="$KIND_SHA256_arm64" ;;
    *) die "no pinned kind checksum for architecture $(dpkg --print-architecture) — add one rather than downloading unverified" ;;
  esac
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL -o "$tmp/kind" \
    "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-${KIND_ARCH}"
  echo "${KIND_SHA256}  $tmp/kind" | sha256sum --check --status \
    || die "kind ${KIND_VERSION} checksum mismatch — the download was not what the release publishes. Nothing was installed."
  chmod +x "$tmp/kind"
  sudo install -m 0755 "$tmp/kind" /usr/local/bin/kind
  ok "installed ${KIND_VERSION}, checksum verified"
fi

# --- the shared path --------------------------------------------------------
# From here the container is set up by exactly what a contributor runs on a
# bare machine. --yes because there is no terminal to prompt on.
step "Handing off to scripts/bootstrap.sh"
bash scripts/bootstrap.sh --yes

step "Handing off to scripts/dev-setup.sh"
bash scripts/dev-setup.sh

# --- proof ------------------------------------------------------------------
# A devcontainer that builds and then cannot run a gate has failed at the only
# thing it is for. One real gate is run here so a broken image fails at create
# time, in the build log, rather than at the contributor's first command.
step "Verification"
uv run --no-sync ruff check --quiet scripts/ \
  || die "the environment is built but 'ruff check scripts/' does not pass — the container is not usable as-is"
ok "a real gate runs inside the container"

cat <<'EOF'

  Ready.

    make help        every entry point
    make verify      the full gate suite, exactly what CI runs
    make local-up    the local stack (docker-in-docker, kind, kubectl are all here)

  make local-up refuses to start unless MEASURED available memory fits the
  budget in platform/local/budget.yaml. Inside a container that is the
  container's memory, so raise Docker's limit rather than the budget.

EOF
