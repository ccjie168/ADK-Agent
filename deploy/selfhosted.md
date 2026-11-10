# Private (self-hosted) deployment

No `gcloud` needed. The image is a plain HTTP service with bearer auth and a
`/healthz` probe; run it on Docker Compose (single node) or Kubernetes.

## Docker Compose (single node)

```bash
export ADK_MCP_AUTH_TOKEN="$(openssl rand -hex 24)"   # clients send this
export ANTHROPIC_AUTH_TOKEN="<your-model-key>"                  # model provider key
docker compose up -d --build
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/healthz   # 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8080/mcp  # 401
```

### Web console

The Compose file also runs an authenticated console on port 8081
(`http://127.0.0.1:8081`). Open it, paste `ADK_MCP_AUTH_TOKEN`, and chat with
the agents in the browser. `GET /` is a static shell; every `/api/*` call needs
the bearer token.

```bash
docker compose up -d --build
# MCP:      http://127.0.0.1:8080/mcp
# Console:  http://127.0.0.1:8081
```

Point Claude Code at it:

```json
{
  "mcpServers": {
    "adk-local": {
      "type": "http",
      "url": "http://127.0.0.1:8080/mcp",
      "headers": { "Authorization": "Bearer ${ADK_MCP_AUTH_TOKEN}" }
    }
  }
}
```

Put a TLS reverse proxy (Nginx/Traefik/Caddy) in front for anything beyond
loopback. Never expose port 8080 directly to an untrusted network.

## Session persistence

| Deployment | Session store | Notes |
| --- | --- | --- |
| Single node | `SqliteSessionService` via `SESSION_DB=/data/sessions.db` | Default in the image; mount a volume at `/data` |
| Multi node | `DatabaseSessionService` (Postgres) | `pip install "google-adk[db]"` + `asyncpg`; use the same DSN on every replica |

The Compose file mounts the `adk-data` volume at `/data`, so sessions survive a
container restart. `SESSION_DB` is read by the CLI (`--session-db` overrides it).

For multi-node, build a custom entrypoint that injects a Postgres-backed
`Runner`:

```python
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from adk_agent import serve_agent

runner = Runner(
    app_name=agent.name,
    agent=agent,
    session_service=DatabaseSessionService("postgresql+asyncpg://user:pass@db:5432/adk"),
)
serve_agent(
    agent,
    transport="streamable-http",
    host="0.0.0.0",
    auth_token=os.environ["ADK_MCP_AUTH_TOKEN"],
    runner=runner,
)
```

## Kubernetes

Manifests live in `deploy/k8s/`:

```bash
kubectl apply -f deploy/k8s/pvc.yaml
kubectl create secret generic adk-agent-secrets \
  --from-literal=ADK_MCP_AUTH_TOKEN="$(openssl rand -hex 24)" \
  --from-literal=ANTHROPIC_AUTH_TOKEN="<your-model-key>"
kubectl apply -f deploy/k8s/deployment.yaml -f deploy/k8s/service.yaml
```

`deployment.yaml` wires `SESSION_DB` to the PVC and uses `/healthz` for the
readiness and liveness probes. Keep `replicas: 1` with SQLite; switch to
Postgres before scaling out.

## Secrets

- Never bake tokens into the image or the compose file.
- Compose: `environment: ${VAR:?}` reads from the host environment (or a local
  `.env` that is not committed).
- K8s: `Secret` / an external secret manager.
- `.gitignore` already excludes `.env`, `.env.*`, `*.key`, `secrets/`.
