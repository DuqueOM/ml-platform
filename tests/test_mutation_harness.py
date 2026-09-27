"""The committed mutation catalogue stays applicable.

`scripts/mutation_harness.py` is slow — it runs a test selection per mutation
— so it is not part of the suite. What must not happen silently is the
catalogue rotting: a refactor that moves an anchor would turn a mutation into
one that no longer applies, and the harness would shrink without anyone
deciding it should. This keeps every entry pointed at real code.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import mutation_harness  # noqa: E402

CATALOGUE = mutation_harness.load()


def test_the_catalogue_is_not_empty() -> None:
    assert len(CATALOGUE) >= 30, "the catalogue shrank — was a mutation removed on purpose?"


def test_ids_are_unique() -> None:
    ids = [m["id"] for m in CATALOGUE]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)


@pytest.mark.parametrize("mutation", CATALOGUE, ids=[m["id"] for m in CATALOGUE])
def test_every_mutation_still_applies(mutation: dict) -> None:
    source = (REPO_ROOT / mutation["file"]).read_text(encoding="utf-8")
    assert source.count(mutation["old"]) == 1, (
        f"{mutation['id']}: its anchor occurs {source.count(mutation['old'])} times in {mutation['file']}. "
        "Update the catalogue with the code, or the harness silently stops testing this."
    )
    assert mutation["old"] != mutation["new"]


@pytest.mark.parametrize("mutation", CATALOGUE, ids=[m["id"] for m in CATALOGUE])
def test_every_mutation_names_what_must_catch_it(mutation: dict) -> None:
    assert mutation["expect"] in {"killed", "survives"}
    if mutation["expect"] == "survives":
        assert mutation.get("reason"), f"{mutation['id']}: a tolerated survivor needs its reason written down"
    for command in mutation["run"]:
        for token in shlex.split(command):
            if token.endswith(".py") and "/" in token and "::" not in token:
                assert (REPO_ROOT / token).exists(), f"{mutation['id']} runs {token}, which does not exist"
