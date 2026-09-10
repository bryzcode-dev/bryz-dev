# DataCube local-only skill toolkit

This repository is a four-skill operating system for designing and delivering a DataCube from Google Drive CSV files and Google Sheets, with BigQuery as the durable analytical engine and Google Apps Script as a thin dashboard facade. The assistant works entirely from local project files. Google execution is prepared as an explicit handoff and is never falsely reported as tested.

## What is included

| Skill | Invoke when | Primary output |
| --- | --- | --- |
| `datacube-design-contract` | Defining source meaning and cube semantics | Versioned source and cube contract |
| `datacube-ingestion-build` | Building ingestion, staging, marts, and watchdog state | Idempotent pipeline and atomic publication design |
| `datacube-gas-query-api` | Building the dashboard-facing GAS interface | Bounded, allowlisted, versioned query API |
| `datacube-release-operations` | Validating and promoting a release | Evidence manifest, connected handoff, rollback plan |

The split is intentional. It creates hard phase gates without loading every instruction into every task. Use one skill for focused work; use all four in the order above for an end-to-end project.

## Prerequisites

- Node.js 20 or newer for the included scripts and tests.
- Git for preserving and reviewing skill changes.
- Codex or Claude Code with repository-level skill discovery.
- No package installation and no network access are required.

## Install in a project

Copy the repository contents into the project root, or copy `skills/`, `scripts/`, `shared/`, `AGENTS.md`, and `CLAUDE.md`. Preserve the relative symbolic links under `.agents/skills/` and `.claude/skills/`. On a system that did not preserve links, recreate them from the project root:

```bash
mkdir -p .agents/skills .claude/skills
for name in datacube-design-contract datacube-ingestion-build datacube-gas-query-api datacube-release-operations; do
  ln -s "../../skills/$name" ".agents/skills/$name"
  ln -s "../../skills/$name" ".claude/skills/$name"
done
```

Do not install the same canonical files twice. Both hosts should resolve their links to `skills/<skill-name>` so edits and policy stay identical.

## End-to-end operating flow

1. Place representative, redacted source samples and existing SQL/GAS code in the project.
2. Invoke `datacube-design-contract`. Write the source contract and run its validator.
3. Invoke `datacube-ingestion-build`. Profile CSVs, define Drive/Sheet adapters, fingerprints, state transitions, BigQuery layers, quality gates, and immutable publication.
4. Invoke `datacube-gas-query-api`. Define the request and response contract; implement pure local validation, allowlists, query construction, cache keys, limits, and thin service adapters.
5. Produce expected and actual metric fixtures and run reconciliation.
6. Invoke `datacube-release-operations`. Assemble the evidence manifest and run preflight.
7. Hand only the connected checklist to an authorized Google runner. After real BigQuery dry-run and GAS smoke-test evidence is attached, rerun preflight before promotion.

## Commands

```bash
node scripts/validate-contract.mjs shared/fixtures/valid/source-contract.json
node scripts/profile-csv.mjs shared/fixtures/valid/sales.csv --key order_id
node scripts/reconcile-fixtures.mjs shared/fixtures/valid/reconciliation-expected.json shared/fixtures/valid/reconciliation-actual.json
node scripts/release-preflight.mjs shared/fixtures/valid/release-manifest.json
node --test tests/*.test.mjs
```

Each validator writes machine-readable JSON where practical and uses a nonzero exit status for failure. The release preflight returns `READY_FOR_CONNECTED_VALIDATION` when local checks pass but required Google checks remain `NOT RUN`; that is the correct offline result.

## Project artifacts to create

- `contracts/source-contract.json`: source identities, grain, types, mappings, keys, dimensions, measures, quality, freshness, and sensitivity.
- `fixtures/`: representative redacted inputs and expected metric aggregates.
- `sql/`: staging, canonical, quality, and aggregate queries with no embedded credentials.
- `gas/`: pure request validation/query-builder functions plus thin Apps Script adapters.
- `evidence/`: local reports and imported connected-environment reports.
- `release/release-manifest.json`: immutable versions, check states, artifacts, and rollback target.

## Status discipline

- `PASS`: the check ran in the stated environment and evidence exists.
- `FAIL`: it ran and violated an acceptance criterion.
- `NOT RUN`: it was not executed.
- `BLOCKED`: a missing prerequisite makes safe progress impossible.

Offline work should normally end with local gates at `PASS` and BigQuery/GAS gates at `NOT RUN`. That distinction is a feature, not an incomplete test report.
