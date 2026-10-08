# ---------- Frontend build ----------
FROM node:24-bookworm-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./

ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_API_URL=""

RUN npm run build


# ---------- Backend runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Runtime packages required by psycopg2 and other Python dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libpq5 nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt

RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/

# Copy the standalone Next.js application
COPY --from=frontend-builder /app/frontend/.next/standalone /app/frontend/
COPY --from=frontend-builder /app/frontend/.next/static /app/frontend/.next/static
COPY --from=frontend-builder /app/frontend/public /app/frontend/public

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
EXPOSE 8080

CMD ["/app/entrypoint.sh"]







