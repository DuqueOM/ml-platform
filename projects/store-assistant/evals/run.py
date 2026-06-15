#!/usr/bin/env python3
"""
Runner de evaluaciones — mide accuracy de routing y adherencia a gates.

Usage:
    python evals/run.py sets/01_intent.jsonl

Output:
    - Imprime accuracy y casos fallidos a stdout
    - Guarda reporte JSON en evals/reports/<timestamp>_<set_name>.json
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# Añadir app/ al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.router import route

def run_intent_eval(jsonl_path: Path) -> dict:
    """Ejecuta evaluación de routing.
    
    Args:
        jsonl_path: Ruta al archivo JSONL con casos de prueba
    
    Returns:
        Dict con accuracy, fallos, latencias, etc.
    """
    cases = []
    with open(jsonl_path) as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    
    results = {
        "total": len(cases),
        "correct_intent": 0,
        "correct_tier": 0,
        "correct_finality": 0,
        "failures": [],
        "latencies_ms": [],
        "timestamp": datetime.utcnow().isoformat(),
        "set_name": jsonl_path.stem
    }
    
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] Testing: {case['input'][:50]}...")
        
        try:
            start = time.time()
            result = route(case['input'])
            latency_ms = int((time.time() - start) * 1000)
            results["latencies_ms"].append(latency_ms)
            
            # Verificar intent
            intent_match = result.intent == case["expected_intent"]
            if intent_match:
                results["correct_intent"] += 1
            
            # Verificar tier
            tier_match = result.tier == case["expected_tier"]
            if tier_match:
                results["correct_tier"] += 1
            
            # Verificar finality
            finality_match = result.finality == case["expected_finality"]
            if finality_match:
                results["correct_finality"] += 1
            
            # Si algo falló, registrar
            if not (intent_match and tier_match and finality_match):
                results["failures"].append({
                    "case_index": i,
                    "input": case["input"],
                    "expected": {
                        "intent": case["expected_intent"],
                        "tier": case["expected_tier"],
                        "finality": case["expected_finality"]
                    },
                    "actual": {
                        "intent": result.intent,
                        "tier": result.tier,
                        "finality": result.finality,
                        "confidence": result.confidence
                    },
                    "note": case.get("note", "")
                })
            
            print(f"  ✓ Intent: {result.intent} ({'✓' if intent_match else '✗'})")
            print(f"  ✓ Tier: {result.tier} ({'✓' if tier_match else '✗'})")
            print(f"  ✓ Finality: {result.finality} ({'✓' if finality_match else '✗'})")
            print(f"  ⏱ {latency_ms}ms\n")
        
        except Exception as e:
            print(f"  ✗ ERROR: {e}\n")
            results["failures"].append({
                "case_index": i,
                "input": case["input"],
                "error": str(e)
            })
    
    # Calcular accuracies
    results["accuracy_intent"] = results["correct_intent"] / results["total"]
    results["accuracy_tier"] = results["correct_tier"] / results["total"]
    results["accuracy_finality"] = results["correct_finality"] / results["total"]
    results["avg_latency_ms"] = sum(results["latencies_ms"]) / len(results["latencies_ms"]) if results["latencies_ms"] else 0
    results["p95_latency_ms"] = sorted(results["latencies_ms"])[int(len(results["latencies_ms"]) * 0.95)] if results["latencies_ms"] else 0
    
    return results

def print_summary(results: dict):
    """Imprime resumen de resultados."""
    print("\n" + "="*60)
    print(f"EVAL RESULTS: {results['set_name']}")
    print("="*60)
    print(f"Total cases: {results['total']}")
    print(f"Intent accuracy: {results['accuracy_intent']:.1%} ({results['correct_intent']}/{results['total']})")
    print(f"Tier accuracy: {results['accuracy_tier']:.1%} ({results['correct_tier']}/{results['total']})")
    print(f"Finality accuracy: {results['accuracy_finality']:.1%} ({results['correct_finality']}/{results['total']})")
    print(f"Avg latency: {results['avg_latency_ms']:.0f}ms")
    print(f"P95 latency: {results['p95_latency_ms']:.0f}ms")
    
    # Gate F0.3: E4B debe pasar ≥18/20 en intent
    gate_passed = results['correct_intent'] >= 18
    print(f"\nGATE (≥18/20 intent correct): {'✅ PASSED' if gate_passed else '❌ FAILED'}")
    
    if results["failures"]:
        print(f"\n{len(results['failures'])} failures:")
        for fail in results["failures"][:5]:  # Mostrar solo primeros 5
            print(f"  - Case {fail['case_index']}: {fail['input'][:40]}")
            if 'expected' in fail:
                print(f"    Expected: {fail['expected']['intent']} (tier {fail['expected']['tier']})")
                print(f"    Got: {fail['actual']['intent']} (tier {fail['actual']['tier']}, conf={fail['actual']['confidence']:.2f})")
    
    print("="*60)

def save_report(results: dict, reports_dir: Path):
    """Guarda reporte JSON."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{results['set_name']}.json"
    report_path = reports_dir / filename
    
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nReport saved: {report_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python evals/run.py <jsonl_file>")
        print("Example: python evals/run.py sets/01_intent.jsonl")
        sys.exit(1)
    
    jsonl_path = Path(sys.argv[1])
    if not jsonl_path.exists():
        # Probar ruta relativa desde evals/
        jsonl_path = Path(__file__).parent / sys.argv[1]
        if not jsonl_path.exists():
            print(f"Error: {sys.argv[1]} not found")
            sys.exit(1)
    
    print(f"Running eval: {jsonl_path.name}\n")
    
    results = run_intent_eval(jsonl_path)
    print_summary(results)
    
    reports_dir = Path(__file__).parent / "reports"
    save_report(results, reports_dir)
