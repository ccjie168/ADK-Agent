ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ADK_AGENT_MODEL=claude:deepseek-v4-pro

WORKDIR /app

RUN useradd --create-home --uid 10001 app

COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples

# NOTE: runtime dependencies are not locked yet. Add a lock file and produce an
# SBOM before a production release (CI/SBOM slice, CP-S4).
RUN python -m pip install --root-user-action=ignore --upgrade pip \
    && python -m pip install --root-user-action=ignore ".[claude,http]"

USER app

# Cloud Run injects PORT. The server refuses to start without ADK_MCP_AUTH_TOKEN,
# so an unauthenticated public bind is impossible by default (CP-S6).
ENTRYPOINT ["python", "-m", "adk_agent", "serve", \
            "--agent", "examples/minimal/agent.py", \
            "--transport", "streamable-http", \
            "--host", "0.0.0.0"]
