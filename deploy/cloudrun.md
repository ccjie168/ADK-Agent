# Deploy to Cloud Run

The container runs `adk-agent serve --transport streamable-http --host 0.0.0.0`
and **refuses to start without `ADK_MCP_AUTH_TOKEN`** (CP-S6). Cloud Run injects
`PORT`; the server reads it.

## Prerequisites

- `gcloud` CLI, authenticated (`gcloud auth login`)
- A GCP project with Cloud Run and Artifact Registry enabled
- Two secrets in Secret Manager:
  - `mcp-auth-token` — the bearer token clients must send
  - `deepseek-key` — the model provider key (`ANTHROPIC_AUTH_TOKEN`)

```bash
# create the MCP bearer token (random, 48 hex chars)
printf '%s' "$(openssl rand -hex 24)" | gcloud secrets create mcp-auth-token --data-file=-
```

## Deploy from source (uses the Dockerfile)

```bash
gcloud run deploy adk-agent-mcp \
  --source . \
  --region asia-east1 \
  --port 8080 \
  --allow-unauthenticated \
  --set-env-vars ADK_AGENT_MODEL=claude:deepseek-v4-pro,ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic \
  --set-secrets ADK_MCP_AUTH_TOKEN=mcp-auth-token:latest,ANTHROPIC_AUTH_TOKEN=deepseek-key:latest
```

`--allow-unauthenticated` is the **Cloud Run IAM** layer. The MCP endpoint still
requires `Authorization: Bearer <token>` at the application layer; without it
every `/mcp` request returns 401. Only `/healthz` is open, and it returns no data.

> Alternative: keep Cloud Run IAM on (`--no-allow-unauthenticated`) and have
> clients mint a Google identity token. Claude Code's MCP HTTP client sends
> static headers, so the bearer-token model above is the simpler fit.

## Point Claude Code at the service

```json
{
  "mcpServers": {
    "adk-remote": {
      "type": "http",
      "url": "https://<service>-<hash>-<region>.a.run.app/mcp",
      "headers": { "Authorization": "Bearer ${ADK_MCP_AUTH_TOKEN}" }
    }
  }
}
```

## Verify

```bash
URL=https://<service>-<hash>-<region>.a.run.app
curl -s -o /dev/null -w 'health %{http_code}\n' "$URL/healthz"        # 200
curl -s -o /dev/null -w 'noauth %{http_code}\n' -X POST "$URL/mcp"   # 401
curl -s -o /dev/null -w 'auth   %{http_code}\n' \
  -H "Authorization: Bearer $ADK_MCP_AUTH_TOKEN" -X POST "$URL/mcp"  # != 401
```

## Notes

- **Do not** set `ALLOW_UNAUTHENTICATED` in Cloud Run.
- In-memory sessions are per instance. For multi-instance continuity, inject a
  persistent `runner` (e.g. a database or Vertex session service) — follow-up
  slice.
- `check.py --full` runs locally; add `pip-audit`/SBOM to CI when CI is adopted.
