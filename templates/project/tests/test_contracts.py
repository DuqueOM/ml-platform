"""Contract tests for {@ project_name @}.

Every test here states the regression it catches. A test whose answer to
"what would this catch?" is "nothing specific" is coverage theatre — delete it
or replace it (ADR-005 rule J).

Each new test must be verified to FAIL without the change it covers. That step
is the one most often skipped, because the test passes and passing feels like
success.
"""

from __future__ import annotations

import {@ project_slug @}


def test_package_declares_a_version() -> None:
    """A package with no version cannot be pinned by a consumer.

    Failure looks like: a dependent project pins this one and gets a moving
    target, so a reproducible build stops being reproducible.
    """
    assert {@ project_slug @}.__version__
