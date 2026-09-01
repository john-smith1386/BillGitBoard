# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY frontend/ ./
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
# Canonical and link-preview URLs are compiled into index.html here, so the
# public origin has to arrive as a build argument; a runtime variable is too
# late. Left empty, the site falls back to the default in vite.config.ts.
ARG VITE_SITE_URL=""
ENV VITE_SITE_URL=${VITE_SITE_URL}
# Analytics is opt-in: with no measurement ID the tag is stripped from the
# built HTML. Render forwards service environment variables to matching ARGs.
ARG VITE_GA_MEASUREMENT_ID=""
ENV VITE_GA_MEASUREMENT_ID=${VITE_GA_MEASUREMENT_ID}
RUN npm run build


FROM python:3.12-slim-bookworm AS python-build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY app/ ./app/
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip wheel --wheel-dir /wheels .


FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    BILLGITBOARD_DATA_DIR=/data \
    BILLGITBOARD_FRONTEND_DIR=/app/frontend/dist

# libgomp is used by scikit-learn wheels. libglib is kept for OpenCV's
# headless runtime on Debian. setpriv performs the one-time managed-volume
# ownership bootstrap before irrevocably dropping to UID/GID 10001. The root
# bootstrap requires CAP_SETPCAP to clear its capability bounding set.
# Only /data is handed to the application user: /app stays root-owned and
# world-readable, so the process decoding untrusted images can read its own
# code and assets but never rewrite them.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libglib2.0-0 libgomp1 util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 billgitboard \
    && useradd --system --uid 10001 --gid billgitboard --home-dir /nonexistent --shell /usr/sbin/nologin billgitboard \
    && mkdir -p /app/frontend/dist /data \
    && chown -R billgitboard:billgitboard /data

COPY --from=python-build /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

WORKDIR /app
COPY --from=frontend-build /build/frontend/dist ./frontend/dist
COPY --chmod=0755 scripts/docker-entrypoint.sh /usr/local/bin/billgitboard-entrypoint

# Managed platforms commonly attach a new volume as root. The entrypoint may
# start as root only to validate and chown the dedicated data mount, then uses
# setpriv to run Uvicorn as billgitboard (10001:10001). Compose overrides this
# to start non-root immediately because its named volume inherits image ownership.
USER root
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=4)"

ENTRYPOINT ["/usr/local/bin/billgitboard-entrypoint"]
CMD ["sh", "-c", "exec uvicorn app.api:app --host 0.0.0.0 --port \"${PORT:-8000}\" --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
