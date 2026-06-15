#!/usr/bin/env bash
# Quickstart script — inicia E4B router + ejecuta tests de validación F1
set -euo pipefail

echo "=== Agent-Local Quickstart (Fase 1 Validation) ==="
echo ""

# 1. Verificar que llama.cpp está compilado
if [[ ! -f ~/tools/llama.cpp/build/bin/llama-server ]]; then
    echo "❌ ERROR: llama-server not found"
    echo "   Run F0.1 first: compile llama.cpp with CUDA"
    exit 1
fi

# 2. Verificar modelo E4B
if [[ ! -f ~/ml-models/gemma-4-E4B-it-Q4_K_M.gguf ]]; then
    echo "❌ ERROR: E4B model not found at ~/ml-models/gemma-4-E4B-it-Q4_K_M.gguf"
    exit 1
fi

# 3. Verificar venv
if [[ ! -d .venv ]]; then
    echo "⚠️  Virtual environment not found, creating..."
    python3 -m venv .venv
    .venv/bin/pip install -q fastapi uvicorn httpx pydantic pytest rank-bm25 pyyaml
fi

echo "✅ Prerequisites OK"
echo ""

# 4. Iniciar E4B server (Tier 0)
echo "🚀 Starting E4B router (Tier 0) on port 8091..."
pkill -f "llama-server.*8091" 2>/dev/null || true
sleep 2

~/tools/llama.cpp/build/bin/llama-server \
    -m ~/ml-models/gemma-4-E4B-it-Q4_K_M.gguf \
    --port 8091 -ngl 99 -c 8192 --host 127.0.0.1 \
    >/tmp/llama_E4B_quickstart.log 2>&1 &

E4B_PID=$!
echo "   PID: $E4B_PID"

# Esperar readiness REAL: /health devuelve 200 mientras los slots aún cargan,
# por eso probamos el endpoint de completions (devuelve 503 "Loading model"
# hasta que el modelo está realmente listo para inferir).
echo "   Waiting for server to be ready (probing /v1/chat/completions)..."
for i in {1..30}; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        http://127.0.0.1:8091/v1/chat/completions \
        -H 'Content-Type: application/json' \
        -d '{"messages":[{"role":"user","content":"ping"}],"max_tokens":1}' 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "200" ]]; then
        echo "   ✅ Server ready (inference endpoint live)"
        break
    fi
    sleep 2
    if [[ $i -eq 30 ]]; then
        echo "   ❌ Server failed to become ready in 60s (last HTTP: $HTTP_CODE)"
        echo "   Check log: tail /tmp/llama_E4B_quickstart.log"
        kill $E4B_PID 2>/dev/null || true
        exit 1
    fi
done

echo ""

# 5. Tests unitarios
echo "🧪 Running unit tests..."
.venv/bin/pytest tests/ -v --tb=short
TEST_RESULT=$?

echo ""

if [[ $TEST_RESULT -eq 0 ]]; then
    echo "✅ Unit tests PASSED"
else
    echo "❌ Unit tests FAILED"
    pkill -f "llama-server.*8091" || true
    exit 1
fi

echo ""

# 6. Eval de routing (gate F1.7: ≥18/20)
echo "📊 Running routing eval (gate: ≥18/20 correct)..."
.venv/bin/python evals/run.py sets/01_intent.jsonl

echo ""
echo "=== Quickstart Complete ==="
echo ""
echo "✅ E4B router running on port 8091 (PID: $E4B_PID)"
echo "✅ Unit tests passed"
echo "✅ Routing eval completed (check report above)"
echo ""
echo "Next steps:"
echo "  1. Review eval results — gate is ≥18/20 intent correct"
echo "  2. To test endpoint: python -m app.main (in another terminal)"
echo "  3. curl -X POST http://localhost:8000/dev/message \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"text\": \"tienen coca de 600 fria?\"}'"
echo ""
echo "To stop E4B server: pkill -f 'llama-server.*8091'"
echo "Log: tail /tmp/llama_E4B_quickstart.log"
