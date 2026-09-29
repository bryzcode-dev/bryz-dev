# ProjectOS Phase 4 Looker Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete local and simulated Phase 4 Looker intake, SQLite import, analytics, reconciliation, web reporting, ContextOS capability, and reversible cutover-preparation system.

**Architecture:** A separate standard-user collector turns an explicitly declared source folder into a deterministic sanitized archive. ProjectOS verifies and imports that archive transactionally into schema 3, derives versioned graph analytics, exposes role-filtered results through the existing GAS projection, and prepares reconciliation and cutover artifacts without changing the legacy system. Phase 4-A through 4-D are sequential release candidates sharing one evidence and provenance contract.

**Tech Stack:** Python 3.11+ standard library, SQLite migrations, `unittest`, Google Apps Script JavaScript, Node test runner, deterministic ZIP/JSON artifacts.

**Spec:** `docs/superpowers/specs/2026-09-27-projectos-phase-4-looker-migration-design.md`

## Global Constraints

- SQLite is the single source of truth; Sheets and GAS are collaboration surfaces.
- Support macOS and Windows without embedding a home path, username, hostname, source folder, or scheduler.
- Runtime remains dependency-free Python 3.11+.
- Collection is standard-user and read-only; do not follow links or modify repository, Git, Sheet, GAS, scheduler, or script state.
- Never resolve, copy, store, display, or log credential values.
- Use fixed command arrays with `shell=False`; reject shell syntax, expansion, pipes, redirects, substitutions, and unknown parsers.
- Archive and database formats reject unknown fields, traversal, absolute paths, case-fold duplicates, links, devices, corrupt members, and noncanonical JSON.
- Owner alone imports, waives reconciliation items, prepares cutover, manages users, and sees PRIVATE projects.
- Admin edits only allowlisted PUBLIC descriptive fields; User is PUBLIC view-only; neither sees the admin menu.
- All automated work uses invented fixtures and recording executors. Do not inspect the other machine, authenticate Google, run a real refresh, or disable legacy automation.
- Real intake, real refresh, and exact-target legacy disablement remain three separate explicit Owner authorization boundaries.
- Use TDD, focused tests per task, one complete Python/GAS regression at each subphase release-candidate boundary, and at most one automatic correction round per subphase.
- Do not push, merge, publish, remove the detached worktree, or change live ContextOS/shared-root/production SQLite state.

## Review Focus

- Repository content changes between initial inventory and sealing: Task 4 must fail the archive instead of mixing revisions.
- Valid LookML with cyclic `extends` or project imports: Task 2 must terminate deterministically and emit cycle findings.
- Identical source run ID with different archive bytes: Task 5 must reject the import without partial rows.
- PRIVATE project encountered through aggregate counts or graph traversal: Task 8 must return no identifying or inferential data to Admin/User.
- Cutover ownership changes after package preparation: Task 10 must stop without disabling or deleting any target.

---

## File structure

```text
src/projectos/looker/model.py             Strict intake, asset, edge, finding, and result records
src/projectos/looker/policy.py            Source/output path and validation-command envelope checks
src/projectos/looker/lookml.py            Non-executing LookML inventory and reference parser
src/projectos/looker/inspectors.py        Read-only Git, legacy, scheduler, script, and validation inspection
src/projectos/looker/evidence.py          Canonical archive builder and verifier
src/projectos/looker/collector.py         Journaled collection coordinator
src/projectos/looker/importer.py          Archive preview and atomic SQLite import
src/projectos/looker/repository.py        Schema-3 persistence and query boundaries
src/projectos/looker/analytics.py         Dependency graph, impact, counts, and findings
src/projectos/looker/reconcile.py         Immutable comparison policy and reconciliation reports
src/projectos/looker/cutover.py           Local cutover/rollback package preparation and ownership checks
src/projectos/looker_host.py              Separate source-machine collector entrypoint
src/projectos/migrations/0003.sql         Phase 4 canonical schema
src/projectos/cli.py                      Database-free verification plus Owner/domain commands
src/projectos/sync/projection.py          Role-filtered Looker projection
src/projectos/adoption/manifest.py        Versioned Looker capability allowlist
src/projectos/adoption/skill.py           Conditional canonical Looker instructions
gas/src/server/40_DataService.js          Safe Looker DTO queries
gas/src/client/app.html                   Looker overview, graph, findings, and status views
gas/src/client/styles.html                Responsive and accessible Looker presentation
```

### Task 1: Phase 4-A Intake Models and Safety Policy

**Files:**
- Create: `src/projectos/looker/__init__.py`
- Create: `src/projectos/looker/model.py`
- Create: `src/projectos/looker/policy.py`
- Create: `tests/test_looker_intake.py`
- Create: `tests/fixtures/looker/intake-macos.json`
- Create: `tests/fixtures/looker/intake-windows.json`

**Interfaces:**
- Produces: `LookerIntake.from_mapping(value) -> LookerIntake`, `ValidationCommand`, `CollectorPaths`, and `validate_collector_environment(intake, session) -> CollectorPaths`.
- Consumes: `HostFamily`, existing canonical validation helpers, and `ValidationError`.

- [ ] Write failing tests named `test_intake_is_canonical_strict_and_cross_platform`, `test_repository_and_output_are_separate_non_symlink_roots`, `test_standard_user_session_is_required`, `test_command_envelope_rejects_shell_syntax_secret_arguments_and_unknown_parser`, and `test_credential_declarations_are_safe_references_only`.
- [ ] Run `rtk /opt/homebrew/bin/python3 -m unittest tests.test_looker_intake -v`; expect missing `projectos.looker` failures.
- [ ] Implement immutable schema-1 records with exact field validation, path separation, host matching, timeout range `1..600`, fixed argument arrays, and parser allowlist `COUNT_SUMMARY`, `TEST_SUMMARY`, `STATUS_ONLY`.
- [ ] Run the focused test; expect PASS.
- [ ] Commit with `feat: define safe Looker intake contract`.

### Task 2: LookML Inventory and Dependency Parser

**Files:**
- Create: `src/projectos/looker/lookml.py`
- Create: `tests/test_looker_parser.py`
- Create: `tests/fixtures/looker/repository/`

**Interfaces:**
- Consumes: validated regular files below `CollectorPaths.repository_root`.
- Produces: `parse_repository(root: Path) -> ParsedLookerRepository`, containing ordered `LookerAsset`, `LookerRelationship`, and `LookerFinding` tuples.

- [ ] Add failing fixtures/tests for models, views, explores, joins, dashboards, includes, imports, connections, extensions, duplicate names, missing targets, unsupported syntax, malformed files, and cyclic extends/imports.
- [ ] Run `rtk /opt/homebrew/bin/python3 -m unittest tests.test_looker_parser -v`; expect missing parser failures.
- [ ] Implement a bounded tokenizer/reference parser that never evaluates SQL, Liquid, imports, or scripts; preserve portable relative path, content hash, parser version, and line locator.
- [ ] Assert deterministic ordering and cycle findings with no recursion failure; rerun focused tests.
- [ ] Commit with `feat: parse LookML assets and relationships`.

### Task 3: Read-Only Source Inspectors

**Files:**
- Create: `src/projectos/looker/inspectors.py`
- Create: `tests/test_looker_inspectors.py`
- Create: `tests/fixtures/looker/legacy/`

**Interfaces:**
- Consumes: `LookerIntake`, `CollectorPaths`, injected `ProcessExecutor`.
- Produces: `inspect_git(...) -> GitInspection`, `inspect_legacy(...) -> LegacyInspection`, `inspect_automation(...) -> AutomationInspection`, and `run_validations(...) -> tuple[ValidationResult, ...]`.

- [ ] Write failing tests for fixed read-only Git arrays, branch/divergence/dirty parsing, declared Sheet/GAS schemas, script/scheduler text inspection, bounded outputs, timeout/nonzero handling, and proof that repository files cannot introduce commands.
- [ ] Run the focused tests and verify RED.
- [ ] Implement inspectors using injected recording execution, `shell=False`, bounded byte reads, redacted summaries, and no Google client.
- [ ] Run focused tests; confirm no actual Git scheduler, Google, or validation command is executed.
- [ ] Commit with `feat: inspect Looker source workflow read only`.

### Task 4: Collector Journal, Evidence Archive, and Host CLI

**Files:**
- Create: `src/projectos/looker/evidence.py`
- Create: `src/projectos/looker/collector.py`
- Create: `src/projectos/looker_host.py`
- Create: `tests/test_looker_evidence.py`
- Create: `tests/test_looker_collector.py`
- Create: `tests/test_looker_host_cli.py`
- Modify: `build_backend.py`

**Interfaces:**
- Consumes: Tasks 1-3 typed results.
- Produces: `LookerCollector.collect(...) -> CollectionResult`, `verify_intake_archive(path) -> VerifiedLookerEvidence`, and database-free commands `preflight`, `collect`, `verify`, `recover` in the separate `projectos.looker_host` module.

- [ ] Write failing tests for exact archive members, canonical hashes, repository mutation during collection, journal resume, temporary-only cleanup, corruption, traversal, duplicates, links/devices, secrets, identifiers, paths, emails, raw output, and unknown members.
- [ ] Verify RED with the three focused modules.
- [ ] Implement ordered journal stages, before/after repository fingerprint comparison, atomic archive sealing, strict verifier, redacted JSON exits, and build inclusion.
- [ ] Add installed-wheel tests proving collection and verification without source checkout or network/native execution.
- [ ] Run Phase 4-A affected tests, then exactly one complete Python/GAS/compile gate; build and scan the wheel and intake archive.
- [ ] Create `docs/PHASE4A_SOURCE_COLLECTION.md`, `docs/PHASE4_CLAUDE_IMPLEMENTATION_AND_TROUBLESHOOTING.md`, and `docs/PHASE4A_VERIFICATION.md`.
- [ ] Commit with `feat: collect portable Looker intake evidence`.

### Task 5: Phase 4-B Schema 3, Repository, and Atomic Import

**Files:**
- Create: `src/projectos/migrations/0003.sql`
- Create: `src/projectos/looker/repository.py`
- Create: `src/projectos/looker/importer.py`
- Create: `tests/test_database_phase4.py`
- Create: `tests/test_looker_importer.py`
- Modify: `src/projectos/database.py`
- Modify: `tests/test_build_backend.py`

**Interfaces:**
- Consumes: `VerifiedLookerEvidence`.
- Produces: schema version `3`, `LookerRepository`, `LookerImportPreview`, and `LookerImporter.import_archive(project_id, evidence, actor) -> LookerImportResult`.

- [ ] Write failing tests for fresh schema 3, schema-2 upgrade, rollback, constraints, indexes, exact table inventory, idempotent SHA import, conflicting reused run, missing project, provenance, and no partial rows.
- [ ] Run focused tests; expect schema/import failures.
- [ ] Implement `0003.sql`, update `SCHEMA_VERSION = 3`, repositories, read-only preview, and one-transaction Owner-audited import.
- [ ] Run database, backup/health, importer, prior schema, and build tests.
- [ ] Commit with `feat: import Looker evidence into schema three`.

### Task 6: Dependency Graph, Analytics, and Impact

**Files:**
- Create: `src/projectos/looker/analytics.py`
- Create: `tests/test_looker_analytics.py`
- Modify: `src/projectos/looker/repository.py`

**Interfaces:**
- Consumes: imported asset, relationship, finding, Git, validation, legacy, and credential-reference rows.
- Produces: `LookerAnalyticsService.build(project_id, intake_run_id) -> AnalyticVersion`, `summary(...)`, `dependencies(...)`, and `impact(...)`.

- [ ] Write failing tests for all spec counts, dependency paths, unresolved/duplicate/orphan results, cyclic graphs, changed/removed impact, Git/code status, mappings, refresh state, credential usage, deterministic versioning, and prior-version retention.
- [ ] Run focused tests and verify RED.
- [ ] Implement iterative graph traversal with stable ordering and versioned canonical analytic JSON.
- [ ] Run analytics plus importer/repository tests; expect PASS.
- [ ] Commit with `feat: build Looker dependency analytics`.

### Task 7: CLI and Projection Contracts

**Files:**
- Modify: `src/projectos/cli.py`
- Modify: `src/projectos/sync/projection.py`
- Create: `tests/test_cli_phase4.py`
- Create: `tests/test_looker_projection.py`

**Interfaces:**
- Consumes: Tasks 4-6 services and existing `AuthorizationService`.
- Produces: CLI groups `looker intake`, `looker analytics`, and safe projection tabs/DTOs.

- [ ] Write failing tests for database-free verify/preview, explicit database import/build/query, Owner-only mutation, JSON-only results, absence of force/purge/arbitrary-SQL options, PUBLIC filtering, and PRIVATE aggregate/search/graph non-disclosure.
- [ ] Run focused tests and verify RED.
- [ ] Add parser/dispatch handlers that delegate to services and extend the canonical workbook projection without accepting role input.
- [ ] Run Phase 4-B affected regression, then one complete Python/GAS/compile gate; build and scan schema-3 wheel and simulated import artifacts.
- [ ] Create `docs/PHASE4B_IMPORT_AND_ANALYTICS.md` and `docs/PHASE4B_VERIFICATION.md`.
- [ ] Commit with `feat: expose Looker import and analytics contracts`.

### Task 8: GAS Looker Analytics Experience

**Files:**
- Modify: `gas/source-order.json`
- Modify: `gas/src/server/20_Contract.js`
- Modify: `gas/src/server/40_DataService.js`
- Modify: `gas/src/client/app.html`
- Modify: `gas/src/client/styles.html`
- Modify: `gas/test/serialization.test.js`
- Create: `gas/test/looker.test.js`
- Modify: `gas/test/accessibility.test.js`
- Modify: `gas/test/fixtures/ui-roles.json`

**Interfaces:**
- Consumes: role-safe Looker projection rows and server-issued capabilities.
- Produces: safe server DTOs and overview, dependency, findings, Git/status, migration, reconciliation, and Owner cutover-readiness views.

- [ ] Write failing Node tests for Owner/Admin/User matrix, PRIVATE non-disclosure through counts/search/graphs/errors, hidden Owner actions, stale/offline/empty states, keyboard navigation, focus, landmarks, contrast tokens, responsive tables, and 44px targets.
- [ ] Run `rtk node --test gas/test/*.test.js`; verify RED.
- [ ] Implement server-first filtering and progressive, accessible client rendering; never send a role from the browser.
- [ ] Build GAS deterministically and visually inspect Owner/Admin/User on desktop and mobile fixtures.
- [ ] Run Python projection and complete GAS tests; commit with `feat: add role-safe Looker analytics UI`.

### Task 9: Phase 4-C Reconciliation Engine

**Files:**
- Create: `src/projectos/looker/reconcile.py`
- Create: `tests/test_looker_reconcile.py`
- Modify: `src/projectos/looker/repository.py`
- Modify: `src/projectos/cli.py`

**Interfaces:**
- Consumes: immutable analytic version, legacy snapshot, and canonical comparison policy.
- Produces: `ReconciliationPolicy`, `LookerReconciler.stage(...) -> ReconciliationReport`, Owner-only `waive(...)`, and CLI `looker reconcile stage|report|waive`.

- [ ] Write failing tests for every required dimension and states `MATCH`, `MISMATCH`, `MISSING_SOURCE`, `MISSING_TARGET`, `WAIVED`; include changed-policy, duplicate, mixed-version, missing provenance, Admin/User waiver, and unresolved-required readiness tests.
- [ ] Run focused tests and verify RED.
- [ ] Implement immutable report storage, exact-version binding, required-dimension readiness, reasoned Owner waiver, and audit events.
- [ ] Run reconciliation, authorization, CLI, importer, and analytics tests.
- [ ] Commit with `feat: reconcile Looker analytics with legacy tracker`.

### Task 10: Guarded Refresh Receipt and ContextOS Capabilities

**Files:**
- Create: `src/projectos/looker/refresh.py`
- Create: `tests/test_looker_refresh.py`
- Modify: `src/projectos/adoption/manifest.py`
- Modify: `src/projectos/adoption/skill.py`
- Modify: `src/projectos/contextos_adapter.py`
- Modify: `tests/test_projectos_skill.py`
- Modify: `tests/test_skill_discovery.py`
- Modify: `tests/test_extension_bundle.py`

**Interfaces:**
- Produces: `RefreshReceipt` verification and conditional capabilities `looker-status`, `looker-assets`, `looker-dependencies`, `looker-findings`, `looker-impact`, `looker-reconciliation`.
- Consumes: schema-3 health, extension manifest version, reconciliation report, and existing guarded Google receipts; automated tests use fake receipts only.

- [ ] Write failing tests that reject simulated/unbound/mixed receipts and hide capabilities for old schema/extension; prove read-only adapter calls and canonical skill bytes.
- [ ] Run focused tests and verify RED.
- [ ] Implement receipt validation and conditional capability discovery without adding live Google calls or state-changing skill operations.
- [ ] Run Phase 4-C affected tests, then one complete Python/GAS/compile gate; package reconciliation evidence with support state `SIMULATED`.
- [ ] Create `docs/PHASE4C_RECONCILIATION.md` and `docs/PHASE4C_VERIFICATION.md`; commit with `feat: stage Looker reconciliation and ContextOS queries`.

### Task 11: Phase 4-D Cutover and Rollback Preparation

**Files:**
- Create: `src/projectos/looker/cutover.py`
- Create: `src/projectos/looker_cutover_host.py`
- Create: `tests/test_looker_cutover.py`
- Create: `tests/test_looker_cutover_host.py`
- Modify: `src/projectos/cli.py`

**Interfaces:**
- Consumes: verified intake, backup, mapping, reconciliation, refresh, validation, ownership, and rollback facts.
- Produces: `CutoverPreparer.prepare(...) -> CutoverPackage`, `verify_cutover_package`, recording-only effect plans, and a separate host module reserved for explicitly authorized execution/recovery.

- [ ] Write failing tests for every readiness prerequisite, deterministic legacy archive/checklist/rollback package, intent-before-effect journal, disable-before-remove order, exact ownership, process reconstruction, changed ownership, failed effects, idempotent rollback, and permanent legacy archive retention.
- [ ] Run focused tests and verify RED.
- [ ] Implement local preparation and recording-executor transaction contracts; ordinary CLI exposes prepare/verify only and has no disable/delete command.
- [ ] Add installed-wheel tests proving preparation and recovery simulation without source checkout, native execution, Google, or network.
- [ ] Run cutover plus backup, adoption, acceptance, reconciliation, and artifact tests.
- [ ] Commit with `feat: prepare reversible Looker cutover`.

### Task 12: Phase 4 Release Candidate and Handoff

**Files:**
- Create: `docs/PHASE4D_CUTOVER_AND_ROLLBACK.md`
- Create: `docs/PHASE4_VERIFICATION.md`
- Modify: `docs/PHASE4_CLAUDE_IMPLEMENTATION_AND_TROUBLESHOOTING.md`
- Modify: `README.md`
- Modify: `tests/test_build_backend.py`
- Create: `tests/test_looker_installed.py`

**Interfaces:**
- Consumes: all Tasks 1-11.
- Produces: installed-wheel end-to-end fixture workflow, final handoff, deterministic artifacts, and explicit external authorization gates.

- [ ] Write failing extracted-wheel tests for collect, verify, import, analytics, projection, reconciliation, refresh-receipt verification, cutover preparation, crash recovery, and package verification without source checkout.
- [ ] Complete macOS/Windows source-machine instructions, Claude troubleshooting, transfer, import, refresh, cutover, and rollback documents; keep support `SIMULATED`.
- [ ] Run the Phase 4-D affected regression gate and record exact focused counts.
- [ ] Run exactly one final complete Python and GAS regression plus Python compilation for the Phase 4-D candidate; repeat only for the single allowed correction round.
- [ ] Build in fresh roots: wheel, extension bundle, intake archive, schema-3 import snapshot, analytics report, reconciliation report, simulated refresh receipt, cutover package, and rollback package.
- [ ] Scan all portable and local invented state for secrets, identifiers, emails, home paths, hostnames, traversal, links, devices, duplicate paths, shell execution, unexpected native execution, network access, and raw output.
- [ ] Record source revision, sizes, member counts, hashes, migration version, analytic/reconciliation counts, failure-injection boundaries, recording actions, agent runs, correction rounds, full-suite executions, and state `SIMULATED`.
- [ ] Perform the required final review. With no authorized review agent, use and disclose controller self-review; resolve any Critical or Important finding within one correction round.
- [ ] Commit with `docs: complete ProjectOS phase 4 handoff` and stop without real intake, refresh, cutover, push, merge, or worktree removal.

## Completion gate

Phase 4 local implementation is complete when all twelve tasks are committed; schema 3 upgrades safely; collection, import, analytics, GAS authorization, reconciliation, conditional ContextOS queries, and reversible cutover preparation work from the installed wheel; all four subphase candidate gates pass; deterministic artifacts verify; and support remains `SIMULATED`.

Completion does not claim that the other machine was inspected, Google refreshed, macOS or Windows collector behavior was natively verified, or legacy automation was cut over. Those states advance only from separately authorized, returned, verified evidence.
