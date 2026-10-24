"""C11: the technical plan's acceptance commands resolve, or say they cannot yet (W-6).

The plan's own rule is that a phase is complete only when every acceptance
command exits zero, and nothing read them. Phase 3 ran a test file as a
script, which executes no test; Phase 1 named a load test and a module that
do not exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_doc_coherence as coherence  # noqa: E402

PLAN = """# Plan

## Phase 9 — An example

### Deliverables

- Not a command.

### Acceptance

```bash
{commands}
```
"""


def _plan(*commands: str) -> str:
    return PLAN.format(commands="\n".join(commands))


def test_commands_are_read_with_continuations_joined_and_sample_output_skipped() -> None:
    text = _plan(
        "uv run pytest tests/test_plan_acceptance.py -q",
        "kubectl --context x \\",
        "  wait --for=condition=ready pod",
        "uv run python scripts/check_library_reuse.py",
        "  ok   [reuse] sample output, not a command",
    )

    assert [command for _, _, command in coherence.plan_acceptance_commands(text)] == [
        "uv run pytest tests/test_plan_acceptance.py -q",
        "kubectl --context x wait --for=condition=ready pod",
        "uv run python scripts/check_library_reuse.py",
    ]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("uv run pytest projects/no-such-project -q", "names projects/no-such-project, which does not exist"),
        ("uv run python -m demand_forecast.no_such_module", "runs the module demand_forecast.no_such_module"),
        ("make no-such-target", "runs `make no-such-target`, which the Makefile does not define"),
        ("uv run pytest -k no_test_is_called_this", "selects `-k no_test_is_called_this`, which matches no test"),
        ("uv run python tests/test_dependency_direction.py", "as a script, which executes no test"),
        ("terraform -chdir=platform/no-such-dir plan", "names platform/no-such-dir, which does not exist"),
    ],
)
def test_each_unresolvable_reference_is_named(command: str, expected: str) -> None:
    assert any(expected in item for item in coherence.unresolved_in_command(command)), coherence.unresolved_in_command(
        command
    )


@pytest.mark.parametrize(
    "command",
    [
        "uv run pytest projects/demand-forecast -q",
        "uv run python -m demand_forecast.lakehouse",
        "make local-up            # a comment naming projects/nothing-here",
        "kubectl -n demand-forecast-local port-forward svc/demand-forecast 18080:80 &",
        'curl -s "$SERVICE_URL/health"',
        "uv run pytest tests/test_dependency_direction.py -q",
    ],
)
def test_what_resolves_is_not_reported(command: str) -> None:
    """A kubectl resource, a variable and a comment are not repository paths."""
    assert coherence.unresolved_in_command(command) == []


def _run_c11(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> list[str]:
    plan = tmp_path / "technical-plan.md"
    plan.write_text(text, encoding="utf-8")
    monkeypatch.setattr(coherence, "PLAN", plan)
    monkeypatch.setattr(coherence, "REPO_ROOT", REPO_ROOT)
    coherence.failures.clear()
    coherence.notes.clear()
    coherence.check_plan_acceptance_commands()
    return list(coherence.failures)


def test_a_pending_command_is_accepted_until_it_resolves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pending = _plan("uv run pytest projects/not-yet -q   # PENDING — not started")
    assert _run_c11(monkeypatch, tmp_path, pending) == []

    stale = _plan("uv run pytest projects/demand-forecast -q   # PENDING — written before it existed")
    (failure,) = _run_c11(monkeypatch, tmp_path, stale)
    assert "resolves now — remove its PENDING marker" in failure


def test_a_plan_without_acceptance_commands_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (failure,) = _run_c11(monkeypatch, tmp_path, "# Plan\n\nNo phases at all.\n")
    assert "no acceptance commands found" in failure
