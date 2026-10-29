"""Unwired local-only reservation experiment; not a provider billing meter."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.modules.ai.llm_client import (
    EmbeddingsClient,
    NativePostReservationError,
    ResilientEmbeddingsClient,
    native_post_reservation_scope,
)


class LocalReservationExhaustedError(NativePostReservationError):
    """The experiment must stop before invoking another POST."""


@dataclass(frozen=True, slots=True)
class ReservationSnapshot:
    limit: int
    reserved: int
    coverage: str = "partial_unwired"
    denied: bool = False


class LocalPostReservations:
    """One event-loop-local budget shared explicitly by all experiment clients.

    A reservation is conservative: cancellation before an actual send still
    consumes it. This does not measure billed operations or survive restart.
    """

    def __init__(self, limit: int):
        if type(limit) is not int or limit < 1:
            raise ValueError("local_post_limit_invalid")
        self._limit = limit
        self._reserved = 0
        self._denied = False
        self._lock = asyncio.Lock()

    async def reserve(self) -> int:
        async with self._lock:
            if self._reserved >= self._limit:
                self._denied = True
                raise LocalReservationExhaustedError("local_post_limit_exhausted")
            self._reserved += 1
            return self._reserved

    async def snapshot(self) -> ReservationSnapshot:
        async with self._lock:
            return ReservationSnapshot(self._limit, self._reserved, denied=self._denied)


class LocalBoundedEmbeddings:
    """Local-only adapter around the exact native client and its transport."""

    def __init__(self, client: ResilientEmbeddingsClient, budget: LocalPostReservations):
        self._client, self._budget = client, budget
        self._validate()

    def _validate(self) -> None:
        client, budget = self._client, self._budget
        if (type(client) is not ResilientEmbeddingsClient or type(budget) is not LocalPostReservations
                or not client._clients or any(type(item) is not EmbeddingsClient for item in client._clients)
                or any(any(name in item.__dict__ for name in ("_request", "_embed")) for item in client._clients)
                or any(name in client.__dict__ for name in ("_call_with_failover_provenance",
                    "embed_documents_with_provenance", "embed_queries_with_provenance"))):
            raise ValueError("local_embedding_transport_unsupported")

    @property
    def provider_names(self) -> list[str]:
        return self._client.provider_names

    async def embed_documents_with_provenance(self, *args: Any, **kwargs: Any) -> Any:
        self._validate()
        with native_post_reservation_scope(self._budget.reserve):
            return await self._client.embed_documents_with_provenance(*args, **kwargs)

    async def embed_queries_with_provenance(self, *args: Any, **kwargs: Any) -> Any:
        self._validate()
        with native_post_reservation_scope(self._budget.reserve):
            return await self._client.embed_queries_with_provenance(*args, **kwargs)
