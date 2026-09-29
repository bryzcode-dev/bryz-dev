# ProjectOS

ProjectOS includes the Phase 4 Looker migration and analytics enhancement for macOS and Windows. The local build remains `SIMULATED`: it can collect sanitized evidence, import it into SQLite schema 3, project role-safe GAS analytics, reconcile a legacy tracker, validate guarded refresh receipts, and prepare a reversible cutover package. Real source-machine intake, Google refresh, and legacy disablement each require separate authorization.

ProjectOS is a local-first project catalog and an optional Context OS enhancement. Its SQLite database is the system of record. Google Sheets and the GAS web application are collaboration surfaces; they never become authoritative stores.

The Phase 2 local release candidate provides the catalog and Google/GAS boundary. Phase 3 adds portable adoption and guarded host acceptance. Phase 4 adds the Looker migration path:

- versioned SQLite schema and transactional repositories;
- projects, machine locations, resources, deployments, connections, and impact queries;
- credential references and usage maps without secret values;
- provenance-based Context OS manifest discovery with explicit apply/reject review;
- verified backup, staged restore, rollback preservation, and health checks;
- canonical Owner/Admin/User authorization with Owner-only PRIVATE projects;
- a versioned 14-tab Google workbook contract and non-mutating repair planner;
- fake and guarded real Google gateways, immutable request receipts, conflicts, revision publication, and retry-safe checkpoints;
- a server-authorized GAS application and responsive role-aware web interface;
- redacted diagnostics and a JSON-only command-line contract for Context OS integration.
- host-neutral path, lock, ContextOS-contract, and machine-profile planning;
- strict extension manifests and deterministic, identifier-scanned staging bundles;
- database-free adoption inspection and validation commands;
- a deterministic `py3-none-any` wheel whose native lock modules load lazily.
- an explicitly marked isolated-fixture boundary with a local receipt and acknowledgement;
- local journals, exact registry snapshots, verified staging, immutable disabled definitions, rollback, upgrade, recovery, and uninstall;
- a database-free `adoption fixture` CLI with no live target or force option.
- one profile-validated `runtime sync` entrypoint shared by scheduler and skill triggers;
- deterministic disabled `launchd` and Windows Task Scheduler definitions;
- a receipt-bound fixture scheduler runner with no native command execution;
- a canonical manifest-bound ProjectOS skill and ordered read-only discovery gate;
- reversible fixture activation, proof, deactivation, and idempotent recovery.
- deterministic read-only Looker collection with macOS and Windows intake contracts;
- schema-3 immutable intake occurrences, dependency analytics, findings, Git/code status, and credential-reference aggregates;
- role-safe GAS Looker views and conditional read-only ContextOS capabilities;
- immutable legacy reconciliation with protected-Owner waivers;
- guarded refresh receipts that bind intake, analytics, reconciliation, Google projection, sync, and validation;
- deterministic cutover/checklist/rollback packages, non-vacuous legacy-mapping coverage, external signed Owner approvals, and intent-before-effect recovery.

## Status and safety boundary

This repository is a Phase 4 local release candidate. All automated evidence is `SIMULATED`. The real Google gateway, native schedulers, and native cutover host boundary remain fail-closed unless invoked through their separately authorized workflows.

This phase does **not** prove another machine was inspected, authenticate Google, create or modify a real Sheet, deploy GAS, install or change a macOS `launchd` job or Windows scheduled task, enable the skill in a live ContextOS instance, disable a legacy tracker, push, or merge.

The approved access model for the later web application is:

- Owner: full access, the only role allowed to change users, and the only role that sees the admin menu;
- Admin: edit PUBLIC projects, with no admin menu;
- User: view PUBLIC projects, with no admin menu;
- PRIVATE projects: Owner only.

The Python authorization layer and GAS server enforce these rules before serialization. The browser UI only reflects capabilities returned by the server; it cannot elevate a role.

## Install locally

ProjectOS requires Python 3.11 or newer and has no runtime dependencies.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/projectos --db "$HOME/.projectos/projectos.db" init
```

Every command prints exactly one JSON document. A successful response contains `"ok":true`; consumers should also inspect the process exit code.

```json
{"command":"init","data":{"database":"...","schema_version":3},"errors":[],"meta":{"schema_version":3},"ok":true}
```

## Start using the catalog

Create a project:

```bash
projectos --db "$HOME/.projectos/projectos.db" project create \
  --slug example-gas --name "Example GAS" --type GAS --visibility PUBLIC \
  --actor owner@example.com
```

Discover Context OS manifests without mutating the catalog:

```bash
projectos --db "$HOME/.projectos/projectos.db" discover contextos \
  --projects-dir /path/to/context-os-projects --machine-id work-mac \
  --source-run-id manual-2026-09-26
projectos --db "$HOME/.projectos/projectos.db" discover list --status CANDIDATE
```

Apply or reject a reviewed finding:

```bash
projectos --db "$HOME/.projectos/projectos.db" discover apply FINDING_UUID \
  --actor owner@example.com
projectos --db "$HOME/.projectos/projectos.db" discover reject FINDING_UUID \
  --reason "Not managed by ProjectOS" --actor owner@example.com
```

Build and preview the GAS app without contacting Google:

```bash
node gas/scripts/build.mjs --out gas/dist
node gas/scripts/preview.mjs --fixture gas/test/fixtures/ui-roles.json --port 4173
```

Open `http://127.0.0.1:4173/?role=owner`, `?role=admin`, or `?role=user`. The role query parameter exists only in fixture preview mode; deployed GAS always resolves identity server-side.

See [Phase 2 operations](docs/PHASE2_OPERATIONS.md), [schema reference](docs/PHASE2_SCHEMA.md), [verification evidence](docs/PHASE2_VERIFICATION.md), and the [Claude implementation and troubleshooting handoff](docs/PHASE2_CLAUDE_IMPLEMENTATION_AND_TROUBLESHOOTING.md). Phase 1 documents remain as historical foundation references.

For Phase 3C, see [fixture activation operations](docs/PHASE3C_OPERATIONS.md), [candidate verification](docs/PHASE3C_VERIFICATION.md), and the [Windows clean-room implementation and troubleshooting handoff](docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md). Phase 3B [definition operations](docs/PHASE3B_OPERATIONS.md) and [verification](docs/PHASE3B_VERIFICATION.md) remain prerequisites.

Phase 3D-B adds the guarded clean-host runner for both macOS and Windows. Start with [host operations](docs/PHASE3D_HOST_OPERATIONS.md), the [implementation and troubleshooting handoff](docs/PHASE3D_B_IMPLEMENTATION_AND_TROUBLESHOOTING.md), and [verification](docs/PHASE3D_B_VERIFICATION.md). Status remains `SIMULATED`: each real platform run requires separate Owner authorization and accepted evidence before support advances.

For Phase 4, start with [source collection](docs/PHASE4A_SOURCE_COLLECTION.md), [import and analytics](docs/PHASE4B_IMPORT_AND_ANALYTICS.md), [reconciliation and ContextOS queries](docs/PHASE4C_RECONCILIATION.md), [cutover and rollback](docs/PHASE4D_CUTOVER_AND_ROLLBACK.md), the [Claude implementation/troubleshooting handoff](docs/PHASE4_CLAUDE_IMPLEMENTATION_AND_TROUBLESHOOTING.md), and [verification evidence](docs/PHASE4_VERIFICATION.md).
