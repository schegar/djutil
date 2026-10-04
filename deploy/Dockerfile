# DJUtil server image (multi-stage: Vite web build -> slim Python runtime).

FROM node:22-alpine AS web
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ .
RUN pnpm build

FROM python:3.12-slim AS app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY shared/pyproject.toml shared/
COPY shared/src shared/src
COPY server/pyproject.toml server/
COPY server/src server/src
# The workspace references other members; stub them so resolution works.
COPY agent/pyproject.toml agent/
RUN mkdir -p agent/src/djutil_agent && touch agent/src/djutil_agent/__init__.py

RUN uv sync --frozen --package djutil-server --no-dev

COPY --from=web /web/dist /app/static
ENV DJUTIL_DATA_DIR=/data \
    DJUTIL_STATIC_DIR=/app/static \
    # uv installs into /app/.venv; put it on PATH so `python -m djutil_server`
    # works for CMD/HEALTHCHECK and `docker compose run` one-offs.
    PATH="/app/.venv/bin:$PATH"

RUN useradd -r -u 10001 djutil && mkdir -p /data && chown djutil /data
USER djutil
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", \
         "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]

CMD ["python", "-m", "djutil_server", "serve", \
     "--host", "0.0.0.0", "--port", "8000"]
