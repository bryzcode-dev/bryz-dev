# ProjectOS Phase 2 Google Interface — Design Specification

**Date:** 2026-09-26  
**Status:** Written specification awaiting user review  
**Program:** ProjectOS  
**Depends on:** ProjectOS Phase 1 release candidate `267a035`  
**Parent architecture:** `docs/superpowers/specs/2026-09-26-projectos-contextos-enhancement-design.md`  
**Portable implementation guide:** `docs/PHASE2_CLAUDE_IMPLEMENTATION_AND_TROUBLESHOOTING.md`

## 1. Purpose

Phase 2 adds the staged Google interface to ProjectOS while preserving the Phase 1 rule that local SQLite is the single source of truth. It produces a deployable Google Sheet contract, a Google Apps Script web application, and a Mac-side synchronization service. The phase is implemented and verified against fake Google services and fixtures. It does not create, modify, share, or deploy a live Google resource.

The result must be portable to a different Mac and understandable by a Claude implementation session that has no access to the design conversation. Repository files define the contract; machine paths, account identifiers, Sheet IDs, deployment IDs, and credentials remain external configuration.

## 2. Phase boundary

### 2.1 Included

- SQLite migration `0002` for canonical users and Google synchronization state.
- A versioned Google Sheet workbook contract and idempotent bootstrap planner.
- A fake Google gateway for all automated tests.
- A real Google gateway that remains inert until explicitly configured and write-enabled.
- Immutable change requests, local authorization revalidation, optimistic conflicts, durable receipts, and retry-safe publication.
- A GAS web application with server-side Owner/Admin/User enforcement.
- The Context OS Native visual direction: dark graphite, cobalt action color, teal status accents, accessible contrast, responsive layouts, keyboard operation, and plain-language errors.
- Portable configuration, diagnostic bundles, recovery procedures, and a Claude implementation/troubleshooting guide.

### 2.2 Excluded

- Creating or changing a live Google Sheet, GAS project, deployment, Drive permission, OAuth client, service account, or GCP resource.
- Installing the two-hour `launchd` scheduler.
- Installing or activating the Context OS ProjectOS skill.
- Modifying live Context OS configuration or its database.
- Inspecting or migrating the existing Looker Git/Sheet system.
- Treating the Sheet, GAS application, or claimed client role as authoritative.

Those operations require later reviewed phases and fresh machine/account preflight.

## 3. Non-negotiable invariants

1. `projectos.db` is authoritative. Google rows are projections, proposals, or status records.
2. Google Apps Script never connects directly to SQLite.
3. The spreadsheet is shared only with the Owner and the configured automation identity. Admin and User roles access data through the GAS web application, not direct Sheet sharing.
4. Every GAS data operation authorizes on the server. Hidden buttons are never an authorization control.
5. PRIVATE projects and their existence are Owner-only. Non-Owners receive no private row, child record, relationship, search result, count, analytics value, audit item, or distinguishing error.
6. Machine-local paths, credential references, owner notes, configuration, sync diagnostics, and raw audit records are Owner-only even when their project is PUBLIC.
7. Secret values are prohibited from SQLite domain fields, Sheet cells, request payloads, GAS properties returned to clients, logs, fixtures, exports, and diagnostic bundles.
8. The protected Owner identity cannot be created, replaced, removed, demoted, or disabled by Sheet content or ordinary web-app actions.
9. Synchronization is single-writer, durable, retry-safe, and fail-closed. No checkpoint advances past unrecorded work.
10. Google writes require an explicit runtime write-enable control in addition to valid credentials and identifiers.

## 4. Deployment topology and portability

Phase 2 adds source code to the ProjectOS repository and runtime state to a machine-local ProjectOS home. No shared source file contains an absolute home-directory path.

The runtime resolves locations in this order:

1. explicit CLI argument;
2. `PROJECTOS_HOME` or another documented ProjectOS environment variable;
3. the macOS default `~/Library/Application Support/ProjectOS`.

The resolved runtime contains:

```text
config/projectos.toml       Non-secret machine and Google identifiers
data/projectos.db           SQLite SSOT
locks/google-sync.lock      Single-writer process lock
logs/                       Redacted structured logs
diagnostics/                User-requested redacted bundles
backups/                    Verified local snapshots and manifests
```

Credential values are resolved at runtime through an external provider such as macOS Keychain or Google Application Default Credentials. `credential_references` stores only the provider and safe locator.

## 5. Phase 2 SQLite migration

Migration `0002` extends rather than replaces Phase 1.

### 5.1 `users`

Canonical User Manifest records:

- `user_id` UUID primary key;
- normalized lowercase `email` unique;
- `display_name`;
- `role` constrained to `OWNER`, `ADMIN`, or `USER`;
- `active` boolean;
- `notes` safe Owner-only text;
- `version`, `created_at`, `updated_at`, and `last_access_at`;
- provenance and lifecycle status.

Exactly one active Owner is seeded from protected local onboarding configuration. Repository methods reject attempts to create another Owner or disable, delete, replace, or demote the protected Owner.

### 5.2 `google_bindings`

One row per configured workbook/environment:

- binding UUID and environment name;
- spreadsheet ID and safe display name;
- Sheet contract version;
- optional GAS script/deployment IDs;
- sharing policy fixed to `OWNER_ONLY` for Phase 2;
- enabled and write-enabled flags;
- last preflight, publication revision, and status;
- safe credential-reference UUID;
- version, timestamps, and provenance.

No credential value is stored.

### 5.3 Change-request extensions

Migration `0002` adds these fields to the existing `change_requests` table:

- request schema version;
- operation (`CREATE`, `UPDATE`, `ARCHIVE`);
- actor role claimed by GAS;
- client request hash;
- workbook binding and source row;
- observed remote timestamp;
- result code and safe result message;
- publication revision that returned the outcome.

The request UUID and normalized request hash are unique. A replay with the same UUID and hash returns the durable prior result. A reused UUID with different content is rejected as tampering.

### 5.4 `remote_request_receipts`

Receipts preserve remote ingestion independently of the current Sheet row:

- receipt UUID;
- binding and request UUID;
- normalized payload hash;
- raw payload after secret validation and canonical JSON normalization;
- source row and observed timestamp;
- processing status;
- associated local request/conflict/audit IDs;
- processed and published timestamps.

Receipts make retries safe when SQLite commits succeed but Google publication fails.

### 5.5 `remote_access_receipts`

Access receipts contain event UUID, binding, normalized actor email, accessed timestamp, payload hash, source row, observed timestamp, processing status, and processed timestamp. Event UUID and hash are unique. Replays are idempotent; reused UUIDs with different content are rejected. Accepted timestamps update canonical `users.last_access_at` only when later than the stored value.

### 5.6 `projection_revisions`

Publication evidence includes:

- revision UUID;
- binding UUID;
- schema version;
- snapshot hash and entity counts;
- state (`STAGED`, `ACTIVE`, `FAILED`, `SUPERSEDED`);
- started, verified, activated, and failed timestamps;
- safe error code and details.

Only a fully verified revision becomes active.

### 5.7 Existing operational tables

`sync_runs`, `sync_checkpoints`, `conflicts`, `audit_events`, and `backup_manifests` remain authoritative. Migration `0002` adds indexes and columns without discarding Phase 1 history.

## 6. Google workbook contract

The contract is versioned independently from the SQLite schema. The initial Phase 2 workbook contract is `1`.

### 6.1 Tabs

| Tab | Purpose | GAS exposure |
|---|---|---|
| `_ProjectOS_Schema` | Contract version, workbook identity, active projection revision, tab/header hashes | Owner diagnostics only |
| `_ProjectOS_Sync` | Last run, state, safe counts, checkpoint, publication status | Role-safe summary |
| `Users` | Canonical User Manifest projection | Owner full; current caller may receive only their own role summary |
| `Projects` | Canonical project projection | PUBLIC for active callers; PRIVATE Owner-only |
| `Locations` | Project locations | Drive links may be role-safe; machine paths Owner-only |
| `Resources` | Sheets, folders, scripts, repos, datasets, services | Filtered by project and field policy |
| `Deployments` | Development/production deployment metadata | PUBLIC project subset for Admin/User; sensitive IDs role-filtered |
| `Connections` | Relationship graph edges | Returned only when both visible endpoints remain visible |
| `Credential_References` | Safe credential locator metadata | Owner-only; never contains secrets |
| `Change_Requests` | Immutable proposals and sync results | GAS append/result lookup; Sheet direct use Owner-only |
| `Owner_Drafts` | Owner-editable staging rows converted into immutable requests by a signed-in Owner action | Owner-only; never canonical |
| `Access_Events` | Immutable GAS access heartbeats used to update canonical `last_access_at` | No direct web-app exposure |
| `Conflicts` | Version conflicts and Owner resolution state | Owner-only |
| `Audit_Summary` | Redacted high-level activity | Owner-only in Phase 2 |

All tabs include a contract-controlled header row. Bootstrap refuses to silently repurpose an unknown or mismatched tab.

### 6.2 Workbook access

User Manifest membership does not grant spreadsheet permission. Phase 2 preflight requires that direct workbook access is limited to:

- the protected Owner; and
- an explicitly configured automation identity when one is required.

Unexpected viewers, commenters, editors, link-sharing, or domain-wide sharing cause Google write operations to fail closed. The real gateway may use the Drive API only to inspect and report permissions; it does not remove access automatically in Phase 2.

### 6.3 Projection rows

Every projection row includes:

- `projection_revision`;
- stable entity ID;
- canonical entity version;
- lifecycle status;
- publish timestamp;
- entity fields permitted by the tab contract;
- row hash.

GAS reads only the active revision named in `_ProjectOS_Schema`. While `_ProjectOS_Sync.state` is `PUBLISHING`, the application continues reading the prior active revision or returns a retryable maintenance response. It never reads staged rows as canonical.

### 6.4 User Manifest columns

`Users` contains:

```text
user_id, email, display_name, role, active, added_at, updated_at,
last_access_at, notes, version, projection_revision, row_hash
```

`notes` and complete user listings are Owner-only through GAS.

GAS appends a rate-limited immutable `Access_Events` row after successful authorization. The local service validates the actor against canonical users and advances `last_access_at` monotonically. A missing or failed heartbeat does not weaken access control or block the request that was already authorized.

### 6.5 Change request columns

`Change_Requests` contains:

```text
request_id, request_schema_version, actor_email, actor_role_claim,
entity_type, entity_id, operation, base_version, changes_json,
submitted_at, client_request_hash, gas_deployment_id, status,
result_code, result_message, current_version, resolved_at,
publication_revision
```

The request payload consists of columns through `client_request_hash`. GAS appends a complete payload once under `LockService`. ProjectOS writes only result columns. A changed payload after receipt is rejected and audited.

Canonical JSON for request hashing is UTF-8 JSON with recursively sorted object keys, array order preserved, no insignificant whitespace, and JSON-native booleans/null/numbers. `client_request_hash` is lowercase hexadecimal SHA-256 over that canonical payload excluding the hash and result columns. Python and GAS share cross-language golden fixtures.

The Owner may edit `Owner_Drafts` directly in the Sheet. Draft rows have contract-controlled fields but no authority or canonical effect. A bound Apps Script menu action verifies the signed-in caller is the protected Owner, validates the selected draft, appends an immutable `Change_Requests` row, and marks the draft with its request UUID. Direct edits to projection, request, result, conflict, or schema tabs are never interpreted as canonical changes.

## 7. Authorization and field policy

### 7.1 Caller identity

GAS normalizes `Session.getActiveUser().getEmail()` to lowercase. Blank, malformed, unlisted, or inactive identities receive a generic access-denied response and no project information. Deployment configuration must require sign-in. The protected Owner email is stored in Script Properties for bootstrap comparison but is never sent to unauthorized clients.

### 7.2 Role capabilities

| Capability | Owner | Admin | User |
|---|---:|---:|---:|
| View PUBLIC projects and safe child fields | Yes | Yes | Yes |
| Propose permitted PUBLIC changes | Yes | Yes | No |
| View or change PRIVATE records | Yes | No | No |
| View machine paths, owner notes, credentials, conflicts, audit, or config | Yes | No | No |
| Change project visibility | Yes | No | No |
| Manage users or protected Owner | Owner may manage non-Owner users; protected Owner immutable | No | No |
| Resolve conflicts | Yes | No | No |
| Use admin menu | Yes | No | No |

### 7.3 Admin field policy

For PUBLIC projects, Admin may propose:

- project name, description, status, and tags;
- safe Drive/Sheet/resource names, URLs, environment, role, status, and allowlisted metadata; stable external IDs are set at creation and are immutable through Admin updates;
- deployment labels, environments, URLs, and safe notes;
- connection type, method, business purpose, and safe notes.

Admin may not propose user changes, visibility changes, machine-local paths, Context OS registration changes, credential references, protected Owner fields, sync configuration, raw audit changes, or conflict resolutions. Attempts are rejected locally even if GAS mistakenly accepted them.

### 7.4 Side-channel protection

Filtering occurs before serialization, search, aggregation, and graph construction. Unauthorized callers receive the same not-found response for nonexistent and invisible entities. Counts exclude invisible entities. A connection is returned only when all referenced endpoints and included child fields are visible to the caller.

## 8. Change-request and conflict protocol

### 8.1 GAS submission

GAS performs a preliminary role and field check for user experience, creates a UUID, canonicalizes the proposed changes, computes the request hash, and appends one row. It returns the request UUID and `PENDING`, not a claim that SQLite changed.

### 8.2 Local validation order

The local service validates in this order:

1. request schema and hash;
2. duplicate/tampered UUID behavior;
3. normalized actor identity against canonical `users`;
4. active role and project visibility;
5. entity type, operation, and field allowlist;
6. stable identifiers and relationship visibility;
7. secret-material rejection;
8. base version;
9. domain invariants;
10. transactional mutation, audit, and durable receipt result.

The role claim from GAS is evidence only. Canonical local role wins.

### 8.3 Result classes

- `ACCEPTED` — mutation committed and audited.
- `CONFLICT` — base version differs; no mutation committed.
- `REJECTED_AUTHORIZATION` — caller or field not permitted.
- `REJECTED_VALIDATION` — schema or domain validation failed.
- `REJECTED_TAMPERED` — request UUID reused with different content or received payload changed.
- `RETRYABLE_REMOTE_FAILURE` — local result is durable but remote result publication failed.

Safe result messages never disclose invisible current values.

### 8.4 Conflict resolution

Only Owner can create a resolution request. Resolution references the conflict UUID and chooses:

- keep canonical current state;
- accept the entire proposal against the now-current version; or
- merge an explicit permitted field subset into a new version.

Every resolution is a new audited transaction. Existing request and conflict evidence remains immutable.

## 9. Mac-side synchronization engine

### 9.1 Service interfaces

The implementation defines narrow interfaces equivalent to:

```text
GoogleGateway.preflight(binding) -> GooglePreflight
GoogleGateway.pull_requests(binding, checkpoint) -> RemoteRequestBatch
GoogleGateway.pull_access_events(binding, checkpoint) -> RemoteAccessBatch
GoogleGateway.publish_results(binding, results) -> PublicationReceipt
GoogleGateway.publish_projection(binding, bundle) -> PublicationReceipt
GoogleGateway.read_contract(binding) -> WorkbookContractState

GoogleSyncService.plan(binding_id) -> SyncPlan
GoogleSyncService.run(binding_id, trigger) -> SyncRunResult
GoogleSyncService.status(binding_id) -> SyncStatus
```

The fake and real gateways implement the same protocol. Domain services never import Google client libraries.

### 9.2 Locking

All triggers acquire the same non-blocking machine-local file lock. The lock records safe PID, start time, trigger, and run UUID for diagnostics. A concurrent invocation exits as a structured health/unavailable result and performs no remote or canonical write.

### 9.3 Sync sequence

1. Acquire the process lock.
2. Open SQLite and run doctor/schema checks.
3. Load and validate the binding, credential reference, and local User Manifest.
4. Run Google identity, workbook, contract, and sharing preflight.
5. Record a `sync_run` with trigger and starting checkpoint.
6. Pull requests and access events after the durable checkpoint, while verifying the historical payload-region digest against prior receipts.
7. Persist normalized receipts before processing.
8. Process each new request deterministically, apply valid monotonic access timestamps, and record durable results.
9. Build a role-safe projection bundle from one SQLite read snapshot.
10. Mark a projection revision `STAGED` and publish staged rows/results.
11. Read back counts and hashes.
12. Activate the revision only when verification matches.
13. Publish sync status and advance the checkpoint inside a final local transaction.
14. Release the lock and return a structured summary.

If interruption occurs after local mutation but before publication, the next run recognizes durable receipts and republishes without applying mutations twice.

### 9.4 Publication behavior

Publication uses a new revision UUID. The gateway writes staged projection rows, verifies row/header hashes and counts, updates request results, and changes the active-revision pointer last. A failed verification leaves the previous revision active and marks the new revision failed. Cleanup of superseded revisions is a separate explicit maintenance operation and is not required for correctness.

### 9.5 Checkpoints

The checkpoint identifies the last fully published remote sequence/revision, not merely the last pulled row. It advances only after local results and the projection revision are durable and the active-revision update verifies successfully.

## 10. Google gateway implementations

### 10.1 Fake gateway

The fake gateway stores workbook state in memory or deterministic JSON fixtures and supports injected failures at each sync boundary. It is the required gateway for unit, integration, retry, authorization, and conflict tests.

### 10.2 Real gateway

The real gateway uses official Google Sheets and Drive APIs through an optional dependency set. Importing or testing the ProjectOS core does not require Google packages. It supports read-only preflight without write enablement.

Writes require all of:

- a configured binding;
- a resolved external credential;
- successful identity and sharing preflight;
- matching workbook contract;
- binding `enabled=true`;
- binding `write_enabled=true`;
- a CLI invocation that explicitly selects the Google gateway and permits writes.

Missing any gate produces no Google mutation.

## 11. GAS web application

### 11.1 Server modules

The GAS source is separated into modules for:

- application entry and template rendering;
- caller identity and authorization;
- workbook contract validation;
- role-safe query and serialization;
- change-request construction and append;
- Owner draft validation/submission and access-event heartbeat append;
- Owner-only user administration requests;
- conflict and sync-status views;
- safe logging and error mapping.

No server function accepts a client-supplied role as authority.

### 11.2 User experience

The application provides:

- project list, filters, search, status, type, and visibility indicators;
- project detail with permitted locations, resources, deployments, and connections;
- relationship/impact view filtered before graph serialization;
- edit forms for permitted fields that submit change requests;
- pending, accepted, conflict, and rejected request status;
- Owner-only Users, Conflicts, Audit Summary, and Settings navigation;
- clear empty, maintenance, access-denied, retryable, and stale-version states.

Admin and User never see the admin menu. User never sees edit actions. These presentation rules supplement, but do not replace, server authorization.

### 11.3 Visual system

The Context OS Native visual system uses:

- graphite page and surface colors;
- cobalt primary actions and focus indicators;
- teal healthy/synchronized accents;
- amber warnings and red destructive/error states;
- a compact desktop information hierarchy with responsive single-column behavior;
- semantic HTML, labeled controls, visible keyboard focus, sufficient contrast, and touch targets at least 44 CSS pixels where applicable.

No external font or image dependency is required for core operation.

## 12. Configuration and secret handling

The non-secret TOML configuration records machine ID, environment, database path override, binding UUID, spreadsheet ID, expected owner email, contract version, credential reference UUID, and feature gates. It may be generated from an example template but is not committed with real identifiers.

Protected GAS configuration uses Script Properties for spreadsheet ID, Owner email, contract version, environment, and deployment identifier. Properties containing actual credentials are prohibited. GAS client responses never include Script Properties.

All logs use structured event codes and redacted fields. Diagnostic bundles include versions, hashes, safe IDs, health results, tab/header comparisons, lock metadata, and recent safe error codes; they exclude access tokens, cookies, authorization headers, raw credentials, private rows, and full request payloads.

## 13. Failure and recovery behavior

| Failure | Required behavior |
|---|---|
| Missing/invalid Google credential | Fail preflight; no remote or SQLite domain write |
| Wrong spreadsheet or contract version | Fail closed with expected/observed safe metadata |
| Unexpected workbook sharing | Block Google writes and report permission categories |
| Header/tab drift | Produce a non-mutating repair plan; never silently remap columns |
| Concurrent sync | Second process exits without work |
| Secret-like request | Reject before receipt payload persistence |
| Unauthorized/private request | Reject generically; no private-value disclosure |
| Stale base version | Create conflict; preserve canonical row |
| SQLite commit succeeds, Google result fails | Keep durable receipt/result; retry publication only |
| Projection write or verification fails | Keep prior revision active; do not advance checkpoint |
| GAS caller email blank | Deny all data |
| Owner manifest tampering | Reject and audit; protected Owner remains active |
| Newer SQLite or workbook schema | Fail closed; require compatible software/migration |

Before any later live activation, ProjectOS creates and verifies a SQLite backup. Workbook repair or bootstrap produces a dry-run plan and exportable backup instructions; destructive tab replacement is not part of Phase 2.

## 14. Testing and acceptance

### 14.1 Python tests

Tests use temporary SQLite databases and the fake gateway to cover:

- migration and protected Owner invariants;
- workbook contract planning and drift detection;
- all role/visibility/field combinations;
- no PRIVATE leakage through search, counts, errors, graph edges, or request results;
- accepted, conflicting, unauthorized, invalid, tampered, replayed, and interrupted requests;
- lock contention;
- every failure injection point before and after local commit;
- staged publication hash/count verification and active-revision switching;
- checkpoint rules and retry idempotency;
- redaction and diagnostic-bundle safety;
- real-gateway imports remaining optional.

### 14.2 GAS tests

GAS logic is structured so authorization, filtering, request hashing, field allowlists, error mapping, and serialization run under local JavaScript tests with Apps Script services replaced by fakes. Static checks prohibit client-callable functions from returning unfiltered Sheet rows or trusting a client role.

### 14.3 Contract fixtures

Repository fixtures include:

- an empty compliant workbook;
- populated PUBLIC and PRIVATE projects;
- Owner/Admin/User/inactive identities;
- malformed and drifted headers;
- request lifecycle examples;
- Owner draft and access-event examples;
- conflicts and retry scenarios;
- expected role-safe serialized responses.

Fixtures contain invented identifiers and no usable credentials.

### 14.4 Completion gates

Phase 2 implementation is complete only when:

1. all Phase 1 and Phase 2 tests pass;
2. the wheel builds offline except for explicitly optional Google dependencies;
3. GAS tests and static authorization checks pass;
4. a fake-gateway end-to-end run accepts, rejects, conflicts, publishes, interrupts, and retries correctly;
5. diagnostic bundles pass secret and PRIVATE-data scans;
6. a clean-room Mac installation can follow the Claude guide without knowledge of the original machine;
7. real Google write gates default to disabled;
8. verification evidence states that no live Google or Context OS resource changed.

## 15. Deliverables

Phase 2 implementation will deliver:

- migration `0002` and canonical user/binding/sync repositories;
- workbook contract definitions, fixtures, bootstrap planner, and drift diagnostics;
- fake and real Google gateway packages;
- authorization, request-processing, projection, conflict, and sync services;
- JSON CLI commands for contract planning, Google preflight, sync plan/run/status, conflicts, and diagnostics;
- modular GAS server/client source with tests;
- example portable configuration and redaction-safe diagnostics;
- implementation, operations, recovery, and verification documentation;
- the machine-portable Claude guide referenced above.

The implementation plan must keep Google writes and live deployment as explicit later gates. It must not reinterpret approval of this specification as authorization to create Google resources.
