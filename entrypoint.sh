#!/bin/sh
set -eu

PORT="${PORT:-8080}"

echo "========================================"
echo "Starting VSPL SMES"
echo "========================================"

echo "[1/3] Starting FastAPI..."

cd /app/backend

uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1 &

BACKEND_PID=$!

echo "FastAPI PID: $BACKEND_PID"
echo "[2/3] Waiting for FastAPI..."

BACKEND_READY=0
i=1

while [ "$i" -le 120 ]; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "ERROR: FastAPI process exited."
        exit 1
    fi

    if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" >/dev/null 2>&1; then
        BACKEND_READY=1
        echo "FastAPI READY"
        break
    fi

    sleep 1
    i=$((i + 1))
done

if [ "$BACKEND_READY" -ne 1 ]; then
    echo "ERROR: FastAPI did not become ready."
    kill "$BACKEND_PID" 2>/dev/null || true
    exit 1
fi

echo "[3/3] Starting Next.js..."

cd /app/frontend

HOSTNAME=0.0.0.0 PORT="$PORT" NEXT_PUBLIC_API_URL="" node server.js &

FRONTEND_PID=$!

echo "Next.js PID: $FRONTEND_PID"
echo "Next.js listening on 0.0.0.0:$PORT"
echo "========================================"
echo "VSPL SMES startup complete"
echo "========================================"

wait "$FRONTEND_PID"
