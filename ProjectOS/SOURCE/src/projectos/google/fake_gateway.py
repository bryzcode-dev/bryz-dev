from __future__ import annotations

import copy
import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from .contract import WorkbookSnapshot, canonical_json_bytes
from .gateway import GooglePreflight, PublicationReceipt, RemoteBatch


class FakeGatewayFailure(RuntimeError):
    pass


class FailurePoint(StrEnum):
    BEFORE_PREFLIGHT = "BEFORE_PREFLIGHT"
    AFTER_PREFLIGHT = "AFTER_PREFLIGHT"
    BEFORE_READ_CONTRACT = "BEFORE_READ_CONTRACT"
    AFTER_READ_CONTRACT = "AFTER_READ_CONTRACT"
    BEFORE_PULL_REQUESTS = "BEFORE_PULL_REQUESTS"
    AFTER_PULL_REQUESTS = "AFTER_PULL_REQUESTS"
    BEFORE_PULL_ACCESS_EVENTS = "BEFORE_PULL_ACCESS_EVENTS"
    AFTER_PULL_ACCESS_EVENTS = "AFTER_PULL_ACCESS_EVENTS"
    BEFORE_PUBLISH_RESULTS = "BEFORE_PUBLISH_RESULTS"
    AFTER_PUBLISH_RESULTS = "AFTER_PUBLISH_RESULTS"
    BEFORE_PUBLISH_PROJECTION = "BEFORE_PUBLISH_PROJECTION"
    AFTER_PUBLISH_PROJECTION = "AFTER_PUBLISH_PROJECTION"


class FakeGoogleGateway:
    def __init__(
        self,
        fixture: Mapping[str, Any],
        failures: Mapping[FailurePoint, int] | None = None,
    ):
        self._fixture = copy.deepcopy(dict(fixture))
        self._requests = copy.deepcopy(list(fixture.get("requests", [])))
        self._access_events = copy.deepcopy(list(fixture.get("access_events", [])))
        self._write_ready = bool(fixture.get("write_ready", False))
        self._failures = dict(failures or {})
        self._historical: dict[tuple[str, str], str] = {}
        self.call_log: list[dict[str, Any]] = []
        self.published_results: list[dict[str, Any]] = []
        self.published_projections: list[dict[str, Any]] = []

    @classmethod
    def from_fixture(
        cls,
        fixture: Mapping[str, Any] | str | Path,
        failures: Mapping[FailurePoint, int] | None = None,
    ) -> "FakeGoogleGateway":
        if isinstance(fixture, (str, Path)):
            data = json.loads(Path(fixture).read_text(encoding="utf-8"))
        else:
            data = fixture
        return cls(data, failures)

    def _fail(self, point: FailurePoint) -> None:
        remaining = self._failures.get(point, 0)
        if remaining == 0:
            return
        if remaining > 0:
            self._failures[point] = remaining - 1
        raise FakeGatewayFailure(f"injected fake gateway failure at {point.value}")

    def _log(self, method: str, **safe: Any) -> None:
        self.call_log.append({"method": method, **copy.deepcopy(safe)})

    def preflight(self, binding: object) -> GooglePreflight:
        self._fail(FailurePoint.BEFORE_PREFLIGHT)
        self._log("preflight")
        result = GooglePreflight(True, True, True, True)
        self._fail(FailurePoint.AFTER_PREFLIGHT)
        return result

    def read_contract(self, binding: object) -> WorkbookSnapshot:
        self._fail(FailurePoint.BEFORE_READ_CONTRACT)
        self._log("read_contract")
        tabs = {
            name: (tuple(value.get("headers", ())), int(value.get("row_count", 0)))
            for name, value in self._fixture.get("tabs", {}).items()
        }
        result = WorkbookSnapshot(self._fixture.get("contract_version"), tabs)
        self._fail(FailurePoint.AFTER_READ_CONTRACT)
        return result

    def pull_requests(self, binding: object, checkpoint: str) -> RemoteBatch:
        return self._pull(
            "requests",
            self._requests,
            checkpoint,
            FailurePoint.BEFORE_PULL_REQUESTS,
            FailurePoint.AFTER_PULL_REQUESTS,
        )

    def pull_access_events(self, binding: object, checkpoint: str) -> RemoteBatch:
        return self._pull(
            "access_events",
            self._access_events,
            checkpoint,
            FailurePoint.BEFORE_PULL_ACCESS_EVENTS,
            FailurePoint.AFTER_PULL_ACCESS_EVENTS,
        )

    def _pull(
        self,
        kind: str,
        rows: list[dict[str, Any]],
        checkpoint: str,
        before: FailurePoint,
        after: FailurePoint,
    ) -> RemoteBatch:
        self._fail(before)
        cursor = int(checkpoint or "0")
        ordered = sorted(copy.deepcopy(rows), key=lambda row: (int(row["sequence"]), repr(row)))
        historical_rows = [row for row in ordered if int(row["sequence"]) <= cursor]
        digest = hashlib.sha256(canonical_json_bytes(historical_rows)).hexdigest()
        key = (kind, str(cursor))
        prior = self._historical.get(key)
        if prior is not None and prior != digest:
            raise FakeGatewayFailure("historical payload was edited or deleted")
        self._historical[key] = digest
        pending = tuple(row for row in ordered if int(row["sequence"]) > cursor)
        next_cursor = str(max([cursor, *(int(row["sequence"]) for row in pending)]))
        self._log(kind, checkpoint=str(cursor), returned=len(pending), cursor=next_cursor)
        result = RemoteBatch(pending, next_cursor, digest)
        self._fail(after)
        return result

    def publish_results(
        self, binding: object, results: tuple[Mapping[str, Any], ...]
    ) -> PublicationReceipt:
        self._fail(FailurePoint.BEFORE_PUBLISH_RESULTS)
        self._assert_write_ready()
        self.published_results.extend(copy.deepcopy([dict(result) for result in results]))
        digest = hashlib.sha256(canonical_json_bytes(list(results))).hexdigest()
        self._log("publish_results", count=len(results), digest=digest)
        receipt = PublicationReceipt(None, True, {"results": len(results)}, {"results": digest})
        self._fail(FailurePoint.AFTER_PUBLISH_RESULTS)
        return receipt

    def publish_projection(
        self, binding: object, bundle: Mapping[str, Any]
    ) -> PublicationReceipt:
        self._fail(FailurePoint.BEFORE_PUBLISH_PROJECTION)
        self._assert_write_ready()
        copied = copy.deepcopy(dict(bundle))
        self.published_projections.append(copied)
        tabs = copied.get("tabs", {})
        counts = {name: len(rows) for name, rows in tabs.items()}
        hashes = {
            name: hashlib.sha256(canonical_json_bytes(rows)).hexdigest()
            for name, rows in tabs.items()
        }
        revision_id = copied.get("revision_id")
        self._log("publish_projection", revision_id=revision_id, row_counts=counts)
        receipt = PublicationReceipt(revision_id, True, counts, hashes)
        self._fail(FailurePoint.AFTER_PUBLISH_PROJECTION)
        return receipt

    def _assert_write_ready(self) -> None:
        if not self._write_ready:
            raise FakeGatewayFailure("fake gateway write gate is closed")

    def replace_request_rows(self, rows: tuple[Mapping[str, Any], ...]) -> None:
        self._requests = copy.deepcopy([dict(row) for row in rows])
