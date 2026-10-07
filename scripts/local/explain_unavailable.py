#!/usr/bin/env python3
"""Name the local-stack deployments that are NOT available, and why — run when `make local-up` times out.

`kubectl wait --for=condition=available deployment --all` shares one timeout
across every deployment and, when it expires, reports EACH one it had not yet
confirmed as "timed out". QA-4 round eighteen: five components were Available
and Grafana alone was OOMKilled, and the message named all six — pointing
whoever read it at the five that were fine.

This lists only the deployments with no available replica, with each pod's
waiting reason or last termination reason (OOMKilled, CrashLoopBackOff,
ImagePullBackOff…), so the first line read is the cause.

    uv run python scripts/local/explain_unavailable.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

CONTEXT = "kind-ml-platform-local"
NAMESPACE = "ml-platform"


def _kubectl(*args: str) -> dict[str, Any]:
    done = subprocess.run(
        ["kubectl", "--context", CONTEXT, "-n", NAMESPACE, *args, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip())
    return json.loads(done.stdout)  # type: ignore[no-any-return]


def unavailable(deployments: dict[str, Any], pods: dict[str, Any]) -> list[str]:
    """One line per deployment without an available replica, naming its pods' reasons."""
    lines = []
    for deployment in deployments["items"]:
        if deployment.get("status", {}).get("availableReplicas", 0):
            continue
        name = deployment["metadata"]["name"]
        selector = deployment["spec"]["selector"].get("matchLabels", {})
        reasons = []
        for pod in pods["items"]:
            labels = pod["metadata"].get("labels", {})
            if any(labels.get(key) != value for key, value in selector.items()):
                continue
            for status in pod.get("status", {}).get("containerStatuses", []):
                waiting = (status.get("state") or {}).get("waiting") or {}
                last = (status.get("lastState") or {}).get("terminated") or {}
                reason = waiting.get("reason") or last.get("reason") or "not ready"
                if last.get("reason") and last.get("reason") != reason:
                    reason = f"{reason} (last: {last['reason']})"
                reasons.append(f"{status['name']}: {reason}, restarts {status.get('restartCount', 0)}")
            if not pod.get("status", {}).get("containerStatuses"):
                reasons.append(f"pod {pod['status'].get('phase', 'Unknown')}")
        lines.append(f"{name}: " + ("; ".join(reasons) if reasons else "no pod"))
    return lines


def main() -> int:
    lines = unavailable(_kubectl("get", "deployments"), _kubectl("get", "pods"))
    if not lines:
        print("[local-up] every deployment is available")
        return 0
    print("[local-up] NOT available:")
    for line in lines:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
