# ProjectOS Phase 2 Schema Reference

SQLite schema version `2` is canonical. Migration `0001.sql` creates the local catalog; `0002.sql` adds identity, Google binding, immutable remote receipt, and revisioned synchronization state. `ProjectOSDatabase.initialize()` applies missing migrations transactionally and fails closed when a database is newer than the code.

## Core catalog from schema 1

| Area | Tables | Purpose |
|---|---|---|
| Projects | `projects`, `project_locations`, `resources`, `deployments`, `connections` | Stable project identity, per-machine paths/folders, external assets, GAS prod/dev deployments, and directional relationships |
| Credentials | `credential_references`, `credential_usage` | Safe locators and impact mapping only; secret values are rejected |
| Looker foundation | `looker_assets`, `looker_analytics` | Reserved local tracking for a later inspected migration; Phase 2 does not cut over the existing tracker |
| Workflow | `change_requests`, `conflicts`, `sync_runs`, `sync_checkpoints` | Durable change/sync state |
| Evidence | `audit_events`, `discovery_runs`, `discovery_findings`, `extension_adoptions`, `backup_manifests` | Append-oriented audit, Context OS discovery review, adoption records, and verified backup metadata |

All canonical domain records use UUID identity, version checks, status/archive semantics, timestamps, and foreign keys. SQLite foreign keys are enabled on every connection.

## Schema 2 additions

### `users`

Canonical role manifest with case-insensitive unique email, `OWNER|ADMIN|USER`, active state, protected-owner flag, notes, provenance, version, and access timestamps. A partial unique index permits only one active Owner. Repository rules additionally prevent replacing, disabling, or demoting the protected Owner.

### `google_bindings`

Maps an environment to one workbook contract and safe credential reference. It records spreadsheet/GAS identifiers, `OWNER_ONLY` sharing policy, enabled/write-enabled gates, preflight/publication status, provenance, and version. The binding never stores credential material.

### Extended `change_requests`

Schema 2 adds request schema version, `CREATE|UPDATE|ARCHIVE`, role claim, canonical client hash, binding/source observation, safe result code/message, conflict version, and publication revision. The UUID/hash pair detects replay and tampering; historical requests are immutable.

### `remote_request_receipts`

One durable receipt per binding/request UUID and payload hash. It links the remote observation to the local request, conflict, and audit event. Replays return the stored outcome; changed content under a reused UUID is rejected as tampering.

### `remote_access_receipts`

Idempotent access-event receipts keyed by event UUID and binding/hash. Repeated events cannot create duplicate access mutations.

### `projection_revisions`

Tracks `STAGED|ACTIVE|FAILED|SUPERSEDED` workbook snapshots with snapshot hash, safe entity counts, verification/activation times, and safe error details. A partial unique index allows one active revision per binding.

### Extended sync tables

`sync_runs` gains binding, starting/ending checkpoints, and safe error code. `sync_checkpoints` gains binding linkage. Checkpoints advance only after result publication and verified projection activation.

## Workbook contract version 1

The Sheet is a proposal/projection surface with 14 exact tabs:

| Tab | Exposure | Direction |
|---|---|---|
| `_ProjectOS_Schema` | Owner only | Active revision and contract metadata |
| `_ProjectOS_Sync` | Role-safe summary | Sync status projection |
| `Users` | Current caller or Owner | SQLite projection |
| `Projects` | Filtered before serialization | SQLite projection |
| `Locations` | Filtered through project visibility | SQLite projection |
| `Resources` | Filtered through project visibility | SQLite projection |
| `Deployments` | Filtered through project visibility | SQLite projection |
| `Connections` | Visible only when both endpoints are visible | SQLite projection |
| `Credential_References` | Owner only | Safe references only |
| `Change_Requests` | Append-only proposals/results | Sheet to SQLite, then safe result publication |
| `Owner_Drafts` | Owner only | Draft proposals |
| `Access_Events` | Internal | Append-only observation |
| `Conflicts` | Owner only | SQLite projection |
| `Audit_Summary` | Owner only | Safe summary projection |

Header order is part of the contract. Each projected domain row includes a projection revision and row hash where defined. GAS reads only the active verified revision.

## Source-of-truth invariants

- SQLite is the only system of record.
- Sheet edits are untrusted requests, never direct canonical mutations.
- PRIVATE data and Owner-only fields are filtered before serialization, counting, search, graph traversal, and error handling.
- Credential values, OAuth material, private keys, cookies, and tokens are never schema fields.
- A connection cannot broaden the visibility of either endpoint.
- Request, receipt, mutation, conflict, and audit history is not rewritten.
- The previous workbook revision remains active until a new revision passes read-back verification.
