# ── Build stage ──────────────────────────────────────────────────────
# Install dependencies into a virtualenv we can copy wholesale, so the
# final image carries no build toolchain.
FROM python:3.11-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements/base.txt requirements/base.txt
RUN pip install -r requirements/base.txt

# ── Runtime stage ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Run as an unprivileged user, never root.
RUN groupadd --system concord \
    && useradd --system --gid concord --home /app --shell /usr/sbin/nologin concord

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONCORD_DB_PATH=/data/concord.db

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY . .

# Writable data dir for the SQLite default backend, owned by the app user.
RUN mkdir -p /data && chown -R concord:concord /data /app

USER concord
EXPOSE 8000

# Container-level liveness: hit the app's health endpoint.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else sys.exit(1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]