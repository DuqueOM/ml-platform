#!/usr/bin/env python3
"""Dashboards ship by directory, so the directory is the unit that needs checking.

`make local-dashboards` runs `kubectl create configmap grafana-dashboards
--from-file=platform/observability/dashboards/`. Every file in that directory is
provisioned, whatever it is, and `allowUiUpdates: false` means Grafana will not
argue. Dropping a file there is a deploy.

`tests/test_dashboards_structure.py` already checks each dashboard on its own —
valid JSON, a uid, panels that name a datasource provisioning actually creates.
What a per-file test cannot see is the properties that only exist BETWEEN files,
and those are the ones that fail silently:

* **Two dashboards with the same uid.** Grafana keys on uid, not on filename.
  The second file provisioned replaces the first, in whatever order the ConfigMap
  happens to enumerate. Nothing errors, nothing logs, and the dashboard someone
  bookmarked now shows a different service's panels. The existing structural test
  asserts each dashboard HAS a uid and could never assert they DIFFER, because it
  is parametrised one file at a time.

* **Two dashboards with the same title.** Both provision, both appear in the
  picker, indistinguishable. The person on call opens whichever sorts first.

* **A file in that directory that is not a dashboard.** An editor backup, a
  partial export, a `.json` fixture someone parked there — all provisioned, and
  a malformed one takes the whole ConfigMap key with it.

* **A dashboard nobody registered.** Upstream `ml-service-template` states this
  as the point of its own inventory check: make "shipped" and "registered" the
  same word. The register here is `platform/observability/README.md`, which is
  where a dashboard's purpose and its intended reader are written down. A panel
  is a decision aid; one whose reason nobody recorded is a graph.

**`services/*/monitoring/grafana/` is reported and never failed on.** That tree
is generated from ml-service-template and is byte-identical to what the template
produces (ADR-003); editing it here is a fork with extra steps. Its dashboards
are also not provisioned by anything in this repository — `local-dashboards`
names only the platform directory. Reporting them keeps that absence a recorded
fact instead of something a reader has to rediscover, which is the same
convention check C9 uses for upstream defects.

    uv run python scripts/check_dashboard_inventory.py
    uv run python scripts/check_dashboard_inventory.py --dir <other> --register <other>/README.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The directory `make local-dashboards` provisions wholesale.
PROVISIONED_DIR = REPO_ROOT / "platform" / "observability" / "dashboards"

#: Where a provisioned dashboard's purpose and reader are recorded.
REGISTER = REPO_ROOT / "platform" / "observability" / "README.md"

#: Generated from ml-service-template, owned upstream, provisioned by nothing here.
UPSTREAM_GLOB = "services/*/monitoring/grafana/*.json"

failures: list[str] = []
notes: list[str] = []


def fail(message: str) -> None:
    """Record a finding. Every finding fails the run."""
    failures.append(message)


def ok(message: str) -> None:
    """Record what was examined, printed whether or not the run passed.

    Anti-pattern P-20: a gate that does not say what it looked at is
    indistinguishable from one whose filter matched nothing.
    """
    notes.append(message)


def _dashboard_body(document: object) -> dict[str, object] | None:
    """Unwrap the two shapes a Grafana dashboard export takes.

    A bare export is the dashboard object. An API-style export nests it under
    `dashboard`, alongside metadata such as `folderId`. Both are provisioned
    identically, so a check that understood only one would silently skip half
    the tree — the shape of failure this script exists to catch.
    """
    if not isinstance(document, dict):
        return None
    nested = document.get("dashboard")
    if isinstance(nested, dict):
        return nested
    return document


def _display(path: Path) -> str:
    """A path as a reader would cite it: repo-relative where that is meaningful."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def check_provisioned(directory: Path, register_path: Path) -> None:
    """The directory that ships, and the invariants that live between its files."""
    if not directory.is_dir():
        fail(f"missing {_display(directory)} — nothing would be provisioned")
        return

    files = sorted(path for path in directory.iterdir() if path.is_file())
    if not files:
        fail(
            f"{_display(directory)} is empty. Every check below would pass over "
            f"nothing, which is the pass-because-absent shape (P-09) rather than a green dashboard set"
        )
        return

    register = register_path.read_text(encoding="utf-8") if register_path.is_file() else ""
    if not register:
        fail(f"missing {_display(register_path)} — there is nowhere for a dashboard to be registered")

    uids: dict[str, str] = {}
    titles: dict[str, str] = {}
    for path in files:
        name = path.name
        if path.suffix != ".json":
            fail(
                f"{name} is in the provisioned directory and is not JSON. `--from-file` ships the whole "
                f"directory, so this reaches Grafana as a dashboard whatever it actually is"
            )
            continue

        try:
            body = _dashboard_body(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as error:
            fail(f"{name}: not valid JSON — {error}. A malformed file breaks the ConfigMap key it lands in")
            continue
        if body is None:
            fail(f"{name}: top level is not a JSON object, so it is not a dashboard")
            continue

        uid = body.get("uid")
        title = body.get("title")
        if not uid:
            fail(f"{name}: no uid. Every sync creates a NEW dashboard, and saved links point at the last copy")
        elif not isinstance(uid, str):
            fail(f"{name}: uid is {type(uid).__name__}, not a string")
        elif uid in uids:
            fail(
                f"{name} and {uids[uid]} both claim uid {uid!r}. Grafana keys on uid, so one silently "
                f"replaces the other in whatever order the ConfigMap enumerates — no error, no log, and "
                f"the bookmarked dashboard now shows the wrong panels"
            )
        else:
            uids[uid] = name

        if not title:
            fail(f"{name}: no title, so it is unnamed in the dashboard picker")
        elif not isinstance(title, str):
            fail(f"{name}: title is {type(title).__name__}, not a string")
        elif title in titles:
            fail(
                f"{name} and {titles[title]} share the title {title!r}. Both provision and both appear "
                f"in the picker; whoever is on call opens whichever sorts first"
            )
        else:
            titles[title] = name

        if register and name not in register:
            fail(
                f"{name} is provisioned and is not named in {_display(register_path)}. "
                f"Shipped and registered have to be the same word, or a panel's reason lives only in "
                f"the head of whoever added it"
            )

    for referenced in sorted({word.strip("`,.()") for word in register.split()}):
        if not referenced.endswith(".json") or "/" in referenced:
            continue
        if not (directory / referenced).is_file():
            fail(
                f"{_display(register_path)} registers {referenced}, which is not in the provisioned "
                f"directory. The register describes a dashboard nobody would see"
            )

    ok(f"provisioned: {len(files)} file(s) in {_display(directory)}, {len(uids)} distinct uid(s)")


def report_upstream_owned() -> None:
    """Dashboards this repository holds but neither provisions nor may edit."""
    upstream = sorted(REPO_ROOT.glob(UPSTREAM_GLOB))
    if not upstream:
        ok("upstream-owned: none present under services/")
        return
    without_uid = []
    for path in upstream:
        try:
            body = _dashboard_body(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
        if body is not None and not body.get("uid"):
            without_uid.append(path.name)
    ok(
        f"upstream-owned: {len(upstream)} dashboard(s) under services/, provisioned by nothing here and "
        f"not editable here (ADR-003); {len(without_uid)} carry no uid, which is upstream's to fix"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=PROVISIONED_DIR, help="the directory that is provisioned wholesale")
    parser.add_argument("--register", type=Path, default=REGISTER, help="the document naming each provisioned file")
    args = parser.parse_args(argv)

    check_provisioned(args.dir, args.register)
    report_upstream_owned()

    for note in notes:
        print(f"  ok   [dashboards] {note}")
    for failure in failures:
        print(f"  FAIL [dashboards] {failure}")

    if failures:
        print(f"\n[dashboards] FAILED — {len(failures)} finding(s)")
        return 1
    print("\n[dashboards] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
