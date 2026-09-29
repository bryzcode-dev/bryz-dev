# ProjectOS Phase 2 — Claude Implementation and Troubleshooting Guide

This document is the portable handoff for a Claude session implementing, installing locally, or diagnosing ProjectOS Phase 2 on a different Mac. It supplies operating boundaries and a deterministic workflow; the canonical product requirements remain in `docs/superpowers/specs/2026-09-26-projectos-phase-2-google-interface-design.md`.

## 1. Authority order

Use this order when instructions differ:

1. current user instructions and machine safety policy;
2. repository `AGENTS.md` and applicable skills;
3. the Phase 2 specification;
4. the reviewed Phase 2 implementation plan;
5. this troubleshooting guide;
6. implementation details and comments.

Never infer live Google-write, deployment, scheduler-installation, Context OS adoption, migration, push, or deletion authority from a request to build or troubleshoot locally.

## 2. Phase 2 operating boundary

Safe without further live authorization:

- inspect the repository and local configuration examples;
- create an isolated Git worktree;
- run tests, static checks, builds, and fake-gateway workflows;
- create temporary local SQLite databases and invented workbook fixtures;
- write implementation code and documentation from the reviewed plan;
- generate dry-run Google bootstrap or repair plans;
- inspect redacted diagnostic output supplied by the user.

Requires explicit current-task authorization and resolved identifiers:

- authenticating a Google account;
- reading a real spreadsheet or Drive permission list;
- creating or modifying Sheets, GAS projects, deployments, OAuth clients, Script Properties, Drive permissions, or GCP resources;
- enabling a real binding or Google writes;
- installing `launchd` or the Context OS skill;
- moving or replacing a production database;
- inspecting or changing the existing Looker tracker.

## 3. Start-of-session checklist

Before editing:

1. Read repository `AGENTS.md` and applicable skill instructions completely.
2. Confirm the repository root and current Git state.
3. Read the Phase 2 specification and reviewed implementation plan completely.
4. Confirm the Phase 1 base commit required by the plan.
5. Create or enter the isolated Phase 2 worktree.
6. Confirm Python is 3.11 or newer.
7. Run the Phase 1 suite before schema or repository changes.
8. Confirm no real Google identifiers or credentials are present in fixtures or tracked files.
9. Record the exact implementation task, base commit, focused test, and stopping condition.

Do not copy an absolute path from another machine. Resolve paths from the current repository and documented environment variables.

## 4. Portable machine facts to resolve

Record these locally; do not commit real values:

| Fact | Safe placeholder |
|---|---|
| Machine ID | `work-mac` |
| Repository root | resolved by `git rev-parse --show-toplevel` |
| ProjectOS home | `PROJECTOS_HOME` or macOS default |
| SQLite path | derived from ProjectOS home unless overridden |
| Environment | `development`, `staging`, or `production` |
| Workbook binding UUID | generated local UUID |
| Spreadsheet ID | omitted until an authorized Google stage |
| Protected Owner email | omitted from fixtures; supplied through protected onboarding config |
| Credential reference | safe Keychain/ADC locator, never credential material |
| Workbook contract version | `1` for the initial Phase 2 contract |

If a required live fact is missing, continue with the fake gateway or stop at the documented Google boundary. Do not invent account IDs, URLs, Sheet IDs, script IDs, deployment IDs, emails, or credential locations.

## 5. Expected source layout

The reviewed implementation plan determines exact paths. The design expects clear units equivalent to:

```text
src/projectos/                    Existing Phase 1 core
src/projectos/migrations/0002.sql Canonical users and Google sync state
src/projectos/google/             Contract, gateways, bootstrap, diagnostics
src/projectos/sync/               Authorization, requests, projection, runner, lock
gas/                              Modular Apps Script application
tests/                            Python tests and Google fixtures
gas/test/                         Local JavaScript authorization/serialization/UI tests
config/                           Identifier-free examples and schema
docs/                             Operations, verification, and this guide
```

Avoid a single sync or GAS file that owns authorization, transport, persistence, and presentation simultaneously. Each unit must expose a testable interface described by the implementation plan.

## 6. Standard local workflow

Use the Python selected for the machine, provided it is 3.11 or newer. Replace `<python>` with that resolved executable.

```bash
<python> -m unittest discover -s tests -v
<python> -m compileall -q build_backend.py src tests
<python> -m pip wheel . --no-deps --no-build-isolation -w build/wheel-check
git diff --check
```

Phase 2 focused commands will be specified task-by-task in the reviewed plan. Use test-driven development: observe the named test fail for the intended missing behavior, implement the smallest complete behavior, and rerun the focused tests before broader gates.

For GAS, use the repository's pinned local command from the implementation plan. Do not install global packages or use an unpinned package version merely to make a command run.

The Phase 2 implementation is complete through local Level A. Start a new machine by building and installing the repository wheel, not by recreating files from this guide. Verify `projectos --help`, schema version `2`, the full Python suite, and the Node suite before diagnosing environment-specific behavior.

## 7. Three activation levels

### Level A — local safe mode

- Fake gateway only.
- Invented workbook fixtures.
- Google optional dependencies may be absent.
- Real gateway imports must not break the core.
- No account login or network write.
- This is the default for implementation and regression tests.

### Level B — authorized Google read-only staging

- Requires explicit permission to authenticate and read the named test workbook.
- Binding identifies a test environment.
- `enabled` may be true; `write_enabled` remains false.
- Run identity, contract, header, and sharing preflight only.
- Save only redacted results.

### Level C — authorized Google write staging

- Requires explicit permission naming the test workbook/GAS project and permitted actions.
- Requires a verified SQLite backup and a workbook backup/export plan.
- Binding and CLI write gates must both be enabled.
- Apply only the reviewed bootstrap or repair plan.
- Verify read-back hashes/counts and rollback instructions immediately.

Production deployment, scheduler installation, Context OS adoption, and Looker cutover are not Phase 2 Level C. They require later plans.

## 8. Configuration rules

- Commit only identifier-free examples.
- Keep real config in the machine-local ProjectOS home.
- Keep credentials in Keychain, ADC, or another approved external provider.
- Store only a safe credential reference in SQLite.
- Never put tokens, client secrets, private keys, cookies, authorization headers, or refresh tokens in TOML, fixtures, Script Properties returned to clients, logs, screenshots, or diagnostic bundles.
- Do not rely on shell history for credential commands.
- Real Google writes default to disabled after install, restore, or config regeneration.

If configuration schema validation fails, fix the configuration or code contract. Do not bypass validation by adding permissive fallback keys.

## 9. Implementation sequence for Claude

Follow the reviewed implementation plan exactly. At a high level, preserve this dependency order:

1. migration and protected canonical users;
2. workbook contract and bootstrap planner;
3. gateway protocol and fake gateway;
4. authorization and field policy;
5. change-request receipts and conflicts;
6. projection builder and revision publication;
7. sync lock, checkpoints, runner, and failure recovery;
8. JSON CLI and redacted diagnostics;
9. GAS server authorization and query layer;
10. GAS UI and request lifecycle;
11. clean-room portability and release evidence.

Do not start GAS UI work before authorization and role-safe serialization have executable tests. Do not connect the real gateway before fake-gateway interruption/retry tests pass.

## 10. Troubleshooting decision tree

### 10.1 The repository or base is unclear

1. Stop edits.
2. Resolve the Git root and show the current commit/status.
3. Locate the reviewed Phase 2 plan and its required base.
4. If the commit is unavailable, ask for the correct repository/ref; do not recreate Phase 1 from memory.

### 10.2 Python or package build fails

1. Record `python --version` and module availability without installing anything.
2. Require Python 3.11+.
3. Run the dependency-free wheel-backend test.
4. Run `pip wheel --no-deps --no-build-isolation`.
5. If the self-hosted backend cannot be imported, confirm repository root and `backend-path` before changing packaging.
6. Do not download a new backend as a first response; the Phase 1 package intentionally builds offline.

### 10.3 Migration or database open fails

1. Preserve the database and sidecars; do not delete or rewrite them.
2. Run the read-only/fail-closed doctor path.
3. Record current and supported schema versions.
4. For a newer schema, use compatible code rather than downgrading the file.
5. For integrity or foreign-key failure, stop sync and restore only from a verified backup to a separate target.
6. Never replace an active database or one with unresolved `-wal`/`-shm` sidecars.

### 10.4 Sync reports locked

1. Read safe lock metadata.
2. Confirm whether the recorded PID is alive and belongs to ProjectOS.
3. If alive, do not start another sync.
4. If dead, follow the reviewed stale-lock recovery function and tests.
5. Never remove a lock solely because it is old; elapsed time is evidence, not proof.

### 10.5 Google authentication fails

1. Confirm the requested activation level and explicit authorization.
2. Confirm only the credential provider/reference, never print the credential.
3. Verify the authenticated account identity through the gateway's safe preflight.
4. Confirm the account matches the configured Owner or automation identity.
5. Leave `write_enabled=false` until identity, workbook, sharing, and contract checks pass.
6. Do not switch accounts or create credentials without user direction.

### 10.6 Wrong workbook, missing tab, or header drift

1. Stop before writes.
2. Compare spreadsheet ID, workbook contract version, tab names, header order, and hashes.
3. Produce the non-mutating bootstrap/repair plan.
4. Classify additions, missing fields, reordered fields, and unknown data separately.
5. Never silently rename, delete, clear, or repurpose a tab.
6. Apply a repair only at authorized Google write staging.

### 10.7 Unexpected Sheet sharing

1. Block writes.
2. Report only permission categories and safe account identifiers approved for diagnostics.
3. Do not remove sharing automatically.
4. Require the Owner to resolve sharing, then rerun preflight.

### 10.8 GAS says caller email is blank

1. Treat the caller as unauthorized.
2. Verify deployment access mode and organization behavior.
3. Do not fall back to a form field, query parameter, browser storage, or client-supplied email.
4. If the environment cannot provide a trustworthy identity, stop deployment design and report the incompatibility.

### 10.9 Admin or User can see private data

Treat this as a release-blocking authorization defect:

1. Disable the affected deployment if authorized; otherwise report immediately.
2. Reproduce with role fixtures.
3. Trace filtering before serialization, search, count, graph, error, and analytics paths.
4. Fix the earliest authorization boundary, not only the visible component.
5. Run the full cross-role/private-leak suite.
6. Do not redeploy until the suite and a staged role check pass.

### 10.10 Request remains pending

1. Search receipts by request UUID and hash.
2. Check the last durable checkpoint and sync run status.
3. If no receipt exists, inspect pull/preflight without editing the request row.
4. If a receipt and result exist, republish; do not reapply the mutation.
5. If UUID content differs, mark tampered and preserve both evidence hashes.

### 10.11 Request becomes a conflict

1. Confirm the submitted base version and current canonical version.
2. Do not overwrite canonical data automatically.
3. Present safe field differences only to Owner.
4. Resolution creates a new transaction; it never rewrites request history.

### 10.12 SQLite changed but Sheet publication failed

1. Confirm the durable receipt and audit event.
2. Confirm the mutation is not re-executed on retry.
3. Leave the previous projection revision active.
4. Retry result/projection publication with the same durable outcome.
5. Advance the checkpoint only after verified activation.

### 10.13 Projection verification fails

1. Keep the prior revision active.
2. Compare expected and observed row counts, headers, and hashes.
3. Mark the staged revision failed with a safe error code.
4. Do not clear the prior revision.
5. Retry through a new or explicitly reusable staged revision as defined by the plan.

## 11. Safe diagnostic bundle

A diagnostic bundle may contain:

- ProjectOS, SQLite schema, workbook contract, Python, and GAS source versions;
- safe machine/environment names;
- database doctor result;
- binding enabled/write-enabled state;
- spreadsheet ID in the redacted form defined by the implementation plan;
- expected/observed tab and header hashes;
- safe sync run codes, counts, checkpoint, and projection revision IDs;
- lock metadata;
- recent structured error codes;
- file checksums for tracked source and fixture files.

It must not contain:

- tokens, cookies, authorization headers, secrets, private keys, OAuth client secrets, or refresh tokens;
- full credential references when the locator itself is sensitive;
- PRIVATE project names, IDs, counts, rows, graph edges, request contents, or audit payloads;
- raw Sheet exports;
- user notes;
- unredacted emails unless the Owner explicitly requests them for the named diagnostic.

Run the repository's secret and PRIVATE-data scan against every bundle before presenting it.

## 12. Evidence required at each boundary

### Local implementation complete

- focused red/green evidence for every task;
- full Python and GAS suites passing;
- offline wheel build passing;
- fake-gateway interruption and retry workflow passing;
- diagnostic-bundle scans passing;
- clean Git diff/status evidence;
- no live Google or Context OS state changed.

### Google read-only staging ready

- explicit authorization and exact test workbook/account scope;
- local complete evidence;
- identity, sharing, workbook, and contract preflight results;
- writes confirmed disabled.

### Google write staging ready

- explicit authorization naming permitted changes;
- verified SQLite backup;
- workbook backup/export and recovery plan;
- dry-run bootstrap/repair plan reviewed;
- dual write gates verified;
- post-write read-back and rollback checks prepared.

## 13. Handoff format

When stopping or transferring work, report:

- repository root, worktree, branch/detached state, and HEAD;
- spec and plan paths;
- completed task and last commit;
- exact focused and broad verification commands/results;
- active configuration level (A, B, or C);
- whether any external state changed;
- unresolved Confirmed, Probable, and Hypothetical findings separately;
- next task and its required red test;
- any user decision or live authorization still required.

Never summarize a partial or blocked live operation as complete. Preserve rollback artifacts and identify where they live without exposing secret paths or values.

## 14. Different-Mac implementation and adoption procedure

Claude should use this sequence on the rollout Mac:

1. Resolve the checked-out repository root and record `git status`, `git rev-parse HEAD`, Python version, and Node version.
2. Read `README.md`, `docs/PHASE2_OPERATIONS.md`, `docs/PHASE2_SCHEMA.md`, `docs/PHASE2_VERIFICATION.md`, the canonical spec, and the reviewed plan.
3. Run the complete local Level A gates before reading any live identifier.
4. Create a machine-local ProjectOS home and install the built wheel in an isolated environment.
5. If importing an existing Phase 1 database, make and verify a backup, copy it to a staging path, migrate the copy, and compare health/counts before considering a production path.
6. Seed the protected Owner once, then add Admin/User records from Owner-approved input. Do not infer users from Sheet sharing.
7. Keep the Google binding disabled and use invented fixture identifiers until the user approves a Level B plan naming the exact account and workbook.
8. Produce a redacted diagnostic bundle and a handoff report before requesting any live-stage approval.

Context OS adoption is a later atomic operation. Its plan must stage the ProjectOS skill, configuration facade, CLI path, and two-hour scheduling definition; test immediate skill-triggered sync with the fake gateway; preserve local-only database/config/credentials; and provide rollback that removes the adoption pointer without deleting ProjectOS data. The ProjectOS skill must be unavailable unless adoption is active. Context OS remains the orchestrator; ProjectOS remains a separate build and an optional enhancement.

## 15. Troubleshooting evidence packet

When asking another Claude session for help, provide only:

- repository commit and dirty/clean state;
- OS, Python, Node, and ProjectOS versions;
- activation level and whether real Google packages are installed;
- exact redacted command and single JSON response;
- `doctor` response and the generated diagnostic manifest;
- relevant safe error code, binding flags, contract version, and lock metadata;
- expected versus observed behavior.

Do not paste real config, raw Sheet exports, access tokens, OAuth files, Keychain values, PRIVATE rows, user notes, or unredacted emails. If the problem concerns Google or GAS identity, first confirm that explicit live-read authorization exists; otherwise reproduce with the fake gateway and role fixtures.

## 16. Release stopping condition

Phase 2 stops after local verification. A successful local build is not permission to authenticate, deploy GAS, create a Sheet, enable Google writes, install `launchd`, install the Context OS skill, adopt the extension, or inspect/migrate Looker. Prepare a separate, reversible live-staging plan with resolved identifiers and wait for explicit approval.
