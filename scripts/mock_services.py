#!/usr/bin/env python3
"""Local mock ecosystem for the support-agent demo (ITSM, Quark, WeCom)."""

from __future__ import annotations

import argparse
import base64
import binascii
import os
from datetime import datetime, timezone
from itertools import count
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

_MAX_FILE = 1024 * 1024
_PRIORITIES = ("low", "normal", "high")
_MESSAGES = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unauthorized() -> JSONResponse:
    return JSONResponse({"error": "unauthorized"}, status_code=401)


def build_mock_app(*, token: str | None = None) -> FastAPI:
    expected = token or os.environ.get("MOCK_TOKEN") or "mock-token"
    app = FastAPI(title="ADK support mock", docs_url=None, redoc_url=None)
    tickets: dict[str, dict[str, Any]] = {}
    files: dict[str, dict[str, Any]] = {}
    messages: list[dict[str, Any]] = []
    ticket_ids = count(1)
    file_ids = count(1)
    message_ids = count(1)

    def authorized(header: str | None) -> bool:
        return header == f"Bearer {expected}"

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/itsm/tickets")
    async def create_ticket(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        if not authorized(authorization):
            return _unauthorized()
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_ticket"}, status_code=400)
        title = body.get("title") if isinstance(body, dict) else None
        description = body.get("description", "") if isinstance(body, dict) else None
        priority = body.get("priority", "normal") if isinstance(body, dict) else None
        if (
            not isinstance(title, str)
            or not 1 <= len(title) <= 200
            or not isinstance(description, str)
            or len(description) > 2000
            or priority not in _PRIORITIES
        ):
            return JSONResponse({"error": "invalid_ticket"}, status_code=400)
        ticket_id = f"t-{next(ticket_ids)}"
        ticket = {
            "id": ticket_id,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "open",
            "created_at": _now(),
        }
        tickets[ticket_id] = ticket
        return JSONResponse(ticket, status_code=201)

    @app.get("/itsm/tickets/{ticket_id}")
    async def get_ticket(ticket_id: str, authorization: str | None = Header(default=None)) -> Any:
        if not authorized(authorization):
            return _unauthorized()
        ticket = tickets.get(ticket_id)
        if ticket is None:
            return JSONResponse({"error": "ticket_not_found"}, status_code=404)
        return ticket

    @app.post("/quark/files")
    async def upload_file(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        if not authorized(authorization):
            return _unauthorized()
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_file"}, status_code=400)
        name = body.get("name") if isinstance(body, dict) else None
        encoded = body.get("content_base64") if isinstance(body, dict) else None
        if not isinstance(name, str) or not 1 <= len(name) <= 128 or not isinstance(encoded, str):
            return JSONResponse({"error": "invalid_file"}, status_code=400)
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return JSONResponse({"error": "invalid_file"}, status_code=400)
        if len(content) > _MAX_FILE:
            return JSONResponse({"error": "file_too_large"}, status_code=413)
        file_id = f"f-{next(file_ids)}"
        files[file_id] = {"name": name, "size": len(content), "content": content}
        return JSONResponse(
            {"file_id": file_id, "name": name, "size": len(content)}, status_code=201
        )

    @app.get("/quark/files/{file_id}")
    async def file_metadata(file_id: str, authorization: str | None = Header(default=None)) -> Any:
        if not authorized(authorization):
            return _unauthorized()
        stored = files.get(file_id)
        if stored is None:
            return JSONResponse({"error": "file_not_found"}, status_code=404)
        return {"file_id": file_id, "name": stored["name"], "size": stored["size"]}

    @app.post("/wecom/webhook")
    async def wecom_webhook(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        if not authorized(authorization):
            return _unauthorized()
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_message"}, status_code=400)
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str) or not 1 <= len(text) <= 2000:
            return JSONResponse({"error": "invalid_message"}, status_code=400)
        message_id = f"w-{next(message_ids)}"
        messages.append({"id": message_id, "text": text, "sent_at": _now()})
        del messages[:-_MESSAGES]
        return JSONResponse({"sent": True, "id": message_id}, status_code=201)

    @app.get("/wecom/messages")
    async def list_messages(authorization: str | None = Header(default=None)) -> Any:
        if not authorized(authorization):
            return _unauthorized()
        return list(messages)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the support-agent mock services.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8055)
    parser.add_argument(
        "--print-token", action="store_true", help="print the bearer token and exit"
    )
    args = parser.parse_args()

    token = os.environ.get("MOCK_TOKEN") or "mock-token"
    if args.print_token:
        print(token)
        return
    import uvicorn

    uvicorn.run(build_mock_app(token=token), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
