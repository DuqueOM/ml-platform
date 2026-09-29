"""V7: the agentic surface is checked against what each tool reads, not against itself.

QA-4 round twelve (P0-1) found all 29 skills at `.claude/skills/<id>.md`, a
path Claude Code never reads, with `sync_agentic_adapters.py --check` and
`validate_agentic_surface.py --strict` both green. Both compared the rendered
tree with `agentic/manifest.yaml`, and the manifest was the thing that was
wrong. These tests pin the property that was missing: a manifest that names the
wrong place passes V1 and fails V7.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import sync_agentic_adapters as sync  # noqa: E402
import validate_agentic_surface as validate  # noqa: E402

MARKER = validate.GENERATED_MARKER

# The layout this repository shipped until round twelve, for the three tools
# V7 knows about: one flat file per artifact under each surface's own root.
FLAT = {
    "claude": {"skills": ".claude/skills/{name}.md", "workflows": ".claude/commands/{name}.md"},
    "cursor": {"skills": ".cursor/skills/{name}.mdc", "workflows": ".cursor/commands/{name}.mdc"},
    "codex": {"skills": ".codex/skills/{name}.md", "workflows": ".codex/automations/{name}.md"},
}
FIXED = {
    "claude": {"skills": ".claude/skills/{name}/SKILL.md", "workflows": ".claude/commands/{name}.md"},
    "cursor": {"skills": ".agents/skills/{name}/SKILL.md", "workflows": ".cursor/commands/{name}.md"},
    "codex": {"skills": ".agents/skills/{name}/SKILL.md", "workflows": ".codex/automations/{name}.md"},
}
SKILL_FRONT_MATTER = '---\nname: deploy\ndescription: "Ship it (Mode: CONSULT)"\n---\n'
COMMAND_FRONT_MATTER = "---\ndescription: Ship it\n---\n"


def _world(root: Path, layout: dict[str, dict[str, str]], skill_head: str, command_head: str) -> dict[str, Any]:
    """A repository with one skill and one workflow, published at ``layout``."""
    canonical_skill = root / "agentic/skills/deploy/SKILL.md"
    canonical_workflow = root / "agentic/workflows/ship.md"
    for path in (canonical_skill, canonical_workflow):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ndescription: canonical\nmode: CONSULT\n---\n", encoding="utf-8")
    for surface, kinds in layout.items():
        for kind, pattern in kinds.items():
            name = "deploy" if kind == "skills" else "ship"
            target = root / pattern.replace("{name}", name)
            target.parent.mkdir(parents=True, exist_ok=True)
            head = skill_head if kind == "skills" else (command_head if surface == "claude" else "")
            target.write_text(f"{head}{MARKER}\n# {name}\n", encoding="utf-8")
    return {
        "manifest": {"surfaces": {s: {"root": f".{s}", "mode": "pointer", "layout": k} for s, k in layout.items()}},
        "canonical": {"skills": {"deploy": canonical_skill}, "workflows": {"ship": canonical_workflow}},
    }


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(validate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(validate, "failures", [])
    monkeypatch.setattr(validate, "notes", [])
    monkeypatch.setattr(validate, "warnings", [])
    monkeypatch.setattr(validate, "reports", [])
    return tmp_path


def _failures(check: str) -> list[str]:
    return [f for f in validate.failures if f.startswith(f"[{check}]")]


def test_the_shipped_flat_layout_passes_v1_and_fails_v7(isolated: Path) -> None:
    """The round-twelve defect, reproduced: self-consistent, and invisible to every tool."""
    world = _world(isolated, FLAT, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)

    validate.check_parity(world["manifest"], world["canonical"])
    assert not _failures("V1"), "the flat layout is consistent with its own manifest — V1 cannot see this"

    validate.check_discovery(world["manifest"], world["canonical"])
    missed = _failures("V7")
    assert any("claude: skills/deploy is not where the tool looks" in f for f in missed), missed
    assert any("codex: skills/deploy" in f for f in missed), missed
    assert any("cursor: workflows/ship" in f for f in missed), "a .mdc command is invisible to Cursor"


def test_v1_fails_a_file_left_at_a_superseded_layout(isolated: Path) -> None:
    """A flat `.claude/skills/<id>.md` beside the new `<id>/SKILL.md` is neither published nor ignored."""
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    (isolated / ".claude/skills/deploy.md").write_text(f"{MARKER}\n", encoding="utf-8")
    validate.check_parity(world["manifest"], world["canonical"])
    assert any(".claude/skills/deploy.md is not at a path the skills layout produces" in f for f in _failures("V1"))


def test_the_discovery_layout_passes_v7(isolated: Path) -> None:
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    validate.check_discovery(world["manifest"], world["canonical"])
    assert not _failures("V7"), validate.failures


@pytest.mark.parametrize(
    ("skill_head", "command_head", "expected"),
    [
        ("", COMMAND_FRONT_MATTER, "has no front-matter"),
        ("---\nname: deploy\n---\n", COMMAND_FRONT_MATTER, "missing 'description'"),
        ("---\ndescription: x\n---\n", COMMAND_FRONT_MATTER, "missing 'name'"),
        ("---\nname: deploy-app\ndescription: x\n---\n", COMMAND_FRONT_MATTER, "requires its folder name"),
        (f"---\nname: deploy\ndescription: {'x' * 1025}\n---\n", COMMAND_FRONT_MATTER, "exceeds 1024"),
        (SKILL_FRONT_MATTER, "", ".claude/commands/ship.md has no front-matter"),
        ('---\nname: deploy\ndescription: ""\n---\n', COMMAND_FRONT_MATTER, "missing 'description'"),
        (
            SKILL_FRONT_MATTER,
            "---\nargument-hint: x\n---\n",
            ".claude/commands/ship.md front-matter is missing 'description'",
        ),
    ],
    ids=[
        "no-front-matter",
        "no-description",
        "no-name",
        "name-not-folder",
        "description-too-long",
        "bare-command",
        "empty-description",  # round thirteen survivor V7-empty-desc-ok
        "command-without-description",  # round thirteen survivor V7-claude-cmd-desc-dropped
    ],
)
def test_v7_fails_what_a_tool_would_not_list(isolated: Path, skill_head: str, command_head: str, expected: str) -> None:
    world = _world(isolated, FIXED, skill_head, command_head)
    validate.check_discovery(world["manifest"], world["canonical"])
    assert any(expected in f for f in _failures("V7")), validate.failures


def test_v7_fails_a_surface_that_only_finds_another_surfaces_copy(isolated: Path) -> None:
    """Codex pointed at `.codex/skills/` still finds Cursor's `.agents/skills/` copy — until Cursor's moves."""
    layout = {**FIXED, "codex": {**FIXED["codex"], "skills": ".codex/skills/{name}/SKILL.md"}}
    world = _world(isolated, layout, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    validate.check_discovery(world["manifest"], world["canonical"])
    assert any("codex: publishes skills to .codex/skills/{name}/SKILL.md" in f for f in _failures("V7"))


def test_a_new_surface_cannot_arrive_without_a_discovery_contract(isolated: Path) -> None:
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    world["manifest"]["surfaces"]["windsurf"] = {"root": ".windsurf", "mode": "pointer", "layout": {}}
    validate.check_discovery(world["manifest"], world["canonical"])
    assert any("windsurf: no discovery contract recorded" in f for f in _failures("V7"))


def test_v7_prints_no_ok_above_its_own_failure(isolated: Path) -> None:
    world = _world(isolated, FLAT, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    validate.check_discovery(world["manifest"], world["canonical"])
    assert _failures("V7")
    assert not [n for n in validate.passing_notes() if n.startswith("[V7]")]


def test_one_tool_reaching_two_identical_copies_is_accepted(isolated: Path) -> None:
    """Cursor reads `.agents/` and `.claude/`: listed twice, the same skill both times (P2-3)."""
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    validate.check_discovery(world["manifest"], world["canonical"])
    assert not _failures("V7"), validate.failures


def test_one_tool_reaching_copies_that_disagree_fails(isolated: Path) -> None:
    """Two skills under one name, and the tool — not this repository — picks which runs."""
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    claude = isolated / ".claude/skills/deploy/SKILL.md"
    claude.write_text(claude.read_text().replace("Ship it", "Something else"), encoding="utf-8")
    validate.check_discovery(world["manifest"], world["canonical"])
    assert any("cursor reaches skill 'deploy' through copies that disagree" in f for f in _failures("V7"))


_COPY = '---\nname: deploy\ndescription: "canonical (Mode: CONSULT)"\n---\n'
_OTHER = '---\nname: deploy\ndescription: "a different skill (Mode: AUTO)"\n---\n'


def _nested(root: Path, owner: str, rel: str, text: str = _COPY, unit: str = "svc") -> None:
    target = root / owner / unit / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@pytest.fixture
def no_exemptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real exemptions name this repository's service, which a temporary tree does not have."""
    monkeypatch.setattr(validate, "V8_EXEMPT", {})


@pytest.mark.usefixtures("no_exemptions")
def test_v8_reports_an_inherited_service_without_failing(isolated: Path) -> None:
    """P2-4: services/ are the template's (ADR-003) — seen every run, never silently."""
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    _nested(isolated, "services", ".cursor/skills/deploy.md")
    _nested(isolated, "services", ".claude/skills/deploy/SKILL.md")
    validate.check_nested_surfaces(world["canonical"])
    assert not _failures("V8")
    assert any(".cursor/skills: 1 flat pointer(s) no tool loads" in r for r in validate.reports), validate.reports
    assert any(".claude/skills: 1 skill(s) that copy a root skill" in r for r in validate.reports)


@pytest.mark.usefixtures("no_exemptions")
def test_v8_fails_the_same_defect_in_a_project_of_ours(isolated: Path) -> None:
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    _nested(isolated, "projects", ".agents/skills/deploy/SKILL.md")
    validate.check_nested_surfaces(world["canonical"])
    assert any("projects/svc/.agents/skills: 1 skill(s) that copy a root skill" in f for f in _failures("V8"))


# --- round fourteen, P3-4: any depth, and copies told apart from collisions ----


@pytest.mark.usefixtures("no_exemptions")
@pytest.mark.parametrize(
    "where",
    ["libs/llm-core/.agents/skills", "projects/rag-assistant/src/.agents/skills", "docs/.cursor/skills"],
)
def test_v8_sees_a_discovery_directory_at_any_depth(isolated: Path, where: str) -> None:
    """The auditor's three probes, each of which V8 inspected as `2 directories … OK`."""
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    target = isolated / where / "deploy" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text(_COPY, encoding="utf-8")
    validate.check_nested_surfaces(world["canonical"])
    assert any(f"{where}: 1 skill(s) that copy a root skill" in f for f in _failures("V8")), validate.failures


@pytest.mark.usefixtures("no_exemptions")
def test_v8_fails_a_different_skill_under_a_root_name_even_in_a_service(isolated: Path) -> None:
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    _nested(isolated, "services", ".agents/skills/deploy/SKILL.md", _OTHER)
    validate.check_nested_surfaces(world["canonical"])
    assert any("services/svc/.agents/skills/deploy: a different skill" in f for f in _failures("V8"))


def test_v8_notes_an_exempted_collision_and_fails_an_outlived_exemption(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    _nested(isolated, "services", ".agents/skills/deploy/SKILL.md", _OTHER)
    monkeypatch.setattr(
        validate, "V8_EXEMPT", {("services/svc", "deploy"): "the template's", ("services/svc", "gone"): "renamed"}
    )
    validate.check_nested_surfaces(world["canonical"])
    assert any("deploy: a different skill under a root skill's name — exempt" in r for r in validate.reports)
    assert _failures("V8") == [
        "[V8] V8_EXEMPT names services/svc/gone, which no longer collides — delete the exemption"
    ]


@pytest.mark.usefixtures("no_exemptions")
def test_v8_does_not_walk_into_another_checkout(isolated: Path) -> None:
    """A worktree under `.claude/worktrees/` is another copy of the repository, not a nested surface."""
    world = _world(isolated, FIXED, SKILL_FRONT_MATTER, COMMAND_FRONT_MATTER)
    worktree = isolated / ".claude" / "worktrees" / "wip"
    (worktree / ".agents" / "skills" / "deploy").mkdir(parents=True)
    (worktree / ".agents" / "skills" / "deploy" / "SKILL.md").write_text(_OTHER, encoding="utf-8")
    (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    validate.check_nested_surfaces(world["canonical"])
    assert not _failures("V8"), validate.failures


def test_the_real_exemptions_still_name_real_collisions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run against this repository: an exemption that outlives its collision fails V8."""
    for bucket in ("failures", "notes", "warnings", "reports"):
        monkeypatch.setattr(validate, bucket, [])
    manifest = validate.yaml.safe_load(validate.MANIFEST.read_text(encoding="utf-8"))
    validate.check_nested_surfaces(validate.collect_canonical(manifest))
    assert not _failures("V8"), validate.failures


def test_no_ok_line_above_a_warning_for_the_same_check(isolated: Path) -> None:
    """P3-3: V6 printed `ok` above its own warning, which --strict turns into a failure."""
    validate.warn("V6", "rule 99-probe cites no authority")
    validate.ok("V6", "24 rules carry a resolvable authority")
    validate.ok("V1", "untouched")
    assert validate.passing_notes() == ["[V1] untouched"]


# --- the renderer -------------------------------------------------------------


def _artifact(kind: str, name: str, body: str) -> sync.Artifact:
    source = REPO_ROOT / "agentic" / kind / (f"{name}/SKILL.md" if kind == "skills" else f"{name}.md")
    return sync.Artifact(kind=kind, name=name, source=source, body=body)


def test_a_rendered_skill_carries_name_description_and_mode_and_nothing_else() -> None:
    body = "---\nname: x\ndescription: Does x\nmode: STOP\nallowed-tools:\n  - Bash(aws:*)\n---\n# x\n"
    rendered = sync.render_pointer(_artifact("skills", "x", body), ["claude"], with_front_matter=True)
    head = validate._front_matter(rendered)
    assert head == {"name": "x", "description": "Does x (Mode: STOP)"}, (
        "allowed-tools must not be copied: pre-approving a tool is a reviewed decision in the canonical body"
    )


def test_a_rendered_command_carries_no_name() -> None:
    """Claude rejects `name` in a command file."""
    rendered = sync.render_pointer(
        _artifact("workflows", "ship", "---\ndescription: Ship\n---\n"), ["claude"], with_front_matter=True
    )
    assert validate._front_matter(rendered) == {"description": "Ship"}


def test_a_canonical_body_without_a_description_is_refused_not_rendered_bare() -> None:
    with pytest.raises(SystemExit, match="no `description:` front-matter"):
        sync.render_pointer(_artifact("workflows", "ship", "# /ship\n"), ["claude"], with_front_matter=True)


def test_a_shared_path_is_rendered_once_and_names_every_surface() -> None:
    artifact = _artifact("skills", "x", "---\nname: x\ndescription: Does x\nmode: AUTO\n---\n")
    manifest = {
        "surfaces": {
            s: {
                "root": f".{s}",
                "mode": "pointer",
                "layout": {"skills": ".agents/skills/{name}/SKILL.md"},
                "front_matter": ["skills"],
            }
            for s in ("cursor", "codex")
        }
    }
    outputs = sync.render_all(manifest, [artifact])
    assert list(outputs) == [REPO_ROOT / ".agents/skills/x/SKILL.md"]
    assert "**Adapter surfaces**: `cursor`, `codex`" in outputs[REPO_ROOT / ".agents/skills/x/SKILL.md"]


def test_a_shared_path_rendered_two_ways_is_a_manifest_error() -> None:
    artifact = _artifact("skills", "x", "---\nname: x\ndescription: Does x\n---\n")
    layout = {"skills": ".agents/skills/{name}/SKILL.md"}
    manifest = {
        "surfaces": {
            "cursor": {"root": ".cursor", "mode": "pointer", "layout": layout, "front_matter": ["skills"]},
            "codex": {"root": ".codex", "mode": "pointer", "layout": layout, "front_matter": []},
        }
    }
    with pytest.raises(SystemExit, match="would render it differently"):
        sync.render_all(manifest, [artifact])
