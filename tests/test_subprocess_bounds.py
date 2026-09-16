"""Every subprocess a gate script starts is bounded, and the bound actually ends the process.

QA-4 round eleven: one of 25 subprocess calls in `scripts/` carried a timeout.
A gate waiting on a wedged git or a hung verification command does not fail;
it holds the CI job until the runner's own limit, and reports nothing about
why.

Checked from the AST, so a new call without a bound is a red test rather than
a finding for the next audit.
"""

from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SHORT = {"run", "check_output", "check_call", "call"}


def _subprocess_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr in _SHORT | {"Popen"}
    ]


def test_there_are_calls_to_check() -> None:
    """An empty walk would pass everything below."""
    count = sum(
        len(_subprocess_calls(ast.parse(f.read_text(encoding="utf-8")))) for f in (REPO_ROOT / "scripts").rglob("*.py")
    )
    assert count >= 20, f"only {count} subprocess calls found — the walk broke, not the scripts"


def test_no_script_imports_subprocess_functions_by_name() -> None:
    """`from subprocess import run` would hide a call from the check below."""
    offenders = [
        f"{f.relative_to(REPO_ROOT)}:{node.lineno}"
        for f in sorted((REPO_ROOT / "scripts").rglob("*.py"))
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess"
    ]
    assert not offenders, offenders


def test_every_subprocess_call_in_scripts_is_bounded() -> None:
    """`run`-style calls need `timeout=`; a `Popen` needs its own session and a bounded `communicate`."""
    offenders = []
    for path in sorted((REPO_ROOT / "scripts").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for call in _subprocess_calls(tree):
            where = f"{path.relative_to(REPO_ROOT)}:{call.lineno}"
            keywords = {k.arg: k.value for k in call.keywords}
            if call.func.attr in _SHORT:  # type: ignore[attr-defined]
                if "timeout" not in keywords:
                    offenders.append(f"{where} subprocess.{call.func.attr}() has no timeout")  # type: ignore[attr-defined]
                continue
            session = keywords.get("start_new_session")
            if not (isinstance(session, ast.Constant) and session.value is True):
                offenders.append(f"{where} Popen without start_new_session=True cannot kill its children")
            enclosing = next((f for f in functions if f.lineno <= call.lineno <= (f.end_lineno or 0)), None)
            bounded = enclosing is not None and any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "communicate"
                and any(k.arg == "timeout" for k in n.keywords)
                for n in ast.walk(enclosing)
            )
            if not bounded:
                offenders.append(f"{where} Popen whose communicate() has no timeout")
    assert not offenders, "\n".join(offenders)


def _alive(pid: int) -> bool:
    """True for a running process; a zombie awaiting its parent does not count."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    return not stat.is_file() or stat.read_text(encoding="utf-8").split()[2] != "Z"


def _reap(pid: int) -> None:
    if _alive(pid):
        os.kill(pid, signal.SIGKILL)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")
def test_a_timed_out_verification_leaves_no_process_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The reason `_verify` kills a process group, demonstrated rather than asserted.

    The command backgrounds a grandchild and waits on it, the shape of a shell
    running `uv run pytest`. The grandchild writes its PID so survival can be
    checked directly.

    The contrast is the point. `subprocess.run(shell=True, timeout=)` returns
    on time — it does not hang, which the first version of `_verify`'s comment
    wrongly claimed — but it kills only the shell, and the grandchild keeps
    running. Here that orphan would be a pytest session still writing probes
    into the repository after the document recorded it as timed out.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import check_implementation_status as status

    naive = tmp_path / "naive.pid"
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(f"sleep 30 & echo $! > {naive}; wait", shell=True, capture_output=True, text=True, timeout=1)
    time.sleep(0.3)
    orphan = int(naive.read_text(encoding="utf-8"))
    try:
        assert _alive(orphan), (
            "subprocess.run no longer orphans a shell's grandchild; the process group may be unnecessary"
        )
    finally:
        _reap(orphan)

    bounded = tmp_path / "bounded.pid"
    command = f"sleep 30 & echo $! > {bounded}; wait"
    monkeypatch.setattr(status, "VERIFY_TIMEOUT_SECONDS", 1)
    started = time.monotonic()
    try:
        assert status._verify(command) is False
        elapsed = time.monotonic() - started
        assert "TIMED OUT" in status._FAILURES.pop(command)
        assert elapsed < 10, f"_verify took {elapsed:.1f}s against a 1s bound"
        time.sleep(0.3)
        grandchild = int(bounded.read_text(encoding="utf-8"))
        survived = _alive(grandchild)
        _reap(grandchild)
        assert not survived, "the grandchild outlived _verify's timeout"
    finally:
        status._FAILURES.pop(command, None)
