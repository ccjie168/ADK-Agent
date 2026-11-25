ARG PYTHON_IMAGE=python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ADK_AGENT_MODEL=claude:deepseek-v4-pro \
    SESSION_DB=/data/sessions.db

WORKDIR /app

# The base image snapshot predates the zlib and zstd security updates.
# APT_MIRROR lets restricted networks pick a Debian mirror; it is not
# persisted in the image.
ARG APT_MIRROR=deb.debian.org
RUN sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends zlib1g libzstd1 \
    && rm -rf /var/lib/apt/lists/*

# /data holds the SQLite session store; it must be writable by the app user.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data

COPY pyproject.toml README.md ./
COPY requirements/runtime.lock ./requirements/runtime.lock
COPY src ./src
COPY examples ./examples

# runtime.lock is compiled in python:3.13-slim and carries a hash for every
# artifact, so the build fails on any registry substitution. It also pins the
# build backend, so the project install runs without build isolation and never
# fetches a build-time package from the index. Regenerate it with pip-compile in
# the same image whenever pyproject.toml changes.
# PIP_INDEX_URL is optional and lets restricted networks use a mirror; it is
# not persisted in the image, and the hashes still come from the lock.
ARG PIP_INDEX_URL
RUN python -m pip install --root-user-action=ignore --upgrade pip \
    && python -m pip install --root-user-action=ignore --only-binary :all: \
        --require-hashes -r requirements/runtime.lock \
    && python -m pip install --root-user-action=ignore --no-build-isolation --no-deps .

USER app

# Cloud Run injects PORT. The server refuses to start without ADK_MCP_AUTH_TOKEN,
# so an unauthenticated public bind is impossible by default (CP-S6).
ENTRYPOINT ["python", "-m", "adk_agent", "serve", \
            "--agent", "examples/minimal/agent.py", \
            "--transport", "streamable-http", \
            "--host", "0.0.0.0"]
