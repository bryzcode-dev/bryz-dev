# ProjectOS as a Context OS Enhancement — Architecture Design

**Date:** 2026-09-26  
**Status:** Approved conversational design; written specification awaiting user review  
**Program:** ProjectOS  
**Controlling platform:** Context OS V3

## 1. Purpose

ProjectOS is a separately buildable project-management and systems-inventory product that Context OS can adopt as an optional enhancement. It gives Context OS deterministic tools for locating projects, understanding their Google and local assets, tracking deployments and connections, mapping safe credential references, synchronizing a remote Google interface, and later managing an existing Looker Git tracking workflow.

ProjectOS is not a replacement for Context OS. Context OS remains the controlling platform for skill discovery, Executive Assistant access, health orchestration, maintenance, and extension lifecycle. ProjectOS owns its domain database, schema migrations, discovery rules, synchronization protocol, Google Apps Script application, and ProjectOS-specific analytics.

The product serves three related needs:

1. Maintain a canonical inventory of GAS, GCP-connected Sheet, Looker, Git, local-folder, and other tracked projects.
2. Provide a private GAS web application and Google Sheet through which authorized users can view or propose edits to that inventory.
3. Extend Context OS with ProjectOS-aware discovery, queries, maintenance, and an on-demand synchronization skill.

## 2. Architectural decisions

### 2.1 System of record

`projectos.db`, a local SQLite database on the enrolled host, is the single source of truth.

The Google Sheet is a synchronized projection and change-request surface. The GAS web app reads the Sheet-facing projection and writes proposed changes. A Sheet or web-app edit is not canonical until the local ProjectOS synchronization service validates it and commits it to SQLite. After every accepted transaction, ProjectOS republishes canonical state to the Sheet.

There is no direct network path from Google Apps Script to the local SQLite file.

### 2.2 Product boundary

ProjectOS uses a separate database and stable adapter rather than adding tables to the Context OS database.

- Context OS owns extension enablement, skill loading, EA tool exposure, maintenance invocation, compatibility checks, and extension health.
- ProjectOS owns `projectos.db`, schema migrations, project discovery, Google synchronization, authorization-domain rules, and ProjectOS analytics.
- Context OS consumes ProjectOS only through versioned CLI/adapter contracts. It must not query ProjectOS tables directly.
- Removing ProjectOS must not damage the Context OS database or original project ledger.

### 2.3 Deployment topology

ProjectOS follows the existing Context OS topology:

- Shared, portable extension definitions may live under the shared Context OS tree.
- High-frequency runtime state, the SQLite database, locks, offsets, logs, Google credentials, and transient files stay in the machine-local runtime.
- The two-hour scheduler is installed only on an explicitly enrolled machine.
- Machine-specific absolute paths are stored as machine-scoped records, never embedded in shared skill definitions.

### 2.4 Safety posture

Installation, migration, adoption, and cutover are staged and fail closed. Live Context OS configuration and legacy Looker automation remain unchanged until staged verification and rollback rehearsal pass. Backups and legacy archives are retained unless the Owner explicitly requests their deletion.

## 3. System components

### 3.1 ProjectOS core

The local core provides:

- versioned SQLite schema migrations;
- repositories and domain services for projects and related entities;
- discovery adapters for local files, Context OS manifests, Git repositories, GAS metadata, Sheets, Drive folders, GCP connections, and Looker artifacts;
- a versioned CLI and structured JSON output;
- import/export, backup, restore, doctor, and migration operations;
- audit, provenance, synchronization, and conflict services.

All state-changing commands support deterministic validation and structured error results. Operations that change multiple records run inside SQLite transactions.

### 3.2 Google synchronization service

The host-side service is the only component that reconciles SQLite with Google Sheets. It is invoked by either:

- the native scheduler every two hours (`launchd` on macOS or Windows Task Scheduler on Windows); or
- activation of the Context OS ProjectOS skill.

Both triggers call the same idempotent command and acquire the same process lock. Overlapping runs are not allowed.

### 3.3 Google Sheet

The Sheet stores:

- the current publishable projection of canonical ProjectOS records;
- pending change requests submitted by the GAS app;
- synchronization status and conflict results;
- the user manifest;
- validation lists and schema metadata.

The Sheet does not store passwords, OAuth refresh tokens, API keys, private keys, recovery codes, or other secret values.

### 3.4 GAS web application

The GAS application provides authenticated browsing, search, relationship inspection, permitted editing, synchronization visibility, Looker analytics, and Owner administration. It enforces authorization on the server for every data operation. Client-side button visibility is not a security boundary.

### 3.5 Context OS adapter and skill

The adapter exposes ProjectOS capabilities to Context OS without exposing database internals. The conditionally installed skill invokes supported adapter commands for synchronization, lookup, project registration, resource/deployment inspection, impact analysis, conflict review, and health reporting.

The skill is discoverable only after ProjectOS onboarding and adoption complete successfully. A missing, disabled, incompatible, or unhealthy ProjectOS installation causes the skill to fail closed with a diagnostic response.

## 4. Canonical data model

Every canonical domain record uses a stable UUID, integer version, creation timestamp, update timestamp, provenance, and lifecycle status. Deletion is represented by archival or tombstone state unless an explicit purge workflow is approved.

### 4.1 Projects

`projects` is the central identity table.

Required fields:

- `project_id` — stable UUID;
- `slug` — stable human-readable identifier;
- `name`;
- `description`;
- `project_type` — GAS, Sheet-GCP, Looker, Git, local, mixed, or extensible future type;
- `status` — proposed, active, paused, archived;
- `visibility` — PUBLIC or PRIVATE;
- `context_os_registered` — boolean;
- `context_os_project_id` — optional external identifier;
- `owner_notes`;
- `tags_json`;
- `version`, timestamps, and provenance.

Project visibility is inherited by dependent records unless a stricter rule is defined. A dependent record can never broaden the visibility of its project.

### 4.2 Locations

`project_locations` records where a project lives:

- machine ID;
- local path and normalized path;
- repository root;
- Google Drive folder UID and URL;
- location type and environment;
- existence and discovery state;
- last discovered and last verified timestamps.

Local paths are machine scoped. The same project may have locations on multiple enrolled machines.

### 4.3 Resources

`resources` represents assets owned or used by a project:

- GAS script project;
- Google Sheet or workbook tab;
- Google Drive folder;
- GCP project, dataset, table, or service;
- Looker Git repository, model, view, explore, or dashboard;
- Git remote or repository;
- API, service, automation, dashboard, or other typed asset.

Resources record provider, external ID, URL, environment, role, status, metadata, and verification time. The model stores stable IDs separately from URLs so links can change without losing identity.

### 4.4 Deployments

`deployments` stores development and production deployment details:

- associated project and optional GAS resource;
- environment;
- script ID and deployment ID;
- deployment URL;
- active version and status;
- last discovered and last verified timestamps;
- safe notes and provenance.

Multiple development and production deployments may belong to one project.

### 4.5 Connections

`connections` models directed or bidirectional relationships between projects and resources:

- source project/resource;
- target project/resource;
- connection type;
- direction;
- implementation method, such as direct connector, GAS automation, scheduled load, API, file exchange, or manual process;
- business purpose and notes;
- active and health status;
- evidence and verification timestamps.

This model supports statements such as “this is a View Together connection for project X” without reducing the relationship to free-form notes.

### 4.6 Credential references

`credential_references` and `credential_usage` record safe metadata only:

- provider and safe label;
- credential type and purpose;
- scope description;
- external storage-system reference;
- owning project and consuming projects/resources;
- rotation due date and last verified timestamp;
- status and notes.

Secret values and directly usable authentication material are prohibited. Logs and exports redact credential metadata marked sensitive.

### 4.7 Looker and migration records

Looker-specific tables record repositories, files, models, views, explores, references, validation results, Git state snapshots, Sheet load results, and analytics snapshots. Migration tables record schema version, import batch, source provenance, reconciliation status, and cutover state.

### 4.8 Operational records

Operational tables include:

- `schema_migrations`;
- `sync_runs` and `sync_checkpoints`;
- `change_requests`;
- `conflicts`;
- `audit_events`;
- `discovery_runs` and findings;
- `extension_adoptions`;
- `backup_manifests`.

Operational data is retained according to configurable local retention rules. Audit entries required to explain canonical changes are not silently discarded.

## 5. Authorization and visibility

### 5.1 User roles

The User Manifest has three roles:

- **Owner:** the user. Full project access, PRIVATE-project access, conflict resolution, settings, user administration, migration approval surfaces, and all Admin capabilities.
- **Admin:** may view and propose edits to PUBLIC projects. Cannot view the administration menu, change users, see PRIVATE projects, or perform Owner-only system actions.
- **User:** view-only access to PUBLIC projects. Cannot see editing controls or the administration menu.

Unlisted, inactive, or unidentified callers receive no project data.

### 5.2 Owner protection

The Owner email is anchored in protected GAS configuration and mirrored in the User Manifest for display. Ordinary Sheet edits or web-app actions cannot remove, replace, or demote the Owner. The application rejects conflicting manifest changes and records an audit event.

### 5.3 Project visibility

- **PUBLIC:** visible to Owner, Admin, and User. Owner and Admin may submit changes; User is view-only.
- **PRIVATE:** visible and editable only by Owner.

PRIVATE records are filtered server-side before serialization. Non-Owners receive no private project, dependent record, search result, graph edge, analytics row, count, error detail, or audit entry that reveals the private project exists.

### 5.4 User Manifest fields

The Sheet representation includes email, display name, role, active flag, added timestamp, updated timestamp, last-access timestamp, and notes. User changes are Owner-only and take effect through the synchronization protocol rather than direct trust in arbitrary Sheet cell edits.

## 6. Synchronization protocol

### 6.1 Change-request model

GAS edits append immutable change requests rather than editing canonical projection rows in place. Each request contains:

- request UUID;
- actor email and role observed by GAS;
- entity type and stable entity ID;
- base SQLite version shown to the editor;
- changed fields and proposed values;
- submission timestamp;
- request status.

The local service independently revalidates actor role, project visibility, entity schema, stable IDs, base version, and field permissions. It does not trust the role supplied by the client.

### 6.2 Synchronization sequence

1. Acquire the shared synchronization lock.
2. Verify database health, schema version, Google credentials, Sheet identity, and projection schema.
3. Pull change requests after the last durable checkpoint.
4. Validate authorization and data rules.
5. Commit accepted requests inside SQLite transactions and append audit events.
6. Record rejected requests and conflicts without partial domain writes.
7. Publish the canonical, role-safe projection and status records to the Sheet.
8. Advance the checkpoint only after durable local recording.
9. Release the lock and emit a structured run summary.

The implementation must be safe to retry after interruption.

### 6.3 Conflict behavior

ProjectOS does not use silent last-write-wins behavior. A base-version mismatch creates a conflict. The Owner may:

- keep the current SQLite value;
- accept the proposed value as a new transaction; or
- merge selected fields into a new transaction.

Unauthorized edits are rejected, not presented as resolvable data conflicts.

### 6.4 Failure behavior

- If Google is unavailable, SQLite remains authoritative and the run records a retryable failure.
- If the enrolled synchronization host is offline, Sheet requests remain pending.
- If one proposal is invalid, ProjectOS rejects that proposal and continues with independent safe proposals.
- If publication fails after a SQLite commit, the run records `publish_incomplete`; the next run republishes from SQLite.
- If local database health, migration, identity, or Sheet-schema checks fail, the run stops before applying incoming changes.

## 7. Google Sheet design

An idempotent, non-destructive setup function creates or upgrades the workbook. It never treats formatting-generated checkbox values as evidence of user data; stable ID columns determine whether a row exists.

Logical sheets include:

- `Projects`;
- `Locations`;
- `Resources`;
- `Deployments`;
- `Connections`;
- `CredentialReferences`;
- `CredentialUsage`;
- `LookerAssets`;
- `LookerAnalytics`;
- `ChangeRequests`;
- `Conflicts`;
- `SyncStatus`;
- `UserManifest`;
- `Settings`;
- `Lists`;
- `SchemaMetadata`.

Projection sheets include stable IDs, canonical version, canonical update time, synchronization status, and appropriate link fields. Protected system columns are not normal user-edit surfaces.

## 8. GAS web-app design

### 8.1 Information architecture

Primary navigation includes:

- Overview;
- Projects;
- Connections;
- Deployments;
- Credential References;
- Looker Analytics;
- Sync Activity.

The Owner additionally sees Administration. Admins and Users do not receive administration navigation or administration data.

Selecting a project opens a workspace with Summary, Locations, Google Assets, Deployments, Connections, Credential References, Looker, and History tabs. Tabs may be omitted when they have no applicable content.

### 8.2 Dashboard

The dashboard emphasizes active projects, production deployments, pending changes, synchronization age, verification alerts, and migration state. Counts are calculated from records the current user is allowed to see.

### 8.3 Visual system

The approved direction is **Context OS Native**:

- deep graphite surfaces;
- cobalt structural accents;
- teal success and canonical-state accents;
- amber warnings and red failures;
- restrained depth and minimal glass effects;
- dense but readable operational layouts;
- plain-language labels and explicit statuses.

The interface must satisfy WCAG 2.1 AA contrast, keyboard navigation, visible focus, semantic headings, meaningful labels, status text beyond color, reduced-motion support, and responsive desktop/mobile behavior.

### 8.4 Editing experience

Permitted edits open structured forms. The client submits only changed fields and the displayed base version. After submission, the UI shows `PENDING`, `SYNCED`, `CONFLICT`, or `REJECTED`. It never claims an edit is canonical before SQLite confirms it.

## 9. Context OS adoption

### 9.1 Extension manifest

The ProjectOS extension manifest declares:

- extension ID and version;
- compatible Context OS versions;
- adapter and CLI entrypoints;
- skill path and command capabilities;
- database and migration status;
- health, maintenance, and uninstall hooks;
- safe references to the Sheet and GAS deployment;
- installation machine and adoption state.

### 9.2 Adoption transaction

1. **Preflight:** verify Context OS version, machine identity, runtime, paths, SQLite support, Google authentication, Sheet ownership, and required tools.
2. **Snapshot:** preserve affected configuration and generate a verified manifest.
3. **Stage:** install ProjectOS runtime, database, config, adapter, CLI, skill, and scheduler definition outside live activation paths.
4. **Verify:** run migrations, tests, dry-run synchronization, role/visibility checks, adapter calls, skill contract tests, and rollback rehearsal.
5. **Adopt:** register the extension, expose approved tools, enable the skill, and load the two-hour service.
6. **Prove:** run a real synchronization and real skill invocation, verify health and integrity, and retain rollback artifacts.

Any failed gate leaves the live Context OS installation unchanged.

### 9.3 Skill behavior

Activating the ProjectOS skill runs synchronization before answering ProjectOS queries or performing ProjectOS commands. If another run holds the lock, the skill reports the active run and may wait only within a bounded timeout before returning a non-destructive status.

Supported capability categories include:

- synchronize and report status;
- register or inspect a project;
- locate project folders and Google assets;
- list deployments and environments;
- trace connections and credential-reference usage;
- report conflicts and health;
- query Looker analytics after the Looker phase is adopted.

The skill delegates deterministic changes to ProjectOS commands; it does not edit SQLite directly.

### 9.4 Removal and rollback

Removal disables the extension and scheduler, removes the discoverable skill link, restores preserved Context OS configuration, and archives ProjectOS runtime state. The ProjectOS database remains recoverable unless the Owner separately approves a purge.

## 10. Discovery and self-refinement

ProjectOS may research enrolled machines through explicit discovery adapters. Discovery produces candidate findings with provenance; it does not silently rewrite canonical records or change the schema.

Candidate examples include:

- a new `.clasp.json` script ID;
- a Git remote or branch change;
- a newly detected Sheet or Drive folder reference;
- a new production deployment URL;
- a broken local path;
- a new Looker model or view;
- a credential reference used by another project.

Low-risk factual updates may be auto-applied only when a future policy explicitly identifies the field and evidence as deterministic. All other findings enter a review queue. New entity types, schema changes, migration rules, or security policies require versioned code and migrations; learned observations cannot generate or execute arbitrary schema mutations.

## 11. Looker Git migration

### 11.1 Timing

The Looker migration begins only after the ProjectOS core, Google interface, and Context OS adoption are stable. It is a separate release phase using the same architecture.

### 11.2 Required intake

The Owner supplies:

- source machine ID and operating context;
- absolute Looker Git project folder;
- Git remote, primary branch, and repository ownership context;
- master Google Sheet URL/ID and relevant tabs;
- GAS script project/deployment IDs and local source folder if present;
- current local synchronization scripts and scheduler definitions;
- validation commands, tests, and expected outputs;
- credential storage systems by safe reference only.

These are runtime intake values, not unresolved architectural decisions.

### 11.3 Read-only evaluation

The first pass inventories and explains the current system without modifying it. It captures LookML/model files, scripts, Sheet schemas, data flow, Git status, schedules, validation results, credential references, and observed outputs. The evaluation produces a migration assessment, source-to-target mapping, risk register, reconciliation plan, and rollback plan.

### 11.4 Migration and cutover

ProjectOS imports copied fixtures first through versioned SQL migrations. It then runs staged or parallel reconciliation against the current system. Cutover requires matching required counts and analytics, a successful real refresh, passing validation, a preserved legacy snapshot, a rehearsed rollback, and explicit Owner approval.

Disabling old scripts, triggers, launch agents, or Sheet automation is never part of the read-only evaluation.

### 11.5 Web analytics

The web app reports:

- model, view, explore, and dashboard counts;
- model-to-view and cross-project connections;
- broken references, duplicate names, and orphaned files;
- current Git branch, dirty state, divergence, and last commit;
- existing validation and code-status results;
- Sheet refresh and last-success status;
- migration version, provenance, drift, and reconciliation state;
- credential-reference usage without secret exposure.

## 12. Delivery decomposition

The program uses four release phases. Each receives its own implementation plan and release-candidate gate.

### Phase 1 — Local foundation

Build the separate repository, SQLite schema and migrations, domain/CLI services, discovery contracts, provenance, audit, safe credential references, and backup/restore.

Acceptance requires deterministic migration from an empty database and previous fixtures, complete domain invariants, structured CLI contracts, backup/restore proof, corruption handling, and passing local security checks.

### Phase 2 — Google interface

Build Sheet setup/upgrades, the GAS web app, authorization and visibility filters, change requests, conflict UI, and bidirectional synchronization.

Acceptance requires role-matrix tests, PRIVATE-data non-disclosure, offline and interrupted-run behavior, round-trip synchronization, conflict resolution, accessible responsive UI inspection, and verified GAS file ordering.

### Phase 3 — Context OS adoption

Build the extension manifest, adapter, conditional skill, EA tools, staged installer, two-hour scheduler, health integration, and rollback.

Acceptance requires stage-only verification, real skill invocation, real synchronization, scheduler proof, health/integrity checks, compatibility enforcement, and rollback proof. Live adoption is a separate approval boundary.

### Phase 4 — Looker migration

Run the other-machine intake, read-only evaluation, analytics build, versioned migration, parallel reconciliation, and approved cutover.

Acceptance requires analytics parity, traceable import provenance, real refresh validation, cutover checklist completion, recoverable legacy archive, and rollback proof. Disabling legacy automation is a separate approval boundary.

## 13. Testing and verification

### 13.1 Focused tests

- schema migrations, constraints, repositories, and transactions;
- role and visibility matrix at service and GAS endpoints;
- stable IDs, optimistic versions, idempotency, and conflict creation;
- sync checkpoints, lock behavior, retry, and publish recovery;
- discovery provenance and candidate handling;
- CLI/adapter and extension-manifest contracts;
- Looker parsers and analytics using copied fixtures;
- secret-redaction and prohibited-field tests.

### 13.2 Integration tests

- SQLite to Sheet projection;
- Sheet change request to SQLite commit and republish;
- owner/admin/user behavior;
- PUBLIC/PRIVATE non-disclosure;
- Context OS adapter and skill invocation;
- scheduler and manual trigger serialization;
- backup, restore, adoption, disablement, and rollback.

### 13.3 Release-candidate gates

Focused tests run during development. Each completed phase runs its complete regression suite once at the release-candidate boundary. Visual inspection is required for changed web surfaces on desktop and mobile. Security, authorization, protected identifiers, migration integrity, and rollback are mandatory when affected.

## 14. Operational observability

Every scheduled or skill-triggered run produces a structured local summary with run ID, trigger, start/end time, schema version, pulled request count, accepted/rejected/conflict counts, published row count, checkpoint, warnings, and errors. The Sheet receives a safe summary without secrets or private-project leakage.

The web app displays last successful sync, latest attempt, pending count, conflict count, projection age, and whether the local machine appears offline. It does not imply real-time connectivity.

## 15. Explicit non-goals

The initial program does not:

- make Google Sheets authoritative;
- expose SQLite directly over the internet;
- store secrets in SQLite domain records or Sheets;
- allow Admins to manage users or see PRIVATE projects;
- silently rewrite schemas based on discovered data;
- disable legacy Looker automation during evaluation;
- replace Context OS project memory, tasks, knowledge, or policy systems;
- require a separate cloud database or always-on application server.

## 16. Completion criteria

ProjectOS is complete when:

1. SQLite is demonstrably canonical and recoverable.
2. The Sheet and GAS application provide authorized, accessible, role-correct access.
3. Two-hour and skill-triggered synchronization are transactional and observable.
4. Context OS adopts ProjectOS through a compatible, reversible extension boundary.
5. Project discovery and credential-reference impact queries work with provenance.
6. The Looker workflow is evaluated, migrated, reconciled, and cut over only after approval.
7. Each phase passes its stated release-candidate gate with retained evidence and rollback artifacts.

## 17. Next design artifact

After this written specification is reviewed and approved, the next artifact is a detailed Phase 1 implementation plan. Later phases receive their own implementation plans after the preceding phase reaches its acceptance gate and any live/authenticated boundary is approved.
