"""Approval gate adapters."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from ..core import ApprovalDecision, ApprovalRequest

ApprovalCallback = Callable[[ApprovalRequest], ApprovalDecision | Awaitable[ApprovalDecision]]


class CallbackApprovalGate:
    """Delegate approval to a sync or async callback."""

    def __init__(self, callback: ApprovalCallback) -> None:
        self.callback = callback

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        result = self.callback(request)
        if inspect.isawaitable(result):
            return await result
        return result
