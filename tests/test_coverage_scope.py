"""Every tracked script is in the `scripts/` coverage report, executed or not.

QA-4 round fourteen: coverage discovers a file no test executed only inside a
package, and `scripts/datasets/` and `scripts/local/` have no `__init__.py`.
Two scripts — 315 statements — were therefore absent from the figure the floor
of 83 is set on, rather than counted at 0%. `include_namespace_packages` in
`[tool.coverage.report]` is the fix; this test is what keeps it, by asking
coverage itself which files it would report with nothing executed.

**It asks in a child process, with every `COVERAGE_*` variable removed.** The
first version built a `Coverage` object inside the test process. Under
`--cov`, that re-applied `[tool.coverage.run] patch = ["subprocess"]` and
pointed every later subprocess's data at this test's temporary file, so each
gate the suite runs as a subprocess afterwards went unmeasured: the
`scripts/` figure fell from about 84% to 51.86%, and `check_doc_coherence.py`
to 20%. Measuring coverage from inside a measured process is the mistake.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_REPORT = """
import json, sys
import coverage
cov = coverage.Coverage(source=[sys.argv[1] + "/scripts"], config_file=sys.argv[1] + "/pyproject.toml",
                        data_file=sys.argv[2] + "/.coverage")
cov.set_option("run:patch", [])
cov.start()
cov.stop()
cov.json_report(outfile=sys.argv[2] + "/coverage.json")
"""


def test_every_tracked_script_is_reported_even_when_nothing_ran_it(tmp_path: Path) -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "scripts/*.py"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert len(tracked) > 30, tracked  # the listing itself worked

    env = {k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")}
    subprocess.run(
        [sys.executable, "-c", _REPORT, str(REPO_ROOT), str(tmp_path)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        timeout=120,
    )
    files = json.loads((tmp_path / "coverage.json").read_text())["files"]
    reported = {str(Path(name).resolve().relative_to(REPO_ROOT)) for name in files}

    unreported = sorted(set(tracked) - reported)
    assert not unreported, f"tracked scripts coverage cannot see, so the scripts/ figure leaves them out: {unreported}"


def test_every_python_probe_the_tests_write_is_omitted_from_measurement() -> None:
    """A probe recorded by coverage and deleted before the report fails the report.

    The gate tests write short-lived files into source directories. Coverage
    adds every unexecuted file under `--source` to its data when a measured
    process exits, so a probe that exists at that instant is recorded, and the
    floors gate then dies on `No source for code` — depending on which test
    happened to finish while another's probe existed. The names are read from
    the tests themselves, so a new probe name cannot reopen the race unseen.
    """
    import fnmatch
    import re
    import tomllib

    omit = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["coverage"]["run"]["omit"]
    sources = [
        *(REPO_ROOT / "tests").glob("*.py"),
        *REPO_ROOT.glob("libs/*/tests/*.py"),
        *REPO_ROOT.glob("projects/*/tests/*.py"),
    ]
    probes = {
        name
        for source in sources
        # Any underscore-prefixed module with "probe" in its name, not only
        # `_<word>_probe`: a bare `_probe` module, which
        # `test_dependency_direction.py` wrote into `ml_core` and
        # `demand_forecast`, matched neither this pattern nor the omit list
        # (QA-4 round fifteen). That test now writes `_gate_probe` like the rest.
        for name in re.findall(r"(?<![\w.])(_\w*?probe[\w{}]*\.py)\b", source.read_text(encoding="utf-8"))
    }

    assert probes, "no probe names found — the pattern stopped matching, so this test checks nothing"
    unomitted = sorted(name for name in probes if not any(fnmatch.fnmatch(f"src/pkg/{name}", p) for p in omit))
    assert not unomitted, f"probe files coverage would record and then fail to find: {unomitted}"


def test_the_omit_list_drops_the_test_suites_and_nothing_inside_a_package() -> None:
    """Every distribution's own suite is omitted; no module under `src/` is.

    The list said `*/tests/*`, which also omitted a `tests/` directory inside an
    import package — `src/serving_core/tests/engine.py` is importable code, and
    it was never measured (QA-4 round sixteen). Read with coverage's own
    matcher, because its glob is not fnmatch's: `*` stops at a `/`.
    """
    import tomllib

    from coverage.files import GlobMatcher, prep_patterns

    omit = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["coverage"]["run"]["omit"]
    matcher = GlobMatcher(prep_patterns(omit), "omit")
    tracked = subprocess.run(
        ["git", "ls-files", "libs", "projects"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()

    modules = [path.split("/") for path in tracked if path.endswith(".py") and path.count("/") >= 3]
    suites = ["/".join(parts) for parts in modules if parts[2] == "tests"]
    package_code = ["/".join(parts) for parts in modules if parts[2] == "src"]
    assert suites, "no test suite found; the layout this test reads has changed"
    assert package_code, "no package module found; the layout this test reads has changed"

    measured_suites = sorted(path for path in suites if not matcher.match(str(REPO_ROOT / path)))
    assert not measured_suites, f"test suites coverage would measure as if they were code: {measured_suites}"
    omitted_code = sorted(path for path in package_code if matcher.match(str(REPO_ROOT / path)))
    assert not omitted_code, f"package modules coverage would never measure: {omitted_code}"
    for planted in ("libs/serving-core/src/serving_core/tests/engine.py", "projects/x/src/x/tests/model.py"):
        assert not matcher.match(str(REPO_ROOT / planted)), f"{planted} is importable code, and it is omitted"
