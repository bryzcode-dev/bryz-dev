# ProjectOS Phase 4 — Looker Migration and Analytics Design

**Date:** 2026-09-27
**Status:** Approved design; implementation planning pending
**Prerequisite:** Phase 3D-B local candidate at `f2cfea0`
**Parent specification:** `2026-09-26-projectos-contextos-enhancement-design.md`

## 1. Purpose

Phase 4 replaces an existing machine-local Looker Git and Google Sheet tracking workflow with a ProjectOS-managed migration and analytics system. It begins with a portable, read-only collector that can run on macOS or Windows without requiring ProjectOS to reach into another machine. The collector returns a deterministic, sanitized evidence archive. ProjectOS imports copied evidence into SQLite, computes relationship and code-status analytics, reconciles those results with the legacy tracker, and prepares a reversible cutover.

ContextOS remains the controller. ProjectOS remains an optional ContextOS enhancement. SQLite remains the single source of truth. The Google Sheet and GAS web application remain authorized collaboration and reporting surfaces, never authoritative databases.

Phase 4 does not assume that the build machine is the Looker source machine. It does not embed one user's home directory, hostname, operating system, repository path, or scheduler. All source-machine facts arrive through explicit intake or sanitized evidence.

## 2. Outcomes

Phase 4 delivers:

- a dependency-free, cross-platform, read-only source collector;
- a deterministic evidence archive describing the existing Looker workflow;
- LookML inventory and dependency analysis;
- safe Git, scheduler, Sheet, GAS, validation, and credential-reference metadata;
- versioned SQLite migration and provenance-bound import;
- role-correct Looker analytics in the ProjectOS web application;
- staged and parallel reconciliation with the legacy tracker;
- a cutover package, preserved legacy archive, and rehearsed rollback;
- a Claude implementation and troubleshooting handoff for the source machine;
- explicit approval gates before real refresh and before disabling legacy automation.

Phase 4 does not:

- copy secret values, OAuth tokens, cookies, SSH keys, service-account files, or credential contents;
- execute arbitrary commands discovered in repository files or scheduler definitions;
- modify the Looker Git repository during intake;
- modify a Google Sheet, GAS deployment, scheduler, or source-machine script during evaluation;
- infer a schema from observed files and silently migrate production SQLite;
- accept simulated evidence as proof of a real refresh or cutover;
- disable legacy automation without a target-specific Owner approval.

## 3. Phase decomposition

### 3.1 Phase 4-A — Portable intake and read-only evaluation

Build and verify the collector, evidence model, evaluation report, and source-machine handoff. All automated tests use invented fixtures. A real source-machine collection is a separate read-only authorization boundary because it inspects user-supplied paths and may run explicitly allowlisted validation commands.

### 3.2 Phase 4-B — SQLite import and analytics

Add the versioned schema, evidence importer, LookML parsers, dependency graph, analytics services, CLI contracts, and GAS projection. Imports operate on copied archives and commit atomically.

### 3.3 Phase 4-C — Parallel reconciliation

Compare ProjectOS results with the preserved legacy tracker. Reconciliation is staged with fixtures before any real refresh. A real refresh uses existing authenticated boundaries and requires separate approval.

### 3.4 Phase 4-D — Cutover preparation and approved cutover

Create the cutover checklist, legacy snapshot, final parity report, rollback package, and bounded disablement plan. Preparation is local and reversible. Actual disablement of legacy scripts, triggers, launch agents, scheduled tasks, or Sheet automation is a separate target-specific Owner action.

## 4. Source-machine intake contract

The Owner supplies these runtime values:

- a generated source-machine ID that contains no username or hostname;
- operating-system family: `macos` or `windows`;
- absolute Looker Git project folder;
- expected Git remote identity, primary branch, and ownership context;
- master Google Sheet URL or ID and relevant tab names;
- GAS script project ID, deployment IDs, and local GAS source folder when present;
- current local synchronization script paths;
- scheduler definitions that invoke those scripts;
- validation command declarations and expected result contracts;
- credential storage systems by safe reference only;
- an output directory outside the source repository.

The intake file is canonical JSON with schema version `1`. Paths are runtime inputs and never become portable archive member names. Google identifiers are normalized into safe typed references. Credential references identify the provider, label, storage system, and non-secret lookup reference; their resolved values are prohibited.

The collector rejects:

- missing or symlinked repository roots;
- an output root inside the repository;
- elevated execution when standard-user access is sufficient;
- unsupported operating systems;
- duplicate or unknown intake fields;
- validation commands outside the explicit command envelope;
- environment-variable expansion, shell syntax, pipes, redirects, or command substitution;
- secret-bearing arguments or paths identified by the safety scanner.

## 5. Portable collector architecture

The collector is a separate `projectos.looker.collector` package and an installed-wheel entrypoint. It uses Python standard-library APIs and fixed argument arrays with `shell=False`. Platform adapters may inspect scheduler definitions, but they do not enable, disable, create, remove, or trigger tasks.

The collector executes these ordered stages:

1. validate the intake and standard-user session;
2. issue a new collection run ID and local journal;
3. inventory regular repository files without following links;
4. parse supported LookML, manifest, dashboard, and metadata files;
5. inspect Git through fixed, read-only commands;
6. inspect supplied Sheet/GAS configuration files without authenticating Google;
7. inspect supplied scheduler definitions and synchronization scripts as text;
8. run only Owner-declared validation command envelopes;
9. normalize safe credential references without resolving them;
10. generate typed findings, source hashes, and bounded diagnostics;
11. scan every portable member for secrets and machine identifiers;
12. seal the evidence archive atomically.

Interrupted collection may resume only from a matching canonical journal. Collection never cleans or rewrites source files. Recovery removes only an incomplete temporary archive below the declared output root.

## 6. Command envelope

Validation commands use a typed declaration:

- `command_id`;
- fixed executable name or Owner-approved absolute executable path;
- fixed argument array;
- working directory constrained below the repository root;
- timeout from 1 through 600 seconds;
- expected exit codes;
- stdout and stderr handling policy;
- optional safe parser identifier.

The collector captures bounded validation summaries, not unrestricted output. Raw output remains local and excluded by default. Parsers may retain allowlisted counts, status codes, test names, and redacted messages. Unknown parsers fail closed.

No collected repository file can introduce a command. Scheduler and script contents are evidence, not executable instructions.

## 7. Evidence archive contract

The deterministic archive is named `projectos-looker-intake-v1.zip` and contains only regular UTF-8 files with portable relative paths:

- `intake-manifest.json` — release, source, run, inventory, and member hashes;
- `repository.json` — safe Git identity, branch, divergence, dirty-state summary, and last commit;
- `looker-assets.json` — normalized file, model, view, explore, dashboard, include, and project-dependency records;
- `looker-relationships.json` — typed graph edges and unresolved references;
- `legacy-tracker.json` — declared Sheet/GAS schemas and safe references;
- `automation.json` — normalized script and scheduler definitions without command output or secrets;
- `validation.json` — bounded declared-command results;
- `credential-references.json` — safe references only;
- `findings.json` — parse, integrity, drift, and risk findings;
- `SHA256SUMS.txt` — canonical member hashes.

The manifest binds:

- evidence schema and collector versions;
- source-machine ID and host family;
- collection run ID and canonical UTC timestamps;
- repository root fingerprint, never its absolute path;
- Git HEAD and declared primary branch;
- all archive member sizes and SHA-256 hashes;
- intake declaration SHA-256;
- collector wheel SHA-256;
- excluded-artifact categories;
- completion and scan state.

Archives reject traversal, absolute paths, links, devices, duplicate case-folded names, extra members, noncanonical JSON, corrupt ZIP entries, unknown fields, invalid hashes, secret patterns, email addresses, resolved home paths, hostnames, native command output, and raw credential material.

## 8. LookML analysis model

The parser supports the repository forms present in copied fixtures and records unsupported constructs as findings. It never attempts to execute Liquid, SQL, extension code, or imported scripts.

Assets include:

- project manifests;
- model files;
- views and view extensions;
- explores and explore extensions;
- dashboards and dashboard elements;
- includes and imports;
- connection-name references;
- datagroups and persistence references;
- local synchronization and validation artifacts.

Relationship edges include:

- project imports;
- model includes view;
- explore references view;
- join references view;
- dashboard references model/explore;
- view extends view;
- model references connection;
- asset originates from file;
- project uses credential reference;
- tracker row maps to canonical asset.

Every asset and edge includes source run, source member, content hash, parser version, and line-safe locator metadata. Locators may include portable repository-relative paths and line numbers but never source-machine absolute paths.

## 9. SQLite schema version 3

Migration `0003.sql` extends the reserved Looker foundation without discarding existing rows. It is forward-only, transactional, deterministic, and recorded through the existing migration engine.

Existing `looker_assets` remains the canonical asset inventory. Migration 3 adds provenance columns or companion records needed to bind each asset to an intake import.

New canonical tables are:

- `looker_intake_runs` — archive identity, release, source machine, repository fingerprint, Git facts, status, and timestamps;
- `looker_source_members` — imported member inventory and hashes;
- `looker_relationships` — typed graph edges between canonical assets or unresolved targets;
- `looker_findings` — bounded severity, category, code, subject, status, and provenance;
- `looker_validation_results` — declared validation outcomes and safe measurements;
- `looker_legacy_mappings` — legacy tracker row to canonical entity mapping;
- `looker_reconciliation_runs` — compared versions, counts, parity state, and approval state;
- `looker_reconciliation_items` — individual match, mismatch, missing, extra, or waived outcomes;
- `looker_cutover_packages` — immutable archive, checklist, rollback, and approval references.

`looker_analytics` remains the versioned derived-result store. Analytics never overwrite source facts. An import is idempotent by archive SHA-256 and source run ID. Reimporting identical evidence returns the existing import. A reused source run with different bytes fails closed.

An import transaction verifies the entire archive and parser contract before inserting any row. Failure rolls back schema-visible changes and retains only a redacted local diagnostic.

## 10. Analytics

ProjectOS computes deterministic analytics for:

- model, view, explore, dashboard, file, and connection-reference counts;
- model-to-view, explore-to-view, join, extend, dashboard, and project dependencies;
- unresolved includes, imports, views, explores, connections, and dashboards;
- duplicate asset names and ambiguous resolution;
- orphaned files, views, explores, and dashboard references;
- cross-project and cross-model dependency paths;
- dependency impact for a changed or removed asset;
- Git branch, dirty state, divergence, and last commit;
- validation result and code-status summaries;
- legacy tracker coverage and mapping completeness;
- last declared Sheet refresh and last successful synchronization;
- migration version, import provenance, drift, reconciliation, and cutover state;
- credential-reference usage without secret exposure.

Analytics are keyed by project, intake run, analytic type, and parser version. Recalculation writes a new version and retains the prior result for comparison.

## 11. Import and discovery workflow

Import is Owner-only and uses an explicit database path. The CLI verifies the archive before opening SQLite for mutation. The archive must refer to an existing ProjectOS project or an Owner-approved new project registration request.

The workflow is:

1. `looker intake verify` — read-only archive verification;
2. `looker intake preview` — read-only source-to-target mapping and findings;
3. `looker intake import` — Owner-only atomic SQLite import;
4. `looker analytics build` — deterministic derived analytics;
5. `looker analytics show` — role-filtered query;
6. `looker reconcile stage` — fixture or copied legacy comparison;
7. `looker reconcile report` — immutable reconciliation result;
8. `looker cutover prepare` — local cutover and rollback package;
9. separately authorized refresh or cutover commands exposed only by dedicated host modules.

The ordinary CLI has no force, purge, arbitrary SQL, credential resolution, scheduler disablement, or legacy teardown option.

## 12. Reconciliation

Reconciliation compares an immutable ProjectOS analytic version with an immutable legacy snapshot. Comparison dimensions are declared in a canonical policy rather than inferred at runtime.

Required dimensions include:

- asset counts by type and project;
- model/view/explore relationships;
- broken and orphaned reference counts;
- dashboard coverage when present;
- tracker-row mapping completeness;
- validation and code-status outcomes;
- refresh timestamps and source revisions;
- credential-reference usage counts.

Each item is `MATCH`, `MISMATCH`, `MISSING_SOURCE`, `MISSING_TARGET`, or `WAIVED`. Only Owner may waive, and a waiver requires a reason, actor, timestamp, and audit event. Required mismatches prevent cutover preparation from becoming ready.

Fixture reconciliation is not evidence of a real refresh. A real refresh record binds the Google/GAS execution receipt, intake run, analytic version, resulting projection revision, and validation result. It requires separate authorization and uses the existing guarded Google boundary.

## 13. Web application

Phase 4 extends the existing GAS application rather than creating a second application.

Owner capabilities:

- view all PUBLIC and PRIVATE Looker projects;
- inspect safe intake, Git, validation, migration, reconciliation, and cutover details;
- import approved change requests through the existing SQLite synchronization workflow;
- resolve mappings and reconciliation waivers;
- manage Looker-related user-visible settings without exposing secrets.

Admin capabilities:

- view and edit allowlisted PUBLIC-project descriptive fields through change requests;
- view PUBLIC Looker analytics and safe findings;
- no PRIVATE projects, user management, admin menu, import, waiver, refresh, or cutover controls.

User capabilities:

- view PUBLIC Looker analytics and safe status only;
- no edit, admin, import, waiver, refresh, or cutover controls.

The server applies authorization before querying or serializing. Counts, search, graph traversal, error messages, autocomplete, and connection names cannot reveal PRIVATE projects. The browser consumes server-issued capabilities and never supplies a role.

Web surfaces include an overview, dependency explorer, findings list, Git/code status, refresh history, migration timeline, reconciliation detail, and Owner-only cutover readiness panel. Empty, offline, stale, incomplete, and unauthorized states use non-disclosing accessible copy.

## 14. ContextOS integration

After Phase 4-B fixture verification, the ProjectOS extension may declare new read-only capabilities:

- `looker-status`;
- `looker-assets`;
- `looker-dependencies`;
- `looker-findings`;
- `looker-impact`;
- `looker-reconciliation`.

The canonical ProjectOS skill remains unavailable for these capabilities until the installed extension version and SQLite schema both support them. ContextOS calls the adapter; it never reads or edits SQLite directly. State-changing import, waiver, refresh, and cutover operations remain deterministic CLI or dedicated host operations with Owner authorization.

An extension upgrade stages beside the active version, verifies migration compatibility and skill bytes, rehearses rollback, and changes discovery only through the existing adoption transaction.

## 15. Cutover and rollback

Cutover readiness requires:

- a verified real intake archive;
- successful schema migration and backup;
- complete required source-to-target mappings;
- analytics parity for required dimensions;
- a successful real refresh;
- passing validation commands;
- preserved legacy Sheet, scripts, scheduler definitions, and Git snapshot;
- a tested rollback package;
- no unresolved Critical or Important findings;
- explicit Owner approval for the exact source machine and automation targets.

The cutover transaction records intent before each external effect. It disables discovery or triggering before removing automation, verifies ownership before every change, and stops without deletion on any uncertainty. It never deletes the legacy archive.

Rollback restores the exact captured legacy scheduler or trigger state, script configuration, Sheet/GAS references, and ProjectOS extension state. SQLite retains imported evidence, audit history, and reconciliation records. Database purge is never implied by rollback.

## 16. Security and privacy

Mandatory controls include:

- standard-user collection;
- no network during local automated tests;
- no Google authentication during intake unless a separately authorized validation explicitly requires it;
- no secret resolution or storage;
- no shell command construction;
- fixed command arrays and bounded timeouts;
- symlink and path-escape rejection;
- deterministic archive inventories and hashes;
- identifier, email, home-path, hostname, token, key, and credential-content scans;
- canonical JSON and strict unknown-field rejection;
- redacted errors and bounded diagnostics;
- SQLite transactions and immutable provenance;
- server-side role and visibility enforcement;
- retained audit events for every import, waiver, refresh acceptance, and cutover action.

## 17. Failure handling

| Failure | Required behavior |
|---|---|
| Unsupported or malformed LookML | Record a bounded finding; continue only when the archive can remain internally consistent |
| Repository changes during collection | Fail sealing and require a fresh collection |
| Dirty or divergent Git state | Record typed status; policy may block reconciliation but intake remains read-only |
| Validation timeout or nonzero exit | Record bounded failure; never retry an unsafe command automatically |
| Unknown Sheet/GAS schema | Produce a mapping finding; do not infer new canonical columns |
| Secret or machine identifier found | Fail archive sealing and identify only the member/category |
| Archive hash or inventory mismatch | Reject before opening SQLite for mutation |
| Import failure | Roll back the entire transaction |
| Duplicate run with different bytes | Reject as provenance conflict |
| Analytics mismatch | Persist reconciliation findings; do not advance readiness |
| Refresh failure | Preserve legacy operation and ProjectOS state; do not cut over |
| Ownership uncertainty during cutover | Stop without disabling or deleting anything |

## 18. Testing and evidence

### 18.1 Focused tests

- intake schema, path isolation, session, and command-envelope validation;
- macOS and Windows collector contracts;
- LookML fixtures for models, views, explores, dashboards, includes, extends, joins, and imports;
- malformed, cyclic, duplicate, missing, and unsupported reference handling;
- Git parsing and repository-change detection;
- Sheet/GAS and scheduler text inspection;
- secret, identifier, traversal, duplicate, symlink, device, and corruption rejection;
- schema-2 to schema-3 migration and rollback;
- idempotent and conflicting imports;
- graph construction, analytics, impact, and provenance;
- reconciliation policy and Owner-only waivers;
- authorization and PRIVATE non-disclosure in Python and GAS;
- extension upgrade and conditional Looker capability discovery;
- installed-wheel collection, verification, import, and analytics without a source checkout.

### 18.2 Release-candidate gates

Each subphase uses TDD and focused gates. The complete Python and GAS regression suites run once when that subphase reaches its final candidate. Changed web surfaces receive desktop and mobile visual inspection plus accessibility checks. Portable artifacts record SHA-256 hashes, member counts, source revision, scan results, failure-injection boundaries, and support state.

Automated evidence remains `SIMULATED`. Real source-machine intake, real refresh, and cutover are three separate authorization and evidence boundaries. A macOS intake does not verify Windows collection behavior, and vice versa.

## 19. Operations and handoff

The Phase 4 delivery includes:

- source-machine collector operations for macOS and Windows;
- a Claude handoff that requests every required intake value and explains safe troubleshooting;
- archive verification and transfer instructions;
- ProjectOS import, analytics, backup, and reconciliation operations;
- Google/GAS refresh operations behind the existing guarded boundary;
- cutover preparation, approval, execution, and rollback runbooks;
- verification documents that distinguish simulated, collected, refreshed, and cut-over states.

Troubleshooting never recommends force, purge, manual database edits, secret copying, arbitrary shell commands, disabling protections, or deleting uncertain legacy state.

## 20. Completion criteria

Phase 4 is complete only when:

1. the portable collector produces deterministic, sanitized evidence on supported host contracts;
2. copied fixtures import through migration 3 without loss or partial mutation;
3. LookML assets, relationships, findings, Git state, validation state, and credential references have traceable provenance;
4. analytics and impact queries are deterministic and role-correct;
5. the GAS application exposes PUBLIC analytics without PRIVATE leakage;
6. reconciliation reports every required dimension and prevents readiness on unresolved required mismatches;
7. a real intake and real refresh are separately authorized and verified;
8. the legacy archive and rollback rehearsal pass;
9. cutover is performed only after exact-target Owner approval;
10. all focused, regression, security, migration-integrity, accessibility, installed-wheel, and artifact gates pass.

Implementation stops at each external boundary. The build may complete all local and simulated subphases autonomously, but it may not inspect the other machine, authenticate Google, run a real refresh, disable legacy automation, push, merge, or publish without the applicable explicit instruction.
