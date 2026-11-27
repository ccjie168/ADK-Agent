"""Approval notifications over webhooks (ADR-0049)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from .core import ApprovalNotice

logger = logging.getLogger(__name__)

__all__ = ["MultiNotifier", "NotifierError", "WebhookNotifier"]


class NotifierError(RuntimeError):
    """The notification could not be delivered."""


class WebhookNotifier:
    """POST a signed JSON notice, retrying a bounded number of times."""

    def __init__(
        self,
        url: str,
        *,
        secret: str,
        client: httpx.AsyncClient | None = None,
        retries: int = 2,
        backoff_seconds: float = 0.2,
        timeout: float = 5.0,
    ) -> None:
        self.url = url
        self._secret = secret.encode()
        self._client = client
        self.retries = max(0, retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.timeout = timeout

    def sign(self, body: bytes) -> str:
        return "sha256=" + hmac.new(self._secret, body, hashlib.sha256).hexdigest()

    async def notify(self, notice: ApprovalNotice) -> None:
        body = json.dumps(
            notice.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-ADK-Signature": self.sign(body)}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                await self._post(body, headers)
                return
            except (httpx.HTTPError, NotifierError) as exc:
                last = exc
                if attempt < self.retries and self.backoff_seconds:
                    await asyncio.sleep(self.backoff_seconds * (attempt + 1))
        raise NotifierError(f"webhook notification failed: {type(last).__name__}") from None

    async def _post(self, body: bytes, headers: dict[str, str]) -> None:
        if self._client is not None:
            response = await self._client.post(self.url, content=body, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.post(self.url, content=body, headers=headers)
        if response.status_code >= 300:
            raise NotifierError(f"webhook returned {response.status_code}")


class MultiNotifier:
    """Fan a notice out to several notifiers; failures are isolated and logged."""

    def __init__(self, notifiers: list[Any]) -> None:
        self.notifiers = list(notifiers)

    async def notify(self, notice: ApprovalNotice) -> None:
        for notifier in self.notifiers:
            try:
                await notifier.notify(notice)
            except Exception:  # noqa: BLE001  # one bad channel must not block the rest
                logger.warning("approval notifier failed", exc_info=True)
