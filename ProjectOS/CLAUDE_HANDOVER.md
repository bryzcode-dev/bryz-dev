# Claude Handover: ProjectOS Destination-Machine Rollout

You are receiving a portable ProjectOS release-candidate package. Your job is to inspect the destination machine, verify the package, and prepare a staged rollout without silently crossing any live boundary.

## Binding product decisions

1. SQLite is the single source of truth. Google Sheets and GAS are editable collaboration surfaces only.
2. ProjectOS is a separate build adopted by ContextOS as an enhancement. ContextOS remains the orchestrator.
3. Support macOS and Windows. Never substitute a machine-specific path from another host.
4. The protected Owner is the only role with full access, user-management authority, or the admin menu.
5. Admin can edit allowlisted fields on PUBLIC projects only and cannot see the admin menu.
6. User is view-only for PUBLIC projects and cannot see the admin menu.
7. PRIVATE projects are visible only to Owner.
8. Credential values never enter ProjectOS. Record only provider, purpose, storage system, and non-secret lookup reference.
9. Scheduled synchronization is designed for every two hours. Skill activation may request an immediate sync through the same guarded runtime entry point.
10. Runtime databases, locks, logs, configuration, journals, and credentials must remain local to each machine and outside ContextOS shared roots.

## Package authority

- `README.md` is the operator overview.
- `PACKAGE_MANIFEST.json` identifies the source revision and expected verification results.
- `MANIFEST_SHA256.txt` is the transfer-integrity authority.
- `SOURCE/` is the portable source authority for this package.
- `ARTIFACTS/python/` and `ARTIFACTS/gas/` are generated outputs and must reproduce from `SOURCE/`.
- `SOURCE/docs/` contains the detailed phase contracts and runbooks.

If these disagree, stop. Do not select the most convenient value. Report the exact conflicting files and values to the Owner.

## First response to the Owner

Before changing anything, report:

- detected operating system and architecture;
- exact Python and Node versions;
- result of the package hash verification;
- exact proposed local ProjectOS runtime path;
- candidate ContextOS roots and how each was discovered;
- whether `context-os/config/extension-contract.json` exists and is compatible;
- whether any existing ProjectOS runtime, database, skill, extension, scheduler, Sheet binding, or Looker tracker is present;
- what information remains missing;
- the next proposed read-only or local-only step.

Do not describe the rollout as installed, adopted, active, connected, or production-ready until evidence proves that exact state.

## Required Owner inputs

Ask only for values that inspection cannot safely determine:

- protected Owner email;
- intended machine ID that contains no username or hostname;
- exact ContextOS root if discovery is ambiguous;
- desired local ProjectOS runtime path if the platform default is not acceptable;
- Google master Sheet ID/URL and any supporting Sheet IDs/URLs;
- GAS script ID and development/production deployment IDs when they already exist;
- non-secret credential reference and its provider/storage system;
- project roots the Owner authorizes for discovery;
- for Looker: exact Git repository, evidence-output directory, expected remote/branch, master Sheet, tracked tabs, validation commands, and legacy scheduler/script definitions.

Never infer credentials, search unrelated folders, or crawl an entire user profile.

## Phase 0: Verify without mutation

1. Read `README.md` and `PACKAGE_MANIFEST.json`.
2. Verify every entry in `MANIFEST_SHA256.txt`.
3. Confirm Python is at least 3.11. On macOS, do not accidentally use `/usr/bin/python3` when it reports 3.9.
4. Run the Python and GAS test suites from `SOURCE/`.
5. Rebuild the wheel and GAS output into a new temporary directory.
6. Compare rebuilt artifacts with the supplied artifacts.
7. Inventory existing ProjectOS and ContextOS state read-only.

Any checksum, test, rebuild, compatibility, or provenance failure is fail-closed. Preserve the evidence and stop before installation.

## Phase 1: Stage the local ProjectOS runtime

Use a target-local directory outside ContextOS and shared/network storage.

Recommended defaults:

- macOS runtime: `$HOME/Library/Application Support/ProjectOS`
- macOS logs: `$HOME/Library/Logs/ProjectOS`
- Windows runtime: `%LOCALAPPDATA%\ProjectOS`
- Windows logs: `%LOCALAPPDATA%\ProjectOS\logs`

Create an isolated virtual environment and install only the verified wheel. First run database-free commands:

```text
projectos adoption inspect --contextos-root <exact-contextos-root>
projectos adoption profile plan --contextos-root <exact-contextos-root> --python-executable <exact-python>
```

Inspection must not create a SQLite database, modify ContextOS, or write a replacement extension contract.

## Phase 2: Initialize the SQLite SSOT

Only after the Owner accepts the planned runtime path:

1. Create the local runtime directory.
2. Initialize a new schema-3 database.
3. Run `doctor`.
4. Seed exactly one protected Owner.
5. Create Admin and User entries only from Owner-supplied identities.
6. Create credential references without credential values.
7. Create/import projects, locations, resources, deployments, connections, and notes.
8. Run a verified backup before any later live boundary.

Do not reuse, overwrite, merge, or migrate an existing database until its provenance, schema, backup, and rollback path are established.

## Phase 3: Validate synchronization locally

Use the fake Google gateway and invented fixtures first. Validate:

- Owner/Admin/User projection behavior;
- PUBLIC/PRIVATE visibility;
- immutable request validation;
- stale-version conflicts;
- idempotent retry after publication failure;
- verified revision activation;
- lock behavior and dead-PID recovery;
- redacted diagnostics.

A passing fake sync does not authorize Google access.

## Phase 4: Stage ContextOS adoption

The ContextOS contract must be read from:

```text
<contextos-root>/context-os/config/extension-contract.json
```

Required compatibility:

- contract version `1`;
- ContextOS `>=3.0.1,<4.0.0`;
- target operating system listed in `supported_hosts`;
- relative, traversal-free extension and skill roots;
- ProjectOS runtime outside the ContextOS/shared root.

Build and independently verify the extension archive. Inspect its manifest, file hashes, target paths, and forbidden-identifier scan. Stage disabled scheduler definitions. Obtain explicit Owner approval before activating the extension, exposing the skill, or installing a native scheduler.

Activation must be transactional and reversible. Preserve the exact previous registry and target state. On failure, rollback and verify the rollback rather than continuing forward.

## Phase 5: Google Sheet and GAS rollout

Treat these as separate approvals:

1. read-only Google preflight for one exact account and test workbook;
2. reviewed workbook repair/creation plan;
3. test-workbook writes with both local binding and CLI write gates enabled;
4. GAS project upload/deployment;
5. production binding and production deployment.

Identity must come from the authenticated Google session. Never accept a role from URL parameters, form data, local storage, or Sheet cells. The fixture preview's `?role=` parameter is never part of deployed authorization.

Do not copy secrets into Apps Script properties without explicit Owner approval and an approved secret-storage design.

## Phase 6: Looker migration and analytics

Follow the Phase 4 documents in order:

1. `SOURCE/docs/PHASE4A_SOURCE_COLLECTION.md`
2. `SOURCE/docs/PHASE4B_IMPORT_AND_ANALYTICS.md`
3. `SOURCE/docs/PHASE4C_RECONCILIATION.md`
4. `SOURCE/docs/PHASE4D_CUTOVER_AND_ROLLBACK.md`
5. `SOURCE/docs/PHASE4_CLAUDE_IMPLEMENTATION_AND_TROUBLESHOOTING.md`

Source collection is limited to Owner-declared paths and fixed validation command arrays. Return sanitized, verified evidence rather than raw logs or source. Reconciliation requires explicit mappings for every tracked legacy item; empty, incomplete, or ambiguous mappings remain blocked.

Preparation never authorizes cutover. Native execution requires an exact-target, externally HMAC-signed Owner approval and verified ownership. `SIMULATED` packages must be rejected by the real host boundary. If ownership changes or an effect fails, follow the intent journal and rollback procedure exactly.

## Scheduler rules

- Default cadence: every two hours.
- macOS: `launchd` definition.
- Windows: Task Scheduler definition.
- Definitions are generated disabled, inspected, and verified before activation.
- Scheduled and skill-triggered sync use the same runtime entry point and mutual-exclusion lock.
- Never install a scheduler using a virtual-environment or database path that has not been verified on the destination host.
- Never use `--force`, manual lock deletion, or parallel sync as troubleshooting shortcuts.

## Troubleshooting decision table

| Finding | Required response |
|---|---|
| Python is older than 3.11 | Select/install a supported interpreter; do not patch ProjectOS for the old interpreter. |
| Hash or deterministic rebuild mismatch | Stop, preserve evidence, and obtain a fresh trusted package. |
| ContextOS contract missing/incompatible | Stop adoption; do not create or rewrite the contract from ProjectOS. |
| Existing database/runtime found | Inventory and back it up; do not overwrite or merge automatically. |
| Runtime overlaps ContextOS/shared/network storage | Choose a machine-local path. |
| Google identity is blank, inactive, malformed, or unlisted | Return no data; do not add a fallback identity. |
| Sheet contract contains unknown populated tabs or reordered headers | Block mutation and request Owner review. |
| Sync is locked | Validate lock metadata and PID ownership; age alone is insufficient. |
| SQLite committed but Sheet publication failed | Retry through the normal sync path; rely on the durable receipt. |
| Native host evidence says `SIMULATED` | Do not relabel it as real or advance support state. |
| Looker repository changes during collection | Stop and recollect only after the source stabilizes and approval is renewed. |
| Cutover approval, ownership, or rollback evidence is invalid | Stop external effects and preserve all evidence. |

## Prohibited shortcuts

Do not:

- store credential values in SQLite, Sheets, logs, manifests, prompts, or commits;
- edit SQLite tables or migration history manually;
- make Admin equivalent to Owner;
- reveal PRIVATE projects, identifiers, counts, or connections to non-Owners;
- authorize from client-supplied roles;
- bypass workbook, revision, ownership, signature, or evidence checks;
- use `force`, purge, manual lock deletion, or destructive cleanup;
- activate native jobs merely because generated definitions look correct;
- disable the legacy tracker in the same step that prepares cutover;
- push, merge, or publish without explicit approval.

## Completion evidence

A destination rollout report should record, without secrets:

- package version, source commit, and verified manifest hash;
- operating system, machine ID, and exact local runtime path;
- Python, Node, ContextOS, schema, contract, and extension versions;
- test totals and deterministic rebuild hashes;
- database backup manifest and health result;
- adoption transaction and rollback evidence;
- skill discovery proof;
- scheduler definition and activation state;
- Google binding/deployment state and verified projection revision;
- Looker intake/reconciliation/cutover state;
- every separate approval boundary crossed;
- remaining simulated or unverified claims.

If a claim lacks evidence, label it unverified. ProjectOS is ready only to the highest stage that has passed its own gate.

