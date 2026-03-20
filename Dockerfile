# -- Stage 1: Build React frontend --
FROM node:20-alpine AS frontend

WORKDIR /build
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ .
RUN npm run build

# -- Stage 2: Engine (no UI) --
FROM python:3.12-slim AS engine

WORKDIR /app

COPY engine/pyproject.toml .
COPY engine/potatosearch/ potatosearch/
RUN pip install --no-cache-dir .

VOLUME /data
ENV POTATOSEARCH_DATA_DIR=/data
ENV POTATOSEARCH_SERVE_UI=false

EXPOSE 8391

CMD ["potatosearch-server"]

# -- Stage 3: Engine + UI (default) --
FROM engine

COPY --from=frontend /build/dist/ /app/ui/dist/

ENV POTATOSEARCH_SERVE_UI=true
ENV POTATOSEARCH_UI_DIST_DIR=/app/ui/dist
