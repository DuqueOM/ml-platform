"""Gate C3: the compliance mapping states only what the tree supports.

`docs/COMPLIANCE_MAPPING.md` went stale in seven places at once while nothing
checked it — Bandit "invoked by no workflow", Trivy "cannot fail a build", C7
"red at 37 commits", "55 audit entries", "9 ADRs" — each overtaken by the tree
and each still reading as current. These tests make the gate fail in each of
those ways, and in the ways a looser version of it would let through: a clause
attributed to the wrong scanner, an aggregator that needs a job without
asserting its result, a comment that mentions `cosign`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_compliance_mapping as gate  # noqa: E402

MAPPING = gate.MAPPING.read_text(encoding="utf-8")
FIGURES = gate.derive()
VALUES = {figure.key: figure.value for figure in FIGURES}
CONTROLS = gate._security_controls(gate.SECURITY.read_text(encoding="utf-8"))


def _rows(verdicts: dict[str, str]) -> str:
    """A minimal mapping: one row per Category, and a summary that agrees with them."""
    rows = "\n".join(f"| **{category}** Name | Asks | {verdict} | Evidence |" for category, verdict in verdicts.items())
    summary = "\n".join(
        f"| {verdict} | {len(listed)} | {', '.join(listed)} |"
        for verdict in gate.VERDICTS
        for listed in [[category for category, given in verdicts.items() if given == verdict]]
    )
    return f"{rows}\n\n{gate._COUNTED}\n\n| Verdict | Categories | Which |\n| --- | :-: | --- |\n{summary}\n"


ALL_PARTIAL = dict.fromkeys(gate.CATEGORIES, "Partial")


# --- the committed document ---------------------------------------------------


def test_the_committed_mapping_passes() -> None:
    assert gate.main([]) == 0


def test_every_failure_mode_is_reached_by_the_committed_check() -> None:
    """`check` is what `main` runs, so a check function it forgot would pass over nothing."""
    assert gate.check(MAPPING, FIGURES, CONTROLS) == []


def test_security_md_is_read_as_the_tests_read_it() -> None:
    """The Blocking column, as `tests/test_security_controls.py` holds it against the workflows."""
    assert CONTROLS["gitleaks"] is True
    assert CONTROLS["Trivy"] is True
    assert CONTROLS["Bandit"] is True
    assert CONTROLS["Checkov"] is False
    assert CONTROLS["Kubescape"] is False


def test_an_unreadable_controls_table_fails_rather_than_passing_over_nothing() -> None:
    assert gate._security_controls("# SECURITY\n\nno table here\n") == {}
    assert gate.check_scanner_claims("Trivy blocks.", {}) != []


# --- structure ------------------------------------------------------------------


def test_a_complete_mapping_has_a_consistent_structure() -> None:
    assert gate.check_structure(_rows(ALL_PARTIAL)) == []


def test_a_missing_category_fails() -> None:
    verdicts = dict(ALL_PARTIAL)
    del verdicts["DE.AE"]
    failures = gate.check_structure(_rows(verdicts))
    assert any("DE.AE has no row" in failure for failure in failures)


def test_a_category_assessed_twice_fails() -> None:
    text = _rows(ALL_PARTIAL).replace("| **GV.OC**", "| **GV.OC** Again | Asks | Partial | E |\n| **GV.OC**", 1)
    assert any("GV.OC has two rows" in failure for failure in gate.check_structure(text))


def test_a_category_that_is_not_in_the_framework_fails() -> None:
    text = _rows(ALL_PARTIAL) + "| **GV.XX** Invented | Asks | Partial | E |\n"
    assert any("not a NIST CSF 2.0 Category" in failure for failure in gate.check_structure(text))


def test_a_verdict_outside_the_three_fails() -> None:
    """ "Not applicable" is how an absent control stops being counted."""
    verdicts = dict(ALL_PARTIAL, **{"RC.CO": "Not applicable"})
    assert any("RC.CO has verdict 'Not applicable'" in failure for failure in gate.check_structure(_rows(verdicts)))


def test_a_summary_that_disagrees_with_the_rows_fails() -> None:
    text = _rows(ALL_PARTIAL).replace("| **ID.AM** Name | Asks | Partial |", "| **ID.AM** Name | Asks | Satisfied |")
    failures = gate.check_structure(text)
    assert any("summary row Satisfied" in failure for failure in failures)
    assert any("summary row Partial" in failure for failure in failures)


def test_a_summary_whose_count_disagrees_with_its_list_fails() -> None:
    text = _rows(ALL_PARTIAL).replace("| Partial | 22 |", "| Partial | 21 |")
    assert any("says 21 and lists 22" in failure for failure in gate.check_structure(text))


def test_a_mapping_with_no_summary_fails() -> None:
    text = _rows(ALL_PARTIAL).split(gate._COUNTED)[0]
    assert any("no '## The result, counted'" in failure for failure in gate.check_structure(text))


# --- the derived block --------------------------------------------------------------


def test_a_stale_derived_block_fails() -> None:
    stale = MAPPING.replace(f"| ADRs | {VALUES['adrs']} |", "| ADRs | 9 |")
    assert stale != MAPPING
    assert any("derived-figures block is stale" in failure for failure in gate.check(stale, FIGURES, CONTROLS))


def test_a_mapping_without_the_block_fails() -> None:
    start, end = MAPPING.index(gate.BEGIN), MAPPING.index(gate.END) + len(gate.END)
    stripped = MAPPING[:start] + MAPPING[end:]
    assert any("no derived-figures block" in failure for failure in gate.check(stripped, FIGURES, CONTROLS))


def test_write_regenerates_a_stale_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = tmp_path / "COMPLIANCE_MAPPING.md"
    document.write_text(MAPPING.replace(f"| ADRs | {VALUES['adrs']} |", "| ADRs | 9 |"), encoding="utf-8")
    monkeypatch.setattr(gate, "MAPPING", document)
    assert gate.main([]) == 1
    assert gate.main(["--write"]) == 0
    assert document.read_text(encoding="utf-8") == MAPPING


def test_write_refuses_a_document_with_nowhere_to_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = tmp_path / "COMPLIANCE_MAPPING.md"
    document.write_text("# Compliance mapping\n", encoding="utf-8")
    monkeypatch.setattr(gate, "MAPPING", document)
    assert gate.main(["--write"]) == 1


# --- quoted and dated figures -----------------------------------------------------------


@pytest.mark.parametrize(
    ("quoted", "key"),
    [
        ("{} rules", "rules"),
        ("{} skills", "skills"),
        ("{} workflows", "workflows"),
        ("{} ADRs", "adrs"),
        ("{} declared gates", "gates"),
        ("**{} at L4**", "l4"),
    ],
)
def test_a_quoted_count_must_equal_the_derived_one(quoted: str, key: str) -> None:
    right = quoted.format(VALUES[key])
    wrong = quoted.format(int(VALUES[key]) + 1)
    assert gate.check_quoted_figures(f"It has {right}.", VALUES) == []
    failures = gate.check_quoted_figures(f"It has {wrong}.", VALUES)
    assert failures
    assert key in failures[0]


def test_the_block_itself_is_not_read_as_a_quotation() -> None:
    """The block is the source; a stale one is the block check's finding, not this one's."""
    text = f"{gate.BEGIN}\n| Agentic rules | 9 rules |\n{gate.END}\n"
    assert gate.check_quoted_figures(text, VALUES) == []


@pytest.mark.parametrize(
    "figure",
    ["37 commits have landed since the marker", "55 audit entries", "115 failed checks", "114 findings"],
)
def test_an_undated_measurement_fails_and_a_dated_one_passes(figure: str) -> None:
    assert gate.check_dated_measurements(f"C7 reports {figure}.", "doc")
    assert gate.check_dated_measurements(f"On 2026-08-08 it reported {figure}.", "doc") == []


def test_the_date_must_share_the_paragraph() -> None:
    text = "Measured on 2026-08-08.\n\nIt reports 115 failed checks."
    assert gate.check_dated_measurements(text, "doc")


def test_the_documents_quoting_the_same_measurement_are_held_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`SECURITY.md` said "currently finds 114" while the scanner found 104."""
    security = tmp_path / "SECURITY.md"
    security.write_text("**Checkov reports and does not block.** It currently finds 114 findings.\n", encoding="utf-8")
    monkeypatch.setattr(gate, "QUOTE_THE_SAME_MEASUREMENTS", (security,))
    failures = gate.check(MAPPING, FIGURES, CONTROLS)
    assert any(failure.startswith("SECURITY.md: '114 findings'") for failure in failures)


# --- scanner claims ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        'Trivy runs with `exit-code: "0"` and cannot fail a build.',
        "Bandit is configured in `pyproject.toml` and invoked by no workflow.",
        "| Evidence | gitleaks is advisory |",
    ],
)
def test_a_blocking_scanner_said_not_to_block_fails(sentence: str) -> None:
    """The direction every stale sentence in the mapping took."""
    assert gate.check_scanner_claims(sentence, CONTROLS)


@pytest.mark.parametrize("sentence", ["Checkov blocks every merge.", "Kubescape fails the build on a finding."])
def test_an_advisory_scanner_said_to_block_fails(sentence: str) -> None:
    """The direction that misleads an adopter into trusting a gate that is not there."""
    assert gate.check_scanner_claims(sentence, CONTROLS)


@pytest.mark.parametrize(
    "sentence",
    [
        "Checkov reports and does not block.",
        "Trivy was claimed blocking and could not fail a build.",
        "Bandit was configured and no workflow ran it.",
        "Bandit and Trivy block; Checkov and Kubescape report and do not block.",
        "Trivy blocks on HIGH, and Checkov reports and does not block.",
    ],
)
def test_true_and_past_tense_sentences_pass(sentence: str) -> None:
    assert gate.check_scanner_claims(sentence, CONTROLS) == []


def test_a_claim_is_attributed_to_the_name_it_follows() -> None:
    """Not to every name in the sentence: here only Checkov is said to block."""
    failures = gate.check_scanner_claims("Trivy scans, and Checkov blocks.", CONTROLS)
    assert len(failures) == 1
    assert failures[0].startswith("'Checkov'")


# --- evidence ------------------------------------------------------------------------------


def test_a_cited_symbol_that_exists_passes() -> None:
    text = "`tests/test_security_controls.py::_blocks`"
    assert gate.check_symbol_citations(text) == []


def test_a_cited_symbol_that_does_not_exist_fails() -> None:
    text = "`tests/test_security_controls.py::_blocks_everything`"
    assert any("defines no _blocks_everything" in failure for failure in gate.check_symbol_citations(text))


def test_a_cited_file_that_does_not_exist_fails() -> None:
    assert gate.check_symbol_citations("`tests/test_nothing_here.py::test_it`")


# --- the derivations ------------------------------------------------------------------------


def _workflow(tmp_path: Path, name: str, body: str) -> Path:
    directory = tmp_path / "workflows"
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(body, encoding="utf-8")
    return directory


def test_an_image_step_is_counted_by_what_it_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = _workflow(
        tmp_path,
        "build.yml",
        "jobs:\n  build:\n    steps:\n"
        "      - uses: docker/build-push-action@abc\n"
        "      - run: cosign sign --yes $DIGEST\n"
        "      - name: Not yet — cosign arrives with the first image\n"
        "        run: |\n          # cosign sign is Phase 2\n          echo nothing\n",
    )
    monkeypatch.setattr(gate, "WORKFLOWS", directory)
    assert gate._image_steps() == 2


def test_baseline_entries_ignore_comments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".trivyignore").write_text("# header\n\nCVE-2026-1  # reason\nGHSA-x  \n", encoding="utf-8")
    (tmp_path / "checkov.yml").write_text("skip-check:\n  - CKV_K8S_8\n", encoding="utf-8")
    (tmp_path / "tfsec.yml").write_text("exclude: []\n", encoding="utf-8")
    monkeypatch.setattr(gate, "BASELINES", tmp_path)
    assert gate._baseline_entries() == {"Trivy": 2, "Checkov": 1, "tfsec": 0}


def _protection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ci: str) -> None:
    script = tmp_path / "protect.sh"
    script.write_text(
        'REQUIRED_CHECKS=(\n  "Repository invariants"\n)\n"required_approving_review_count": 0,\n', encoding="utf-8"
    )
    (tmp_path / "ci.yml").write_text(ci, encoding="utf-8")
    monkeypatch.setattr(gate, "BRANCH_PROTECTION", script)
    monkeypatch.setattr(gate, "CI", tmp_path / "ci.yml")


def test_an_aggregator_covers_only_the_jobs_it_asserts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`needs` alone is not waiting: under `if: always()` a failed dependency still lets it succeed."""
    _protection(
        tmp_path,
        monkeypatch,
        "jobs:\n"
        "  gates: {name: Fast gates, steps: [{run: 'true'}]}\n"
        "  tests: {name: Tests, steps: [{run: 'true'}]}\n"
        "  invariants:\n"
        "    name: Repository invariants\n"
        "    needs: [gates, tests]\n"
        "    if: always()\n"
        '    steps: [{run: "test ${{ needs.gates.result }} = success"}]\n',
    )
    assert gate._merge_waits_on() == (2, 3, ["Tests"])
    assert gate._required_checks() == (["Repository invariants"], 0)


def test_the_committed_ci_waits_on_every_job() -> None:
    waited, jobs, missing = gate._merge_waits_on()
    assert (waited, missing) == (jobs, [])
