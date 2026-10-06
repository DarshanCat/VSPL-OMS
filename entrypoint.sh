#!/bin/sh
set -eu

PORT="${PORT:-8080}"

cd /app/backend

uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 &
BACKEND_PID=$!

BACKEND_READY=0
i=1

while [ "$i" -le 120 ]; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "ERROR: FastAPI process exited."
        exit 1
    fi

    if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" >/dev/null 2>&1; then
        BACKEND_READY=1
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

cd /app/frontend

HOSTNAME=0.0.0.0 PORT="$PORT" NEXT_PUBLIC_API_URL="" node server.js &
FRONTEND_PID=$!

wait "$FRONTEND_PID"
