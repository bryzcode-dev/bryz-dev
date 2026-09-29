from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .contract import WorkbookSnapshot


@dataclass(frozen=True)
class GooglePreflight:
    ok: bool
    identity_ok: bool
    contract_ok: bool
    sharing_ok: bool
    codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RemoteBatch:
    rows: tuple[Mapping[str, Any], ...]
    cursor: str
    historical_digest: str


@dataclass(frozen=True)
class PublicationReceipt:
    revision_id: str | None
    verified: bool
    row_counts: Mapping[str, int]
    hashes: Mapping[str, str]


@runtime_checkable
class GoogleGateway(Protocol):
    def preflight(self, binding: object) -> GooglePreflight: ...

    def read_contract(self, binding: object) -> WorkbookSnapshot: ...

    def pull_requests(self, binding: object, checkpoint: str) -> RemoteBatch: ...

    def pull_access_events(self, binding: object, checkpoint: str) -> RemoteBatch: ...

    def publish_results(
        self, binding: object, results: tuple[Mapping[str, Any], ...]
    ) -> PublicationReceipt: ...

    def publish_projection(
        self, binding: object, bundle: Mapping[str, Any]
    ) -> PublicationReceipt: ...
