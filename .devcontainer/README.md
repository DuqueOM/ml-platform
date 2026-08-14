# Devcontainer

`devcontainer.json` is strict JSON with no comments, because pre-commit's
`check-json` hook covers it and JSONC would fail that hook. The reasoning that
would otherwise be comments lives here.

## What it is for

A contributor with Docker and nothing else gets an environment that can run
`make verify` and `make local-up`. It provisions itself by calling
`scripts/bootstrap.sh` and `scripts/dev-setup.sh` — the same scripts used on a
bare machine. Provisioning the container its own way would make "works in the
devcontainer" and "works on my machine" two claims with nothing in common.

## The choices

**`python:1-3.11-bookworm`, not a bare base image.** `.python-version` pins
3.11 and `uv` would download a matching interpreter anyway, but shipping one in
the image means a container that still builds when that download is blocked.

**`docker-in-docker`, not `docker-outside-of-docker`.** `make local-up` creates
a kind cluster that binds seven host ports. With the host's socket mounted, the
cluster and its ports land on the host rather than in the container, so two
open containers collide and neither one owns the stack it created. Docker in
Docker keeps the cluster inside the container it belongs to.

**`terraform` pinned to 1.15.5.** The same version
`.github/workflows/ci.yml` installs. `terraform validate` is version-sensitive,
and a local pass at a different version says nothing about the CI result.

**`helm: none`, `minikube: none`, `tflint: none`, `terragrunt: none`.** The
features that bundle them are used for `kubectl` and `terraform` only. Nothing
in this repository calls the rest.

**kind is installed by `post-create.sh`, not by a feature.** The
devcontainers organisation publishes no kind feature, and the third-party ones
trade a pinned, checksum-verified download for an unpinned dependency. The
script downloads a pinned version and refuses to install it unless the
checksum published by that release matches.

**`hostRequirements.memory: 8gb`.** `platform/local/budget.yaml` declares
2,824 MB across the stack's components and allows it 55% of measured available
memory, so the stack needs about 5,135 MB available before
`scripts/local/preflight.py` will let it start. Inside a container that is the
container's memory, not the host's — raise Docker's limit rather than the
budget.

**`UV_LINK_MODE=copy`.** The uv cache is a named volume and the workspace is a
bind mount. They are different filesystems, so uv cannot hardlink between them
and warns on every sync until told to copy.

## Editor settings

Deliberately three: the interpreter path, pytest as the test runner, and ruff
as the Python formatter. Each states a fact about this repository rather than a
preference — the third exists because installing the Python extension pack
without it invites `black`, which ruff replaced here.

Note what is absent: `ms-python.black-formatter` and `ms-python.isort`. Both
are in the upstream template's list, and both would fight `ruff format`.

Personal editor configuration belongs in your own settings, not here; the
repository already enforces what matters through ruff, mypy and pre-commit,
which run regardless of editor.
