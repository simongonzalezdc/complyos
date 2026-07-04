# syntax=docker/dockerfile:1
#
# ComplyOS dashboard container image.
#
# Single-stage build: complyos has no compiled dependencies (FastAPI,
# SQLAlchemy, aiosqlite, uvicorn, jinja2, etc. all ship prebuilt wheels for
# this base image), so there is no build toolchain to shed in a second
# stage. A multi-stage split would not meaningfully shrink this image.
FROM python:3.11-slim

LABEL org.opencontainers.image.title="ComplyOS" \
      org.opencontainers.image.description="L&D Compliance & Learning Operations dashboard" \
      org.opencontainers.image.licenses="BUSL-1.1"

# Unbuffered stdout/stderr so `docker logs` streams in real time; skip .pyc
# writes and pip's cache dir, neither of which help a throwaway image layer.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Only what `pip install .` needs: pyproject.toml (dependencies + the
# `complyos` console-script entry point), README.md (referenced by
# `[project] readme` in pyproject.toml — hatchling reads it for metadata),
# and the package source itself. This intentionally excludes the `postgres`
# extra (psycopg) — SQLite is the local-first default; build a derived image
# with `pip install .[postgres]` if a shared Postgres deployment needs it.
COPY pyproject.toml README.md ./
COPY complyos ./complyos
RUN pip install .

# Run as a fixed non-root uid/gid. /data is the only writable path the app
# needs — it holds the SQLite file and any exported evidence/CSV artifacts —
# and is meant to be mounted as a volume so state survives container
# recreation (see docker-compose.yml and deploy/docker.md).
RUN groupadd --system --gid 1000 complyos \
    && useradd --system --uid 1000 --gid complyos --no-create-home --shell /usr/sbin/nologin complyos \
    && mkdir -p /data \
    && chown -R complyos:complyos /data

USER complyos

# `complyos serve-dashboard` has no --db flag; the database location is
# controlled entirely by COMPLYOS_DATABASE_URL (see
# complyos/models/database.py:resolve_database_url). Default to the SQLite
# file under the /data volume; override with a postgresql+psycopg:// URL
# for Postgres (requires the postgres extra, see note above).
ENV COMPLYOS_DATABASE_URL="sqlite:////data/complyos.db"

VOLUME ["/data"]
EXPOSE 8000

# Hits the same unauthenticated /health route mounted by
# complyos.web.dashboard:create_dashboard_app. Uses stdlib urllib instead of
# curl/wget so no extra package needs installing into the slim base image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" || exit 1

# --host 0.0.0.0 is correct *inside* the container (it must accept
# connections from the Docker network); host-side exposure is controlled by
# the port mapping in docker-compose.yml, which binds to 127.0.0.1 by
# default (local-first posture — see deploy/docker.md).
CMD ["complyos", "serve-dashboard", "--host", "0.0.0.0", "--port", "8000"]
