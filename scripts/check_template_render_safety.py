#!/usr/bin/env python3
"""Contract: every file under the Copier render root must parse as a template.

    python scripts/check_template_render_safety.py
    python scripts/check_template_render_safety.py --root <dir>

Why this exists
---------------
`copier.yml` sets `_templates_suffix: ""`, which means **every** file under
`templates/project/` is a Jinja template — not only the ones that look like
one. Any file that happens to contain Jinja's delimiters is therefore a
scaffolder failure waiting to happen, and the failure is total: `copier copy`
aborts, so whoever runs the generator gets no project at all.

Ported from `ml-service-template`, which wrote it after two of these landed in
one afternoon, neither in a file anyone would think of as a template: a
Markdown table row documenting Jinja tokens, and a shell script using bash's
array-length syntax. Both were caught by its full render job in CI, which is
the right place for the BEHAVIOUR to be checked and the wrong place to discover
a typo.

What it adds to the render test, stated after getting it wrong once
------------------------------------------------------------------
`tests/test_project_generator.py` renders the payload for real, which is the
stronger check on behaviour. When this gate landed, its justification said that
test rendered ONE answer set. That was false: a grep found the default
`ANSWERS` and missed the parametrize that overrides `project_kind`, and the
claim was repeated in four places before QA-4 round eleven caught it. The
render test covered `tabular`, `llm` and `deep-learning`. It omitted `agent`,
which it now renders as well.

So the case for parsing is not the kinds the render test forgot. A render
exercises only the branches its answers select; a parse examines every branch
of every file whatever the answers are — including answer values nobody
enumerates, like a dataset key or an owner string — and it costs milliseconds,
which is what lets it run in pre-commit on every payload edit rather than in a
job measured in minutes.

The two checks are complements and neither subsumes the other. Parsing cannot
catch an undefined variable or a wrong answers file; the render test remains
the authority for that.

What collides with these delimiters
-----------------------------------
The delimiters come from `copier.yml` `_envops` rather than being hardcoded, so
changing them there changes what this checks. They are not the Jinja defaults:
this repository uses `{@ … @}` for expressions because a generated project
ships GitHub Actions workflows where `${{ … }}` is pervasive. That choice
removes the Actions collision and introduces a quieter one — bash's `"${@}"`
contains `{@`, and `${#array[@]}` contains `{#`, which is the comment opener.
Block (`{%`) and comment (`{#`) delimiters are unchanged from Jinja's.

Beyond upstream: path names are templates too
---------------------------------------------
Upstream parses file CONTENTS only. Copier also renders each path SEGMENT, and
this render root actually has one — `src/{@ project_slug @}/`. A malformed
segment aborts the copy exactly as a malformed body does, and it is the harder
of the two to spot in review because a directory name is not somewhere anyone
looks for syntax. Segments are parsed here as well.

Exit codes
----------
- 0: every file and every path segment parses.
- 1: at least one is not a valid Copier template.
- 2: setup error (`copier.yml` unreadable, no render root, or a render root
  holding no payload file — a gate that examined nothing has not passed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from jinja2 import Environment
from jinja2.exceptions import TemplateSyntaxError

REPO_ROOT = Path(__file__).resolve().parent.parent
COPIER_CONF = REPO_ROOT / "copier.yml"

#: Binary trees Copier copies verbatim rather than rendering as text. Suffixes
#: rather than a content sniff: a file whose bytes happen to decode as UTF-8 is
#: still not a template, and guessing is how a gate acquires a false positive
#: nobody can reproduce.
SKIP_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".whl",
        ".pyc",
        ".woff",
        ".woff2",
        ".ttf",
        ".parquet",
        ".joblib",
        ".pkl",
        ".onnx",
    }
)

#: Caches that can appear under the render root on a working copy and never in
#: a commit. Skipped so a local `pytest` run cannot turn this gate red.
SKIP_DIRS = frozenset({"__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache"})


def load_config() -> dict[str, object]:
    """`copier.yml` as data, or a setup error naming why it could not be read."""
    document = yaml.safe_load(COPIER_CONF.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{COPIER_CONF} does not parse as a mapping")
    return document


def render_root(config: dict[str, object]) -> Path:
    """The directory Copier renders, read from `_subdirectory`.

    Read rather than hardcoded for the same reason the delimiters are: a
    constant here would keep checking `templates/project/` after the generator
    moved, and would report OK while examining nothing.
    """
    subdirectory = config.get("_subdirectory")
    if not isinstance(subdirectory, str) or not subdirectory:
        raise ValueError(f"{COPIER_CONF} declares no _subdirectory; there is no render root to check")
    return REPO_ROOT / subdirectory


def environment(config: dict[str, object]) -> Environment:
    """A Jinja environment with Copier's delimiters, used only to `.parse()`."""
    envops = config.get("_envops")
    options: dict[str, object] = envops if isinstance(envops, dict) else {}

    def delimiter(key: str, default: str) -> str:
        value = options.get(key, default)
        return value if isinstance(value, str) else default

    return Environment(
        block_start_string=delimiter("block_start_string", "{%"),
        block_end_string=delimiter("block_end_string", "%}"),
        variable_start_string=delimiter("variable_start_string", "{{"),
        variable_end_string=delimiter("variable_end_string", "}}"),
        comment_start_string=delimiter("comment_start_string", "{#"),
        comment_end_string=delimiter("comment_end_string", "#}"),
        keep_trailing_newline=True,
        # This environment only ever calls `.parse()`, so autoescape has no
        # effect on what it does. Set anyway rather than suppressed: bandit
        # B701 is a real finding class, and a `# nosec` here would be one more
        # comment asserting a control instead of applying one.
        autoescape=True,
    )


def _in_skipped_dir(path: Path, root: Path) -> bool:
    """Whether `path` sits in a cache directory INSIDE the render root.

    Matched against the path relative to the root, never the absolute one.
    Matching absolute components meant a checkout that happened to live under
    any directory named `.mypy_cache` — or `.git`, which a worktree layout can
    produce — skipped every file, and the gate printed OK over zero files
    (QA-4 round eleven).
    """
    return any(part in SKIP_DIRS for part in path.relative_to(root).parts)


def payload_files(root: Path) -> list[Path]:
    """Every file under the render root that Copier renders as text."""
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if _in_skipped_dir(path, root):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        found.append(path)
    return found


def _relative(path: Path) -> str:
    """The path as a reader would cite it — repo-relative when it is inside."""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def path_segments(root: Path) -> dict[str, Path]:
    """Every directory and file NAME under `root`, mapped to one path using it.

    Collected from the whole tree rather than from `payload_files`, and the
    difference is a hole rather than a nicety: a directory whose name is
    malformed and which holds only images has no parsed file under it, so
    deriving segments from the files would leave `assets/{@ bad @/logo.png`
    unreported while `copier copy` still dies on the directory.

    One entry per distinct name, so a templated directory holding twenty files
    is reported once instead of twenty times.
    """
    segments: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if _in_skipped_dir(path, root):
            continue
        for part in path.relative_to(root).parts:
            segments.setdefault(part, path)
    return segments


def parse_failures(root: Path, env: Environment) -> list[str]:
    """Every file body and path segment under `root` that is not a template."""
    failures: list[str] = []

    for path in payload_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable: Copier copies it verbatim
        try:
            env.parse(text)
        except TemplateSyntaxError as exc:
            failures.append(f"{_relative(path)}:{exc.lineno}: {exc.message}")

    for segment, example in sorted(path_segments(root).items()):
        try:
            env.parse(segment)
        except TemplateSyntaxError as exc:
            failures.append(f"{_relative(example)}: path segment {segment!r} does not parse: {exc.message}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "parse this tree instead of the one copier.yml declares. Exists so a test can prove this gate "
            "FAILS without breaking the payload every other test renders."
        ),
    )
    args = parser.parse_args()

    try:
        config = load_config()
        root = args.root if args.root is not None else render_root(config)
        env = environment(config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"[render-safety] SETUP ERROR — {exc}")
        return 2

    if not root.is_dir():
        print(f"[render-safety] SETUP ERROR — render root {_relative(root)} does not exist")
        return 2

    checked = len(payload_files(root))
    if checked == 0:
        # A render root with nothing in it has no unparseable file, so the
        # loop below would report OK. That is the answer to a question nobody
        # asked: the generator has no payload, or the skip rules swallowed it.
        print(f"[render-safety] SETUP ERROR — no payload file under {_relative(root)}; nothing was checked")
        return 2

    failures = parse_failures(root, env)

    if failures:
        print("[render-safety] FAILED\n")
        for failure in failures:
            print(f"  FAIL    {failure}")
        print(
            f"\n{len(failures)} finding(s) under {_relative(root)}, each of which aborts `copier copy`.\n"
            '`_templates_suffix: ""` makes every file a template, so this is not a file that renders\n'
            "oddly — it is a generator that produces nothing at all.\n\n"
            "Fix: wrap the literal text in `{% raw %}`…`{% endraw %}`, or write it so the delimiter\n"
            "never appears. Prose ABOUT Jinja tokens and bash's `${@}` / `${#array[@]}` are the two\n"
            "that reach these delimiters."
        )
        return 1

    print(f"[render-safety] OK — {checked} file(s) under {_relative(root)} parse as Copier templates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
