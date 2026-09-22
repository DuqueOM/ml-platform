"""Every namespace a policy selects is declared, and every declared role is provisioned or says who does.

QA-4 round ten found it and round eleven left it open: `allow-serving-ingress`
and `allow-serving-egress` selected namespaces by labels that no namespace in
this repository, or in any cluster it describes, carries. Under `default-deny`
the serving pod could therefore be neither scraped nor reached — and every
render, every manifest test and every overlay build passed, because a selector
that matches nothing is syntactically perfect.

The contract in `platform/policies/namespace-contract.yaml` is the data; this
is the gate. It answers two questions a render cannot:

* does every label a policy selects correspond to a declared role, and
* is every role either provisioned here, or accompanied by a statement of who
  provisions it and what happens where it is absent.

The second half matters for a template. This repository cannot install a
monitoring stack into somebody's cluster, and pretending otherwise would be
worse than the gap; what it can do is refuse to ship a policy whose dependency
nobody has written down.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICIES = REPO_ROOT / "platform" / "policies"
CONTRACT = POLICIES / "namespace-contract.yaml"
LOCAL_MANIFESTS = REPO_ROOT / "platform" / "local" / "manifests"

#: Labels Kubernetes sets on every namespace itself. A policy may select one
#: without the platform declaring anything, because nobody can forget it.
BUILT_IN_LABELS = frozenset({"kubernetes.io/metadata.name"})


def _contract(path: Path = CONTRACT) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _selectors(directory: Path = POLICIES) -> list[tuple[str, dict[str, str]]]:
    """Every `namespaceSelector` matchLabels block in the policies, with its file."""
    found = []
    for policy in sorted(directory.glob("*.yaml")):
        for document in yaml.safe_load_all(policy.read_text(encoding="utf-8")):
            if not document or document.get("kind") != "NetworkPolicy":
                continue
            spec = document.get("spec") or {}
            for direction in ("ingress", "egress"):
                for rule in spec.get(direction) or []:
                    for peer in rule.get("to") or rule.get("from") or []:
                        labels = (peer.get("namespaceSelector") or {}).get("matchLabels")
                        if labels:
                            found.append((policy.stem, labels))
    return found


def _declared_labels(contract: dict[str, Any]) -> dict[str, str]:
    prefix = contract["label_prefix"]
    return {f"{prefix}/{role['id']}": role["id"] for role in contract["roles"]}


def _local_namespace_labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    for manifest in sorted(LOCAL_MANIFESTS.glob("*.yaml")):
        for document in yaml.safe_load_all(manifest.read_text(encoding="utf-8")):
            if document and document.get("kind") == "Namespace":
                labels.update((document.get("metadata") or {}).get("labels") or {})
    return labels


def test_there_are_policies_and_roles_to_check() -> None:
    """An empty glob or an empty contract would satisfy everything below."""
    assert _selectors(), "no namespaceSelector found — the policies changed shape, or the glob broke"
    assert _contract()["roles"], "the contract declares no roles"


@pytest.mark.parametrize(("policy", "labels"), _selectors())
def test_every_selected_namespace_label_is_declared(policy: str, labels: dict[str, str]) -> None:
    """The finding itself: a policy may not select a label nobody declares."""
    declared = _declared_labels(_contract())
    for key in labels:
        assert key in BUILT_IN_LABELS or key in declared, (
            f"{policy} selects namespaces by {key!r}, which is neither a Kubernetes built-in nor a role in "
            f"namespace-contract.yaml. A selector matching nothing drops traffic while rendering perfectly"
        )


def test_every_declared_role_says_who_provisions_it() -> None:
    """A role without a provisioner is a dependency nobody owns."""
    for role in _contract()["roles"]:
        provisioned = role.get("provisioned_by") or {}
        assert role.get("purpose", "").strip(), f"role {role['id']} states no purpose"
        assert provisioned.get("cloud", "").strip(), f"role {role['id']} says nobody provisions it in cloud"
        assert provisioned.get("local", "").strip(), f"role {role['id']} says nothing about the local stack"
        assert isinstance(role.get("fulfilled_locally"), bool), (
            f"role {role['id']} does not state whether the local stack fulfils it, so a locally dropped "
            f"packet cannot be told from a deliberate absence"
        )


def test_every_role_the_local_stack_claims_is_on_a_namespace_it_creates() -> None:
    """`fulfilled_locally: true` is a claim about a manifest, checked against it."""
    contract = _contract()
    prefix, labels = contract["label_prefix"], _local_namespace_labels()
    for role in contract["roles"]:
        key = f"{prefix}/{role['id']}"
        if role["fulfilled_locally"]:
            assert labels.get(key) == "true", (
                f"role {role['id']} claims the local stack fulfils it, but no Namespace under "
                f"{LOCAL_MANIFESTS.relative_to(REPO_ROOT)} carries {key}=true"
            )
        else:
            assert key not in labels, (
                f"role {role['id']} is declared unfulfilled locally while a local Namespace carries {key}; "
                f"one of the two is wrong"
            )


def test_every_role_is_used_by_the_policies_it_names() -> None:
    """A role nothing selects is a dependency the platform no longer has."""
    by_policy = {}
    for policy, labels in _selectors():
        by_policy.setdefault(policy, set()).update(labels)
    prefix = _contract()["label_prefix"]
    for role in _contract()["roles"]:
        key = f"{prefix}/{role['id']}"
        for policy in role.get("used_by") or []:
            assert policy in by_policy, f"role {role['id']} names {policy}, which declares no namespaceSelector"
            assert key in by_policy[policy], f"role {role['id']} claims {policy} selects it, and it does not"


def test_an_undeclared_selector_is_reported(tmp_path: Path) -> None:
    """The gate, watched failing — against a temporary policy, never the real ones."""
    policy = tmp_path / "probe.yaml"
    policy.write_text(
        "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata: {name: probe}\n"
        "spec:\n  podSelector: {}\n  policyTypes: [Ingress]\n  ingress:\n"
        "    - from:\n        - namespaceSelector:\n            matchLabels: {app.kubernetes.io/name: monitoring}\n",
        encoding="utf-8",
    )
    declared = _declared_labels(_contract())
    offenders = [
        (name, key)
        for name, labels in _selectors(tmp_path)
        for key in labels
        if key not in BUILT_IN_LABELS and key not in declared
    ]
    assert offenders == [("probe", "app.kubernetes.io/name")], offenders
