# ProjectOS Phase 1 Schema

Schema version: `1`

SQLite is the canonical store. All IDs are stable text UUIDs unless an external provider supplies the identity. Timestamps are UTC ISO-8601 strings. Mutable canonical entities use positive integer versions for optimistic concurrency.

## Catalog entities

| Table | Purpose | Stable identity / important rules |
|---|---|---|
| `projects` | Canonical project record | UUID, unique slug, optional unique discovery `source_key`; PUBLIC or PRIVATE |
| `project_locations` | Machine and Drive locations | Project + machine + type + normalized path + folder ID |
| `resources` | Sheets, folders, scripts, repos, datasets, and other assets | Project + provider + type + external ID; URL is mutable metadata |
| `deployments` | Development, staging, production, or other deployments | Project + environment + external deployment ID |
| `connections` | Directed or bidirectional links between projects/resources | At least one source and target endpoint; service blocks cross-visibility links |
| `credential_references` | Safe locators and ownership metadata | Provider + label + storage system + storage reference; no credential value column |
| `credential_usage` | Credential-to-project/resource usage map | Credential + project + optional resource + purpose |
| `looker_assets` | Reserved canonical Looker file/model inventory | Project + asset type + file path + name |
| `looker_analytics` | Reserved versioned analysis output | Source run plus JSON analytic value |

## Synchronization and review entities

| Table | Purpose |
|---|---|
| `change_requests` | Reserved remote edit proposals with base versions |
| `conflicts` | Reserved current/proposed conflict snapshots and resolutions |
| `sync_runs` | Reserved sync execution history |
| `sync_checkpoints` | Reserved incremental synchronization cursors |
| `discovery_runs` | Adapter execution, unique source run, status, and summary |
| `discovery_findings` | Hashed candidate/error findings with evidence and provenance |

Discovery findings are immutable evidence until resolution fields change. A unique `(finding_key, content_hash)` prevents duplicate candidates. Applying a candidate creates canonical catalog records inside an outer transaction; rejecting it preserves the historical finding.

## Governance, recovery, and integration entities

| Table | Purpose |
|---|---|
| `audit_events` | Actor, event, entity, redacted payload, timestamp |
| `extension_adoptions` | Reserved Context OS adoption and compatibility state |
| `backup_manifests` | Locally created backup manifest, snapshot, hash, size, and schema evidence |
| `schema_migrations` | Applied migration versions |

## Invariants enforced in Phase 1

- SQLite foreign keys are enabled on every ProjectOS connection.
- Schema versions newer than the running code fail closed.
- Multi-record candidate application uses nested SQLite savepoints under one outer transaction.
- Project updates and archives require the expected version.
- PRIVATE resources cannot be exposed by a connection to a PUBLIC project.
- Credential material is prohibited recursively by sensitive key and recognizable secret pattern.
- Backup restore never replaces an existing target without explicit `replace=True`/`--replace`.
- Corrupt, changed, missing, foreign-key-invalid, or newer-schema snapshots fail before replacement.

## Deferred schema behavior

The version-1 schema reserves Google synchronization, change request, conflict, adoption, and Looker tables so later phases can build against explicit boundaries. Phase 1 does not yet implement their network workflows. Google User Manifest roles remain a later server-side authorization requirement; they are not represented as trusted local users in this release.
