#!/usr/bin/env python3
"""Routing evaluation runner — measures routing accuracy and gate adherence.

Usage:
    python evals/run.py 01_intent.jsonl [--usecase tienda]

The set path is resolved relative to ``usecases/<usecase>/evals/sets/``.

Output:
    - Prints accuracy and failing cases to stdout
    - Saves a JSON report to evals/reports/<timestamp>_<set_name>.json

Gate (plan §F0.3): intent accuracy must be >= GATE_INTENT_RATIO. The gate is
a RATIO, not an absolute count (AUDIT R8-07) — a 20-case set needs 18
correct, a 40-case set needs 36, and the bar cannot silently dilute as sets
grow.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make the repo root importable (core/, usecases/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import load_usecase  # noqa: E402
from core.router import Router  # noqa: E402

GATE_INTENT_RATIO = 0.90

_ROUTER: Router | None = None


def route(text: str):
    """Route a message using the module-level router (built in ``__main__``)."""
    assert _ROUTER is not None, "router not initialised — run as a script"
    return _ROUTER.route(text)


def _p95(latencies: list[int]) -> float:
    """Nearest-rank p95 with an index clamp (AUDIT R8-07: no off-by-one)."""
    if not latencies:
        return 0.0
    ordered = sorted(latencies)
    idx = min(int(len(ordered) * 0.95), len(ordered) - 1)
    return float(ordered[idx])


def run_intent_eval(jsonl_path: Path) -> dict:
    """Run the routing evaluation over one JSONL case set.

    Args:
        jsonl_path: Path to the JSONL file with test cases.

    Returns:
        Dict with accuracies, failures, latencies and gate result.
    """
    cases = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))

    results: dict = {
        "total": len(cases),
        "correct_intent": 0,
        "correct_tier": 0,
        "correct_finality": 0,
        "failures": [],
        "latencies_ms": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "set_name": jsonl_path.stem,
    }

    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] Testing: {case['input'][:50]}...")

        try:
            start = time.time()
            result = route(case["input"])
            latency_ms = int((time.time() - start) * 1000)
            results["latencies_ms"].append(latency_ms)

            intent_match = result.intent == case["expected_intent"]
            if intent_match:
                results["correct_intent"] += 1

            tier_match = result.tier == case["expected_tier"]
            if tier_match:
                results["correct_tier"] += 1

            finality_match = result.finality == case["expected_finality"]
            if finality_match:
                results["correct_finality"] += 1

            if not (intent_match and tier_match and finality_match):
                results["failures"].append(
                    {
                        "case_index": i,
                        "input": case["input"],
                        "expected": {
                            "intent": case["expected_intent"],
                            "tier": case["expected_tier"],
                            "finality": case["expected_finality"],
                        },
                        "actual": {
                            "intent": result.intent,
                            "tier": result.tier,
                            "finality": result.finality,
                            "confidence": result.confidence,
                        },
                        "note": case.get("note", ""),
                    }
                )

            print(f"  ✓ Intent: {result.intent} ({'✓' if intent_match else '✗'})")
            print(f"  ✓ Tier: {result.tier} ({'✓' if tier_match else '✗'})")
            print(f"  ✓ Finality: {result.finality} ({'✓' if finality_match else '✗'})")
            print(f"  ⏱ {latency_ms}ms\n")

        except Exception as e:
            print(f"  ✗ ERROR: {e}\n")
            results["failures"].append({"case_index": i, "input": case["input"], "error": str(e)})

    results["accuracy_intent"] = results["correct_intent"] / results["total"]
    results["accuracy_tier"] = results["correct_tier"] / results["total"]
    results["accuracy_finality"] = results["correct_finality"] / results["total"]
    results["avg_latency_ms"] = (
        sum(results["latencies_ms"]) / len(results["latencies_ms"]) if results["latencies_ms"] else 0
    )
    results["p95_latency_ms"] = _p95(results["latencies_ms"])
    results["gate_intent_ratio"] = GATE_INTENT_RATIO
    results["gate_passed"] = results["accuracy_intent"] >= GATE_INTENT_RATIO

    return results


def print_summary(results: dict) -> None:
    """Print a human-readable summary of one eval run."""
    print("\n" + "=" * 60)
    print(f"EVAL RESULTS: {results['set_name']}")
    print("=" * 60)
    print(f"Total cases: {results['total']}")
    print(f"Intent accuracy: {results['accuracy_intent']:.1%} ({results['correct_intent']}/{results['total']})")
    print(f"Tier accuracy: {results['accuracy_tier']:.1%} ({results['correct_tier']}/{results['total']})")
    print(
        f"Finality accuracy: {results['accuracy_finality']:.1%} " f"({results['correct_finality']}/{results['total']})"
    )
    print(f"Avg latency: {results['avg_latency_ms']:.0f}ms")
    print(f"P95 latency: {results['p95_latency_ms']:.0f}ms")

    # Gate F0.3 — ratio-based (AUDIT R8-07), so the bar scales with set size.
    print(
        f"\nGATE (intent accuracy >= {results['gate_intent_ratio']:.0%}): "
        f"{'✅ PASSED' if results['gate_passed'] else '❌ FAILED'}"
    )

    if results["failures"]:
        print(f"\n{len(results['failures'])} failures:")
        for fail in results["failures"][:5]:  # show the first 5 only
            print(f"  - Case {fail['case_index']}: {fail['input'][:40]}")
            if "expected" in fail:
                print(f"    Expected: {fail['expected']['intent']} (tier {fail['expected']['tier']})")
                print(
                    f"    Got: {fail['actual']['intent']} "
                    f"(tier {fail['actual']['tier']}, conf={fail['actual']['confidence']:.2f})"
                )

    print("=" * 60)


def save_report(results: dict, reports_dir: Path) -> None:
    """Persist the JSON report under ``evals/reports/``."""
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{results['set_name']}.json"
    report_path = reports_dir / filename

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python evals/run.py <jsonl_file>")
        print("Example: python evals/run.py sets/01_intent.jsonl")
        sys.exit(1)

    # Optional --usecase flag (default: tienda).
    usecase = "tienda"
    args = sys.argv[1:]
    if "--usecase" in args:
        idx = args.index("--usecase")
        usecase = args[idx + 1]
        args = args[:idx] + args[idx + 2 :]

    set_arg = args[0]
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        Path(set_arg),
        repo_root / "usecases" / usecase / "evals" / "sets" / set_arg,
        repo_root / "usecases" / usecase / "evals" / set_arg,
    ]
    jsonl_path = next((p for p in candidates if p.exists()), None)
    if jsonl_path is None:
        print(f"Error: {set_arg} not found (use-case: {usecase})")
        sys.exit(1)

    _ROUTER = Router(load_usecase(usecase))
    print(f"Running eval: {jsonl_path.name} (use-case: {usecase})\n")

    results = run_intent_eval(jsonl_path)
    print_summary(results)

    reports_dir = Path(__file__).parent / "reports"
    save_report(results, reports_dir)

    sys.exit(0 if results["gate_passed"] else 1)
