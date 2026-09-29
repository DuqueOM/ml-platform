"""The GitOps matrix must build, and must not quietly lose a member.

`kubectl kustomize` renders without a cluster and provisions nothing, so this
runs while the cloud work is deliberately paused (constraint S3).

One thing these tests deliberately do NOT claim: that the NetworkPolicies
work. Rendering proves intent — selectors, peers, ports — and nothing about a
packet being dropped. This paragraph used to add that kind cannot provide that
evidence because kindnet enforces nothing; QA-4 round eleven showed kindnetd
enforcing a default-deny on a live kind cluster. Local enforcement evidence is
obtainable and not yet collected — see
`docs/governance/remediation-work-order.md`, round eleven.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAYS = REPO_ROOT / "platform" / "kubernetes" / "overlays"
APPLICATIONSET = REPO_ROOT / "platform" / "gitops" / "applicationset.yaml"

CLOUDS = ("gcp", "aws")
ENVIRONMENTS = ("dev", "staging", "prod")

#: Overlays that are deliberately NOT cells of the cloud x environment matrix.
#: `local` targets a kind cluster: no cloud, no External Secrets, no Kyverno,
#: and no ArgoCD Application generated for it. Listed by name rather than
#: filtered by a pattern, so a sixth cloud overlay named `local-something`
#: cannot slip past the completeness check by looking like an exemption.
NON_MATRIX_OVERLAYS = frozenset({"local"})

pytestmark = pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")


def _build(overlay: Path) -> list[dict]:  # type: ignore[type-arg]
    result = subprocess.run(["kubectl", "kustomize", str(overlay)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"{overlay.name} does not build:\n{result.stderr}"
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def test_the_matrix_is_complete() -> None:
    """Six overlays: two clouds by three environments.

    Asserted against the product, not against a count. A count passes when
    someone adds `gcp-qa` and deletes `aws-prod`, which is the change most
    likely to go unnoticed and most expensive to discover.
    """
    expected = {f"{cloud}-{env}" for cloud in CLOUDS for env in ENVIRONMENTS}
    found = {path.name for path in OVERLAYS.iterdir() if path.is_dir()} - NON_MATRIX_OVERLAYS
    assert found == expected, f"matrix is incomplete: missing {expected - found}, extra {found - expected}"


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_overlay_builds(cloud: str, env: str) -> None:
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    kinds = {doc["kind"] for doc in documents}
    assert {"Deployment", "Service", "PodDisruptionBudget", "NetworkPolicy"} <= kinds


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_overlay_carries_default_deny(cloud: str, env: str) -> None:
    """An allow-list without a deny changes nothing: the traffic already flowed."""
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    policies = {doc["metadata"]["name"] for doc in documents if doc["kind"] == "NetworkPolicy"}
    assert "default-deny" in policies
    assert "allow-dns" in policies, "a default-deny namespace with no DNS egress breaks every lookup"


# --- Pod Security is enforced where the workload runs, not only on a laptop -

#: All three, not just `enforce`. Enforce rejects a violating pod and tells
#: nobody afterwards; `audit` records it and `warn` returns it to whoever ran
#: the apply, which is the difference between a diagnosable failure and a
#: rollout that stops with no explanation.
_PSS_LABELS = (
    "pod-security.kubernetes.io/enforce",
    "pod-security.kubernetes.io/audit",
    "pod-security.kubernetes.io/warn",
)


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_overlay_creates_its_namespace_at_restricted(cloud: str, env: str) -> None:
    """The namespace must arrive WITH the overlay, carrying the labels.

    Only `local` created a Namespace. The six cloud overlays set `namespace:`
    and shipped no Namespace object, so ArgoCD's `CreateNamespace=true` made
    one with no Pod Security labels at all — while the base Deployment's
    comment claimed restricted was "the namespace default" and set every field
    that level requires. The pod was hardened in six environments where
    nothing enforced that it stay so.

    Removing the three labels from an overlay used to change no test result,
    which is why this exists. The Namespace's NAME is deliberately not checked:
    kustomize rewrites it to match `namespace:`, so the assertion could not
    fail and would only look like coverage.
    """
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    namespaces = [doc for doc in documents if doc["kind"] == "Namespace"]

    assert len(namespaces) == 1, f"{cloud}-{env} renders {len(namespaces)} Namespaces; the labels ride on exactly one"

    labels = namespaces[0]["metadata"].get("labels") or {}
    assert {label: labels.get(label) for label in _PSS_LABELS} == dict.fromkeys(_PSS_LABELS, "restricted"), (
        f"{cloud}-{env} namespace does not enforce restricted Pod Security: {labels}"
    )


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_overlay_pod_satisfies_restricted(cloud: str, env: str) -> None:
    """The other half: a level nothing can satisfy is an outage, not a control.

    `enforce` is checked at admission, so a namespace raised above what its
    workload meets rejects every pod — and because dev, staging and prod all
    sit at `restricted` here, that failure would be uniform rather than caught
    one environment before production. This checks the rendered pod against
    the fields the level requires, which is also the evidence that enforcing
    it in dev costs nothing: it is already true there.
    """
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    templates = [doc["spec"]["template"]["spec"] for doc in documents if doc["kind"] == "Deployment"]
    assert templates, f"{cloud}-{env} renders no pod template — this test would pass vacuously"

    violations: list[str] = []
    for pod in templates:
        security = pod.get("securityContext") or {}
        if not security.get("runAsNonRoot"):
            violations.append("pod: runAsNonRoot not set")
        if (security.get("seccompProfile") or {}).get("type") != "RuntimeDefault":
            violations.append("pod: seccompProfile is not RuntimeDefault")
        violations += [f"pod: {field} is set" for field in ("hostNetwork", "hostPID", "hostIPC") if pod.get(field)]

        for container in pod["containers"]:
            context = container.get("securityContext") or {}
            name = container["name"]
            if context.get("allowPrivilegeEscalation") is not False:
                violations.append(f"{name}: allowPrivilegeEscalation is not false")
            if context.get("privileged"):
                violations.append(f"{name}: privileged")
            if "ALL" not in ((context.get("capabilities") or {}).get("drop") or []):
                violations.append(f"{name}: capabilities ALL not dropped")

    assert not violations, f"{cloud}-{env} would be rejected by its own namespace:\n" + "\n".join(violations)


@pytest.mark.parametrize("cloud", CLOUDS)
def test_production_runs_more_replicas_than_dev(cloud: str) -> None:
    """The overlays must actually differ; identical ones are six copies of one."""

    def replicas(env: str) -> int:
        documents = _build(OVERLAYS / f"{cloud}-{env}")
        return next(doc["spec"]["replicas"] for doc in documents if doc["kind"] == "Deployment")

    assert replicas("prod") > replicas("dev")


def test_the_applicationset_generates_the_same_matrix() -> None:
    """ArgoCD's generator and the overlay directories must not disagree.

    A generated Application whose path does not exist syncs to nothing and
    reports Healthy, which is the failure mode of a matrix that drifted.
    """
    spec = yaml.safe_load(APPLICATIONSET.read_text(encoding="utf-8"))
    matrix = spec["spec"]["generators"][0]["matrix"]["generators"]

    clouds = {element["cloud"] for element in matrix[0]["list"]["elements"]}
    environments = {element["env"] for element in matrix[1]["list"]["elements"]}

    assert clouds == set(CLOUDS)
    assert environments == set(ENVIRONMENTS)

    for cloud in clouds:
        for env in environments:
            assert (OVERLAYS / f"{cloud}-{env}").is_dir(), (
                f"the ApplicationSet generates {cloud}-{env}, which has no overlay to sync"
            )


def test_production_does_not_auto_sync() -> None:
    """Pull-based reconciliation applies whatever reaches main.

    With prod auto-syncing, the promotion gate stops being a gate: the model
    is deployed by the act of merging.
    """
    spec = yaml.safe_load(APPLICATIONSET.read_text(encoding="utf-8"))
    elements = spec["spec"]["generators"][0]["matrix"]["generators"][1]["list"]["elements"]
    autosync = {element["env"]: element["autosync"] for element in elements}

    assert autosync["prod"] == "false"
    assert autosync["dev"] == "true"


def test_nothing_prunes_automatically() -> None:
    """Prune deletes resources absent from git — including ones a human added
    during an incident, at the moment they are load-bearing."""
    spec = yaml.safe_load(APPLICATIONSET.read_text(encoding="utf-8"))
    assert spec["spec"]["template"]["spec"]["syncPolicy"]["automated"]["prune"] is False


@pytest.mark.local
def test_the_local_cluster_cannot_validate_networkpolicies() -> None:
    """Asserts the local CNI is kindnet — and nothing more, which is the open item.

    Its docstring claimed kindnet has no NetworkPolicy implementation, so a
    default-deny applied locally would enforce nothing. QA-4 round eleven
    disproved that on a live kind v0.30 cluster: kindnetd timed DNS out under
    the rendered policies. What this test should become is an enforcement
    probe — DNS allowed under the policies as written, denied when the peer
    selector is wrong — and that waits on a running cluster and on the
    namespace-label decision recorded in the remediation work order, round
    eleven. Until then it is kept, renamed in intent rather than in name so
    the history of the claim stays findable.
    """
    result = subprocess.run(
        ["kubectl", "get", "daemonset", "-n", "kube-system", "-o", "name"],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    if result.returncode != 0:
        pytest.skip("no cluster reachable")

    assert "kindnet" in result.stdout, (
        "the CNI is no longer kindnet; the enforcement probe planned as R11-2 must be re-validated against it"
    )


# --- secrets arrive from outside, and never from this repository ------------


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_overlay_pairs_an_external_secret_with_a_store(cloud: str, env: str) -> None:
    """An ExternalSecret without a SecretStore resolves to nothing.

    The pod then starts with an empty Secret rather than failing, and the
    symptom is an authentication error against the warehouse — which reads as
    a credential problem, which is exactly what it is not.
    """
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    kinds = {doc["kind"] for doc in documents}

    assert "ExternalSecret" in kinds
    assert "SecretStore" in kinds

    external = next(doc for doc in documents if doc["kind"] == "ExternalSecret")
    store = next(doc for doc in documents if doc["kind"] == "SecretStore")
    assert external["spec"]["secretStoreRef"]["name"] == store["metadata"]["name"], (
        "the ExternalSecret references a store that this overlay does not define"
    )


@pytest.mark.parametrize("cloud", CLOUDS)
def test_each_cloud_uses_its_own_provider(cloud: str) -> None:
    """The store is the adapter; using the wrong provider fails only at runtime."""
    documents = _build(OVERLAYS / f"{cloud}-dev")
    store = next(doc for doc in documents if doc["kind"] == "SecretStore")
    provider = set(store["spec"]["provider"])

    assert provider == {"gcpsm" if cloud == "gcp" else "aws"}


@pytest.mark.parametrize("cloud", CLOUDS)
def test_no_long_lived_credential_is_referenced(cloud: str) -> None:
    """Workload Identity and IRSA reach the same place: an identity, not a file.

    A `secretRef` here would mean a static key stored in a Secret to fetch
    other Secrets — a bootstrap credential that never rotates and that every
    incident runbook is written about.
    """
    documents = _build(OVERLAYS / f"{cloud}-dev")
    store = next(doc for doc in documents if doc["kind"] == "SecretStore")
    auth = next(iter(store["spec"]["provider"].values()))["auth"]

    assert "secretRef" not in auth, f"{cloud} authenticates with a stored key rather than an identity"
    assert {"workloadIdentity", "jwt"} & set(auth), f"{cloud} declares no identity-based auth: {auth}"


#: Keys whose VALUE is a credential. A username is not one, and treating it as
#: one would make this noisy enough to be switched off.
_SECRET_KEY = re.compile(r"PASSWORD|TOKEN|SECRET|API_?KEY|PRIVATE", re.IGNORECASE)

#: The marker a deliberately-public local credential must carry. The local
#: stack needs SOME Postgres password, so the rule cannot be "no Secret
#: exists" — a check that forbade it outright would be switched off the first
#: time it blocked someone.
_LOCAL_ONLY = "local-only-not-a-secret"


def test_no_real_credential_is_committed() -> None:
    """The property External Secrets exists to provide, checked against the repo.

    A manifest names a remote KEY and the cluster resolves the value, so a
    leaked manifest leaks a key name. The way that guarantee dies is someone
    adding a `stringData:` block "temporarily".

    The rule is that any committed credential must SAY it is not one, in its
    own value. A real password therefore fails here even inside
    `platform/local/` — which a path exclusion would have quietly allowed, and
    a path exclusion was the first thing I reached for.
    """
    manifests = [path for path in (REPO_ROOT / "platform").rglob("*.yaml") if ".terraform" not in path.parts]
    assert manifests, "no manifests found — this test would pass vacuously"

    offenders = []
    for path in manifests:
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if not isinstance(document, dict) or document.get("kind") != "Secret":
                continue
            values = {**document.get("data", {}), **document.get("stringData", {})}
            offenders += [
                f"{path.relative_to(REPO_ROOT).as_posix()}:{key}"
                for key, value in values.items()
                if _SECRET_KEY.search(key) and _LOCAL_ONLY not in str(value)
            ]

    assert not offenders, f"a credential is committed without the {_LOCAL_ONLY!r} marker: {offenders}"


def test_the_credential_check_can_actually_fail() -> None:
    """A guard never seen to reject anything is not a guard."""
    values = {"POSTGRES_PASSWORD": "hunter2", "MINIO_ROOT_USER": "mlplatform"}
    flagged = [key for key, value in values.items() if _SECRET_KEY.search(key) and _LOCAL_ONLY not in value]

    assert flagged == ["POSTGRES_PASSWORD"], "the pattern misses a real password or flags a username"


#: Tags that name a moving target. `latest` is the obvious one; the others are
#: the aliases people reach for when `latest` has been forbidden, which is how
#: a ban on one string becomes a ban on one string.
_MUTABLE_TAGS = frozenset({"latest", "main", "master", "stable", "edge", "dev", "prod", "staging"})


@pytest.mark.parametrize("overlay", sorted(p.name for p in OVERLAYS.iterdir() if p.is_dir()), ids=lambda n: n)
def test_no_overlay_ships_a_mutable_image_tag(overlay: str) -> None:
    """A mutable tag means the manifest does not say what runs.

    The base carried `:latest` and only the `local` overlay overrode it, so
    the six cloud overlays inherited it — in a repository whose supply-chain
    rows argue for digest pinning. Nothing caught it because rendering a
    manifest never asks what the tag resolves to.

    `local` is exempt and it is the one place a mutable tag is correct: the
    image is built and `kind load`ed by hand, never pulled, so a digest would
    be a hash of something that exists only on this machine.
    """
    if overlay == "local":
        return

    for document in _build(OVERLAYS / overlay):
        containers = document.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        for container in containers:
            reference = container.get("image", "")
            if "@sha256:" in reference:
                continue
            tag = reference.rsplit(":", 1)[-1] if ":" in reference else "latest"
            assert tag not in _MUTABLE_TAGS, (
                f"{overlay} deploys {reference!r}. A mutable tag means this manifest does not say what "
                f"runs; pin a digest, or leave the deploy-pipeline placeholder so an accidental apply "
                f"fails loudly instead of pulling whatever moved."
            )


# --- what an external audit found rendering green ---------------------------


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_the_pod_runs_as_a_named_service_account(cloud: str, env: str) -> None:
    """`default` has no cloud identity, and every overlay was binding one.

    Workload Identity (GCP) and IRSA (AWS) attach a cloud identity to a NAMED
    Kubernetes ServiceAccount. Without `serviceAccountName` the pod runs as the
    namespace's `default`, so the binding each overlay provisions reaches
    nothing — while the repository's own invariant reads "ALWAYS IRSA /
    Workload Identity, no hardcoded credentials".

    Nothing disagreed: the manifests rendered, the policy was declared, and the
    identity was simply never claimed.
    """
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    deployment = next(doc for doc in documents if doc["kind"] == "Deployment")
    name = deployment["spec"]["template"]["spec"].get("serviceAccountName")

    assert name, f"{cloud}-{env}: the pod names no ServiceAccount, so it runs as `default`"
    assert name != "default", f"{cloud}-{env}: `default` cannot carry a cloud identity binding"
    accounts = {doc["metadata"]["name"] for doc in documents if doc["kind"] == "ServiceAccount"}
    assert name in accounts, f"{cloud}-{env}: the pod names {name!r} and the overlay renders {sorted(accounts)}"


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_provisioned_secret_is_consumed(cloud: str, env: str) -> None:
    """An ExternalSecret nothing reads is the whole delivery path running for nothing.

    The operator resolved two remote keys into a Secret that no container
    mounted or referenced. Every step reported success — the pull, the Secret,
    the pod — because none of them is the step that would notice.
    """
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    provisioned = {
        doc["spec"]["target"]["name"]
        for doc in documents
        if doc["kind"] == "ExternalSecret" and doc["spec"].get("target")
    }
    if not provisioned:
        pytest.skip("this overlay provisions no ExternalSecret")

    consumed: set[str] = set()
    for doc in documents:
        if doc["kind"] != "Deployment":
            continue
        pod = doc["spec"]["template"]["spec"]
        for container in pod.get("containers", []):
            for entry in container.get("env", []):
                ref = entry.get("valueFrom", {}).get("secretKeyRef", {})
                if ref.get("name"):
                    consumed.add(ref["name"])
            for source in container.get("envFrom", []):
                if source.get("secretRef", {}).get("name"):
                    consumed.add(source["secretRef"]["name"])
        for volume in pod.get("volumes", []):
            if volume.get("secret", {}).get("secretName"):
                consumed.add(volume["secret"]["secretName"])

    orphans = sorted(provisioned - consumed)
    assert not orphans, f"{cloud}-{env}: {orphans} provisioned and read by nothing"


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_an_advertised_scrape_port_is_reachable(cloud: str, env: str) -> None:
    """An annotation is a request; a NetworkPolicy is the answer.

    The pod annotated `prometheus.io/scrape: "true"` on port 8000 while
    `default-deny` denied every ingress except the one rule naming
    `ingress-nginx`. Prometheus is not in that namespace, so the scrape was
    refused — and the SLO rules, the dashboards and the alerting all rest on a
    series that would never have arrived.

    Nothing in the rendered manifests contradicts itself, which is why this has
    to be asserted across two documents rather than inside one.
    """
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    deployment = next(doc for doc in documents if doc["kind"] == "Deployment")
    annotations = deployment["spec"]["template"]["metadata"].get("annotations", {})
    if annotations.get("prometheus.io/scrape") != "true":
        pytest.skip("this overlay advertises no scrape")

    port = int(annotations.get("prometheus.io/port", 0))
    assert port, f"{cloud}-{env}: scrape advertised with no port"

    allowed = any(
        any(int(entry.get("port", -1)) == port for entry in rule.get("ports", []))
        for doc in documents
        if doc["kind"] == "NetworkPolicy" and "Ingress" in doc["spec"].get("policyTypes", [])
        for rule in doc["spec"].get("ingress", [])
        for source in rule.get("from", [])
        if "role.ml-platform.io/monitoring" in str(source)
    )
    assert allowed, (
        f"{cloud}-{env}: port {port} is advertised for scraping and no NetworkPolicy admits the monitoring "
        f"namespace to it, so the metrics the SLO rules depend on never arrive"
    )


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_the_pod_can_reach_what_it_needs_to_start(cloud: str, env: str) -> None:
    """Egress the pod depends on, asserted against the policies that permit it.

    `default-deny` plus `allow-dns` left the pod able to resolve a name and
    reach nothing, so it could not fetch its model, read the lakehouse,
    authenticate, or export a span. Each failure surfaces as a timeout, which
    reads as the dependency being down — the same shape as the scrape port
    above, in the other direction.

    The metadata address is the one worth naming explicitly. Workload Identity
    and IRSA both mint tokens at 169.254.169.254, and without egress to it the
    identity fails to authenticate — surfacing as a permission error against
    object storage, which sends whoever debugs it to an IAM binding that is
    correct.
    """
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    egress = [
        rule
        for doc in documents
        if doc["kind"] == "NetworkPolicy" and "Egress" in doc["spec"].get("policyTypes", [])
        for rule in doc["spec"].get("egress", [])
    ]
    assert egress, f"{cloud}-{env}: every egress is denied, so the pod cannot start"

    def _permits(port: int, *, cidr: str | None = None, namespace: str | None = None) -> bool:
        """Whether one egress rule names exactly this peer and admits exactly this port.

        Structural, never a substring of the serialised rule. The previous
        version matched `"ipBlock"` anywhere in `str(rule["to"])`, so the
        metadata server's ipBlock satisfied the HTTPS assertion and deleting the
        0.0.0.0/0 rule left the test green (QA-4 round eleven).
        """
        for rule in egress:
            if not any(int(entry.get("port", -1)) == port for entry in rule.get("ports", [])):
                continue
            for peer in rule.get("to", []):
                if cidr is not None and peer.get("ipBlock", {}).get("cidr") == cidr:
                    return True
                selector = peer.get("namespaceSelector", {}).get("matchLabels", {})
                if namespace is not None and namespace in selector:
                    return True
        return False

    assert _permits(80, cidr="169.254.169.254/32"), (
        f"{cloud}-{env}: no egress to the metadata server on port 80. Workload Identity and IRSA mint tokens "
        f"there over plain HTTP, so the identity cannot authenticate and the symptom appears as a storage "
        f"permission error"
    )
    assert not _permits(443, cidr="169.254.169.254/32"), (
        f"{cloud}-{env}: the metadata server is admitted on 443, which no cloud metadata service uses"
    )
    assert _permits(443, cidr="0.0.0.0/0"), (
        f"{cloud}-{env}: no HTTPS egress, so the model artifact and the Iceberg table are unreachable"
    )
    assert _permits(4317, namespace="role.ml-platform.io/monitoring"), (
        f"{cloud}-{env}: no egress to the OTLP collector, so spans are dropped silently — nothing errors "
        f"and the trace is simply absent"
    )


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_broad_https_egress_cannot_reach_back_into_the_cluster(cloud: str, env: str) -> None:
    """The carve-out is what makes a 0.0.0.0/0 rule acceptable.

    NetworkPolicy cannot match a hostname and the public object-storage ranges
    change without notice, so HTTPS egress is broad by necessity. Broad egress
    to the internet is a cost; broad egress that also reaches the VPC and the
    cluster is lateral movement, and the difference is entirely in `except`.
    """
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    for doc in documents:
        if doc["kind"] != "NetworkPolicy":
            continue
        for rule in doc["spec"].get("egress", []):
            for target in rule.get("to", []):
                block = target.get("ipBlock", {})
                if block.get("cidr") != "0.0.0.0/0":
                    continue
                excluded = set(block.get("except", []))
                missing = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"} - excluded
                assert not missing, (
                    f"{cloud}-{env}: {doc['metadata']['name']} permits egress to 0.0.0.0/0 without "
                    f"excluding {sorted(missing)}, so it reaches the VPC and the cluster as well as "
                    f"the internet"
                )


# --- selectors are not rewritten ----------------------------------------------
#
# QA-4 round ten found, and round eleven proved on a live cluster, that every
# cloud overlay denied DNS. `commonLabels` rewrites selectors as well as labels,
# so allow-dns's peer selector `{k8s-app: kube-dns}` rendered as
# `{cloud, environment, k8s-app}` — a selector no CoreDNS pod carries. The only
# existing assertion checked that a policy NAMED allow-dns was present, which
# it was.

_ALL_OVERLAYS = sorted(p.name for p in OVERLAYS.iterdir() if (p / "kustomization.yaml").is_file())


def test_no_kustomization_uses_common_labels() -> None:
    """The mechanism, banned — so the next policy cannot be broken the same way.

    Checked as parsed YAML rather than grep, because the explanatory comment in
    each kustomization names the key it replaced.
    """
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted((REPO_ROOT / "platform").rglob("kustomization.yaml"))
        if "commonLabels" in (yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    ]
    assert not offenders, (
        f"commonLabels rewrites selectors it does not own, including NetworkPolicy peers: {offenders}. "
        f"Use `labels:` with includeSelectors: false"
    )


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_dns_egress_selects_the_cluster_dns_pods_exactly(cloud: str, env: str) -> None:
    """Exact equality, not containment: an extra key is precisely the defect."""
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    policy = next((d for d in documents if d["kind"] == "NetworkPolicy" and d["metadata"]["name"] == "allow-dns"), None)
    assert policy is not None, f"{cloud}-{env}: allow-dns is missing"
    peers = [peer for rule in policy["spec"]["egress"] for peer in rule.get("to", [])]
    assert peers, f"{cloud}-{env}: allow-dns names no peer"
    for peer in peers:
        assert peer.get("podSelector") == {"matchLabels": {"k8s-app": "kube-dns"}}, (
            f"{cloud}-{env}: allow-dns selects {peer.get('podSelector')}, which no CoreDNS pod carries — "
            f"DNS is denied under default-deny"
        )
        assert peer.get("namespaceSelector") == {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}


@pytest.mark.parametrize("overlay", _ALL_OVERLAYS)
def test_every_selector_in_the_namespace_matches_the_pod(overlay: str) -> None:
    """The opposite failure: a selector that matches NOTHING renders and applies cleanly.

    A Service with no endpoints, a PDB protecting no pod, and a NetworkPolicy
    whose podSelector matches no pod all report success on apply. Each is
    checked against the labels the Deployment actually stamps on its pods.
    """
    documents = _build(OVERLAYS / overlay)
    deployment = next(d for d in documents if d["kind"] == "Deployment")
    pod_labels = deployment["spec"]["template"]["metadata"]["labels"]

    def _selects_the_pod(selector: dict[str, str]) -> bool:
        return all(pod_labels.get(key) == value for key, value in selector.items())

    checked = 0
    for doc in documents:
        kind, name, spec = doc["kind"], doc["metadata"]["name"], doc.get("spec") or {}
        if kind in ("Deployment", "PodDisruptionBudget"):
            selector = spec["selector"]["matchLabels"]
        elif kind == "Service":
            selector = spec.get("selector") or {}
        elif kind == "NetworkPolicy":
            selector = (spec.get("podSelector") or {}).get("matchLabels") or {}
            if not selector:
                continue  # `{}` selects every pod in the namespace by design
        else:
            continue
        checked += 1
        assert _selects_the_pod(selector), f"{overlay}: {kind}/{name} selects {selector}, pod carries {pod_labels}"
    assert checked >= 3, f"{overlay}: only {checked} selector(s) examined — the rendering changed shape"
