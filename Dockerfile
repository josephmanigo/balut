FROM node:22-bookworm-slim AS web
WORKDIR /build
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
RUN npm ci --no-audit --no-fund
COPY apps/web apps/web
RUN npm run build

FROM python:3.12.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/edge_api
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 && rm -rf /var/lib/apt/lists/*
COPY deployment/requirements-serving.lock.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/edge_api/balut_api apps/edge_api/balut_api
COPY deployment/releases/automatic-recapture-20260912 deployment/releases/automatic-recapture-20260912
COPY deployment/model-parts deployment/model-parts
COPY scripts/assemble_render_model.py scripts/assemble_render_model.py
RUN python scripts/assemble_render_model.py
COPY --from=web /build/apps/web/dist apps/web/dist
RUN useradd --create-home balut && mkdir -p /tmp/balut && chown balut:balut /tmp/balut
USER balut
EXPOSE 10000
CMD ["sh", "-c", "exec python -m uvicorn balut_api.render_app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --no-proxy-headers --no-access-log --limit-concurrency 16"]
