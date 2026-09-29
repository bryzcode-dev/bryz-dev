from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
from uuid import UUID

from projectos.google.contract import WorkbookSnapshot
from projectos.google.gateway import GooglePreflight, PublicationReceipt, RemoteBatch
from projectos.google.types import GoogleBindingRecord


class GoogleIntegrationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Clients:
    identity: str
    sheets: Any
    drive: Any


def _default_credentials(_credential_reference_id: UUID):
    try:
        import google.auth  # type: ignore[import-not-found]
    except ImportError as exc:
        raise GoogleIntegrationError(
            "GOOGLE_EXTRA_MISSING", "Install ProjectOS with the google optional dependency"
        ) from exc
    credentials, _project = google.auth.default(
        scopes=(
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.metadata.readonly",
            "https://www.googleapis.com/auth/userinfo.email",
        )
    )
    return credentials


def _default_discovery(service: str, version: str, credentials: Any):
    try:
        from googleapiclient.discovery import build  # type: ignore[import-not-found]
    except ImportError as exc:
        raise GoogleIntegrationError(
            "GOOGLE_EXTRA_MISSING", "Install ProjectOS with the google optional dependency"
        ) from exc
    return build(service, version, credentials=credentials, cache_discovery=False)


class _OfficialSheetsAdapter:
    def __init__(self, resource: Any):
        self.resource = resource

    def read_contract(self, spreadsheet_id: str) -> WorkbookSnapshot:
        metadata = self.resource.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties.title",
        ).execute()
        titles = [item["properties"]["title"] for item in metadata.get("sheets", [])]
        ranges = [f"'{title}'!1:1" for title in titles]
        response = self.resource.spreadsheets().values().batchGet(
            spreadsheetId=spreadsheet_id, ranges=ranges
        ).execute()
        tabs: dict[str, tuple[tuple[str, ...], int]] = {}
        for title, value_range in zip(titles, response.get("valueRanges", []), strict=False):
            values = value_range.get("values", [])
            tabs[title] = (tuple(str(item) for item in (values[0] if values else ())), max(0, len(values) - 1))
        schema = self.resource.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range="'_ProjectOS_Schema'!A2:B20"
        ).execute().get("values", [])
        schema_map = {str(row[0]): row[1] for row in schema if len(row) >= 2}
        version = int(schema_map["contract_version"]) if "contract_version" in schema_map else None
        return WorkbookSnapshot(version, tabs)

    def pull_requests(self, spreadsheet_id: str, checkpoint: str) -> Mapping[str, Any]:
        return self._pull(spreadsheet_id, "Change_Requests", checkpoint)

    def pull_access_events(self, spreadsheet_id: str, checkpoint: str) -> Mapping[str, Any]:
        return self._pull(spreadsheet_id, "Access_Events", checkpoint)

    def _pull(self, spreadsheet_id: str, tab: str, checkpoint: str) -> Mapping[str, Any]:
        values = self.resource.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f"'{tab}'!A:Z"
        ).execute().get("values", [])
        if not values:
            return {"rows": (), "cursor": checkpoint, "historical_digest": ""}
        headers = [str(value) for value in values[0]]
        rows = []
        for row_number, values_row in enumerate(values[1:], start=2):
            if row_number <= int(checkpoint or "0"):
                continue
            row = {header: values_row[index] if index < len(values_row) else "" for index, header in enumerate(headers)}
            row["source_row"] = row_number
            row["sequence"] = row_number
            rows.append(row)
        cursor = str(max([int(checkpoint or "0"), *(row["sequence"] for row in rows)]))
        return {"rows": tuple(rows), "cursor": cursor, "historical_digest": ""}

    def publish_results(self, spreadsheet_id: str, results: tuple[Mapping[str, Any], ...]):
        raise GoogleIntegrationError(
            "LIVE_RESULT_MAPPING_REQUIRED",
            "Live result publication requires the separately approved workbook activation step",
        )

    def publish_projection(self, spreadsheet_id: str, bundle: Mapping[str, Any]):
        raise GoogleIntegrationError(
            "LIVE_PROJECTION_MAPPING_REQUIRED",
            "Live projection publication requires the separately approved workbook activation step",
        )


class _OfficialDriveAdapter:
    def __init__(self, resource: Any):
        self.resource = resource

    def list_permissions(self, spreadsheet_id: str):
        return self.resource.permissions().list(
            fileId=spreadsheet_id,
            fields="permissions(type,role,emailAddress,domain,allowFileDiscovery)",
        ).execute().get("permissions", [])


class RealGoogleGateway:
    def __init__(
        self,
        expected_owner_email: str,
        *,
        automation_email: str | None = None,
        allow_writes: bool = False,
        cli_write_flag: bool = False,
        credential_factory: Callable[[UUID], Any] | None = None,
        identity_factory: Callable[[Any], str] | None = None,
        sheets_factory: Callable[[Any], Any] | None = None,
        drive_factory: Callable[[Any], Any] | None = None,
    ):
        self.expected_owner_email = expected_owner_email.strip().lower()
        self.automation_email = automation_email.strip().lower() if automation_email else None
        self.allow_writes = allow_writes
        self.cli_write_flag = cli_write_flag
        self.credential_factory = credential_factory or _default_credentials
        self.identity_factory = identity_factory or self._default_identity
        self.sheets_factory = sheets_factory or (
            lambda credentials: _OfficialSheetsAdapter(_default_discovery("sheets", "v4", credentials))
        )
        self.drive_factory = drive_factory or (
            lambda credentials: _OfficialDriveAdapter(_default_discovery("drive", "v3", credentials))
        )
        self._clients_by_binding: dict[UUID, _Clients] = {}
        self._preflight_ok: set[UUID] = set()

    @staticmethod
    def _default_identity(credentials: Any) -> str:
        email = getattr(credentials, "service_account_email", None)
        if not email:
            raise GoogleIntegrationError(
                "IDENTITY_UNAVAILABLE", "Google credential identity could not be established"
            )
        return str(email)

    def _clients(self, binding: GoogleBindingRecord) -> _Clients:
        existing = self._clients_by_binding.get(binding.binding_id)
        if existing:
            return existing
        credentials = self.credential_factory(binding.credential_id)
        clients = _Clients(
            self.identity_factory(credentials).strip().lower(),
            self.sheets_factory(credentials),
            self.drive_factory(credentials),
        )
        self._clients_by_binding[binding.binding_id] = clients
        return clients

    def preflight(self, binding: GoogleBindingRecord) -> GooglePreflight:
        clients = self._clients(binding)
        allowed_identities = {self.expected_owner_email}
        if self.automation_email:
            allowed_identities.add(self.automation_email)
        identity_ok = clients.identity in allowed_identities
        snapshot = clients.sheets.read_contract(binding.spreadsheet_id)
        contract_ok = snapshot.contract_version == binding.contract_version
        allowed_permissions = set(allowed_identities)
        permissions = clients.drive.list_permissions(binding.spreadsheet_id)
        sharing_ok = True
        for permission in permissions:
            email = str(permission.get("email", permission.get("emailAddress", ""))).lower()
            if permission.get("type") in {"anyone", "domain"} or email not in allowed_permissions:
                sharing_ok = False
                break
            if permission.get("role") not in {"owner", "writer"}:
                sharing_ok = False
                break
        codes = tuple(
            code
            for ok, code in (
                (identity_ok, "IDENTITY_MISMATCH"),
                (contract_ok, "CONTRACT_MISMATCH"),
                (sharing_ok, "UNEXPECTED_SHARING"),
            )
            if not ok
        )
        result = GooglePreflight(identity_ok and contract_ok and sharing_ok, identity_ok, contract_ok, sharing_ok, codes)
        if result.ok:
            self._preflight_ok.add(binding.binding_id)
        else:
            self._preflight_ok.discard(binding.binding_id)
        return result

    def read_contract(self, binding: GoogleBindingRecord) -> WorkbookSnapshot:
        return self._clients(binding).sheets.read_contract(binding.spreadsheet_id)

    def pull_requests(self, binding: GoogleBindingRecord, checkpoint: str) -> RemoteBatch:
        value = self._clients(binding).sheets.pull_requests(binding.spreadsheet_id, checkpoint)
        return RemoteBatch(tuple(value["rows"]), str(value["cursor"]), str(value["historical_digest"]))

    def pull_access_events(self, binding: GoogleBindingRecord, checkpoint: str) -> RemoteBatch:
        value = self._clients(binding).sheets.pull_access_events(binding.spreadsheet_id, checkpoint)
        return RemoteBatch(tuple(value["rows"]), str(value["cursor"]), str(value["historical_digest"]))

    def publish_results(
        self, binding: GoogleBindingRecord, results: tuple[Mapping[str, Any], ...]
    ) -> PublicationReceipt:
        self._assert_write_ready(binding)
        value = self._clients(binding).sheets.publish_results(binding.spreadsheet_id, results)
        return PublicationReceipt(value["revision_id"], value["verified"], value["row_counts"], value["hashes"])

    def publish_projection(
        self, binding: GoogleBindingRecord, bundle: Mapping[str, Any]
    ) -> PublicationReceipt:
        self._assert_write_ready(binding)
        value = self._clients(binding).sheets.publish_projection(binding.spreadsheet_id, bundle)
        return PublicationReceipt(value["revision_id"], value["verified"], value["row_counts"], value["hashes"])

    def _assert_write_ready(self, binding: GoogleBindingRecord) -> None:
        if not self.allow_writes or not self.cli_write_flag:
            raise GoogleIntegrationError("WRITE_GATE_CLOSED", "Google writes are disabled")
        if not binding.enabled or not binding.write_enabled:
            raise GoogleIntegrationError("BINDING_WRITE_DISABLED", "Binding writes are disabled")
        if binding.binding_id not in self._preflight_ok:
            raise GoogleIntegrationError("PREFLIGHT_REQUIRED", "Successful preflight is required")
