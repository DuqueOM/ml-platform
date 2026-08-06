#!/usr/bin/env python3
"""Refuse to start the local stack when it does not fit in measured memory.

The failure this prevents is specific and expensive: a stack that overcommits
memory does not fail at start. It runs, degrades, and is eventually resolved by
the OOM killer choosing a victim — usually the IDE, rarely the culprit. The
symptom appears minutes later and points at the wrong component.

So the budget is declared (``platform/local/budget.yaml``), summed, and checked
against **measured** available memory before anything is created.

Memory is sampled repeatedly rather than read once. A single reading of a
fluctuating quantity is an anecdote; this project has already been burned by
treating one as a measurement.

    python scripts/local/preflight.py
    python scripts/local/preflight.py --samples 10 --interval 2
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUDGET = REPO_ROOT / "platform" / "local" / "budget.yaml"

REQUIRED_TOOLS = ("docker", "kind", "kubectl")
CLUSTER_NAME = "ml-platform-local"


def cluster_exists() -> bool:
    """True when the local cluster is already created."""
    result = subprocess.run(["kind", "get", "clusters"], capture_output=True, text=True)
    return result.returncode == 0 and CLUSTER_NAME in result.stdout.split()


def _available_mb() -> int:
    """Available memory in MB, from /proc/meminfo.

    ``MemAvailable`` rather than ``MemFree``: free memory excludes reclaimable
    page cache and would understate what a new workload can actually use.
    """
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    raise RuntimeError("MemAvailable not present in /proc/meminfo")


def sample_available(count: int, interval: float) -> tuple[int, int, int]:
    """Sample available memory. Returns (minimum, mean, maximum) in MB.

    The **minimum** is what the budget is checked against. Budgeting against
    the mean means the stack fits on average and fails at the moment something
    else on the machine is busy — which is exactly when it will be running.
    """
    samples: list[int] = []
    for index in range(count):
        samples.append(_available_mb())
        if index < count - 1:
            time.sleep(interval)
    return min(samples), sum(samples) // len(samples), max(samples)


def occupied_ports(ports: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """Host ports already bound.

    Checked BEFORE cluster creation because the alternative is a collision
    discovered after the node image is pulled, reported as a Docker error that
    names the port and not the cause. On WSL the holder is often a Windows
    process invisible to `ss`, so the message says which service wanted it
    rather than pretending to identify the owner.
    """
    taken: list[tuple[int, str]] = []
    for entry in ports:
        port = int(entry["port"])
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                taken.append((port, str(entry["service"])))
    return taken


def check_tools() -> list[str]:
    return [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]


def docker_running() -> bool:
    result = subprocess.run(["docker", "info"], capture_output=True, text=True)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--samples", type=int, default=5, help="memory samples to take (default 5)")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between samples (default 2)")
    args = parser.parse_args()

    print("[preflight] local validation stack\n")

    missing = check_tools()
    if missing:
        print(f"  FAIL  missing required tools: {', '.join(missing)}")
        return 1
    print(f"  ok    tools present: {', '.join(REQUIRED_TOOLS)}")

    if not docker_running():
        print("  FAIL  docker is installed but not responding — is the daemon running?")
        return 1
    print("  ok    docker daemon responding")

    if not BUDGET.is_file():
        print(f"  FAIL  missing {BUDGET.relative_to(REPO_ROOT)}")
        return 1

    budget = yaml.safe_load(BUDGET.read_text(encoding="utf-8"))
    components = budget["components"]
    required_mb = sum(int(component["limit_mb"]) for component in components)
    utilisation = float(budget["max_utilisation"])

    print(f"\n  sampling available memory ({args.samples}x, {args.interval}s apart)…")
    low, mean, high = sample_available(args.samples, args.interval)
    spread = high - low
    print(f"  ok    available: min {low} MB · mean {mean} MB · max {high} MB (spread {spread} MB)")
    if spread > low * 0.25:
        print("  note  memory is fluctuating widely; the minimum is what the budget is checked against")

    allowed_mb = int(low * utilisation)
    print(f"\n  budget declared : {required_mb} MB across {len(components)} components")
    print(f"  budget allowed  : {allowed_mb} MB ({utilisation:.0%} of {low} MB minimum available)")

    if required_mb > allowed_mb:
        print("\n[preflight] FAILED — the stack does not fit\n")
        for component in sorted(components, key=lambda c: -int(c["limit_mb"])):
            print(f"  {int(component['limit_mb']):>5} MB  {component['name']}")
        deficit = required_mb - allowed_mb
        print(
            f"\n  Short by {deficit} MB. Options, in order of preference:\n"
            "    1. Free memory on the host (close a browser, stop other containers).\n"
            "    2. Raise the WSL2 allocation in .wslconfig, then `wsl --shutdown`.\n"
            "    3. Lower a component's limit in platform/local/budget.yaml — but\n"
            "       re-measure afterwards rather than assuming it still works.\n"
            "  Do NOT raise max_utilisation to make this pass: the headroom is for\n"
            "  the IDE and browser that will be running alongside the stack."
        )
        return 1

    ports = budget.get("host_ports") or []
    if ports and cluster_exists():
        # The stack is already up, so it is holding its own ports. Reporting
        # that as a collision would make preflight fail precisely because it
        # previously succeeded.
        print(f"  ok    cluster {CLUSTER_NAME} already exists — port check not applicable")
    elif ports:
        taken = occupied_ports(ports)
        if taken:
            print("\n[preflight] FAILED — host ports already in use\n")
            for port, service in taken:
                print(f"  {port}  wanted by {service}")
            print(
                "\n  Free the port, or change it in platform/local/budget.yaml AND"
                "\n  platform/local/kind-cluster.yaml — the two must agree."
                "\n  On WSL the holder is often a Windows process that `ss` cannot see."
            )
            return 1
        print(f"  ok    {len(ports)} host port(s) free")

    headroom = allowed_mb - required_mb
    print(f"\n[preflight] OK — fits with {headroom} MB of headroom inside the allowance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
