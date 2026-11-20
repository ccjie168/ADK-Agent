"""Build per-agent RAG contexts from deployment config (ADR-0036)."""

from __future__ import annotations

from ..core import AgentManifest, AuditSink, ModelPolicy
from .context import RagContext
from .guard import RagGuard
from .ingest import Embedder
from .pgvector_service import PgVectorRagService
from .vector_store import PgVectorRagStore


class RagFactory:
    """One shared store and embedding gateway, one context per enabled manifest."""

    def __init__(
        self,
        store: PgVectorRagStore,
        gateway: Embedder,
        *,
        provider: str,
        model: str,
        audit: AuditSink | None = None,
        policy: ModelPolicy | None = None,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.provider = provider
        self.model = model
        self.audit = audit
        self.policy = policy

    def context(self, manifest: AgentManifest) -> RagContext | None:
        """Return a context for a manifest that opts in, otherwise ``None``."""
        config = manifest.rag
        if config is None or not config.enabled:
            return None
        service = PgVectorRagService(
            self.store,
            self.gateway,
            provider=self.provider,
            model=self.model,
            limit=config.top_k,
        )
        return RagContext(
            service,
            data_classes=list(config.data_classes),
            top_k=config.top_k,
            min_confidence=config.min_confidence,
            on_error=config.on_error,
            guard=RagGuard(min_confidence=config.min_confidence),
            policy=self.policy or manifest.model_policy,
            audit=self.audit,
        )

    async def aclose(self) -> None:
        await self.store.aclose()


def build_rag_factory(
    *,
    database_url: str,
    dimensions: int,
    model: str,
    provider: str = "litellm",
    audit: AuditSink | None = None,
    policy: ModelPolicy | None = None,
) -> RagFactory:
    """Construct the production factory from the deployment's RAG settings."""
    import os

    from ..models.budget import BudgetTracker
    from ..models.embeddings import EmbeddingGateway
    from ..models.providers import LiteLlmProvider

    if provider != "litellm":
        raise ValueError(f"unknown rag provider {provider!r}")
    gateway = EmbeddingGateway(
        {provider: LiteLlmProvider(api_key=os.environ.get("LITELLM_API_KEY"))},
        audit=audit,
        budgets=BudgetTracker(),
    )
    return RagFactory(
        PgVectorRagStore(database_url, dimensions=dimensions),
        gateway,
        provider=provider,
        model=model,
        audit=audit,
        policy=policy,
    )


__all__ = ["RagFactory", "build_rag_factory"]
