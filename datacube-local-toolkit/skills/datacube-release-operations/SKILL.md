---
name: datacube-release-operations
description: Use when preparing, validating, promoting, monitoring, or rolling back a DataCube release while keeping offline evidence separate from connected Google Cloud and Apps Script checks.
---

# DataCube Release Operations

Turn a tested cube build into an auditable release decision. Keep promotion atomic, preserve the last-known-good version, and never upgrade an unexecuted connected check to PASS.

## Offline boundary

Work only with repository files and local commands. Do not access Google Drive, Sheets, BigQuery, Apps Script, GitHub, package registries, MCP servers, or web services. A connected check that cannot run locally remains `NOT RUN` or `BLOCKED`; list the exact handoff command or human action required.

## Workflow

1. Inspect the current contract, build manifest, test reports, release evidence, publication pointer, and rollback record before changing release state.
2. Identify the release, cube, and contract versions. Reject mutable labels such as `latest` as the only identity.
3. Require local evidence for contract validation, fixture reconciliation, idempotency simulation, API-contract tests, secret scanning, and rollback-manifest validation.
4. Run `node scripts/release-preflight.mjs <release-manifest.json>` from the toolkit root.
5. Stop on any `BLOCKED` result. Repair the evidence or manifest; do not waive a required gate silently.
6. If the result is `READY_FOR_CONNECTED_VALIDATION`, produce a handoff for BigQuery dry-run and GAS deployment smoke testing. Do not claim deployment success.
7. Promote by updating one version pointer only after every required connected check has real connected-environment evidence.
8. Keep the prior pointer as last-known-good until the observation window closes. Roll back the pointer atomically if freshness, reconciliation, latency, or correctness thresholds fail.

## Release rules

- New immutable cube version first; pointer promotion second.
- Release evidence is append-only and names the artifact, environment, status, and origin.
- Reconciliation compares published aggregates with approved fixture expectations and explicit tolerances.
- Rollback changes the version pointer; it does not patch rows in place.
- Dashboard and GAS callers must observe either the old complete cube or the new complete cube, never a partial refresh.

Read [release-evidence.md](references/release-evidence.md) when authoring or reviewing a release manifest. Start from `shared/templates/release-manifest.example.json`.

## Output

Report one of `READY_FOR_RELEASE`, `READY_FOR_CONNECTED_VALIDATION`, or `BLOCKED`. Include release identifiers, failed gates, pending connected checks, rollback target, and exact next actions.
