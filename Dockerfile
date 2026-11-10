ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ADK_AGENT_MODEL=claude:deepseek-v4-pro \
    SESSION_DB=/data/sessions.db

WORKDIR /app

# /data holds the SQLite session store; it must be writable by the app user.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data

COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples

# Third-party deps come from wheels only (no setup scripts). The project itself
# is installed with --no-deps. NOTE: runtime deps are not locked yet; add a lock
# file and produce an SBOM before a production release (CI/SBOM slice, CP-S4).
RUN python -m pip install --root-user-action=ignore --upgrade pip \
    && python -m pip install --root-user-action=ignore --only-binary :all: \
        "google-adk[mcp]" "anthropic>=0.78" "uvicorn>=0.30" \
    && python -m pip install --root-user-action=ignore --no-deps .

USER app

# Cloud Run injects PORT. The server refuses to start without ADK_MCP_AUTH_TOKEN,
# so an unauthenticated public bind is impossible by default (CP-S6).
ENTRYPOINT ["python", "-m", "adk_agent", "serve", \
            "--agent", "examples/minimal/agent.py", \
            "--transport", "streamable-http", \
            "--host", "0.0.0.0"]
