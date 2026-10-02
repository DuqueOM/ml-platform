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
        for name in re.findall(r"\b(_[a-z]+_probe[\w{}]*\.py)\b", source.read_text(encoding="utf-8"))
    }

    assert probes, "no probe names found — the pattern stopped matching, so this test checks nothing"
    unomitted = sorted(name for name in probes if not any(fnmatch.fnmatch(f"src/pkg/{name}", p) for p in omit))
    assert not unomitted, f"probe files coverage would record and then fail to find: {unomitted}"
