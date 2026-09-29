# ProjectOS Phase 4-C Reconciliation and ContextOS Queries

Status: `SIMULATED`. This phase does not authorize source-machine inspection, a Google refresh, scheduler changes, legacy disablement, push, or merge.

Phase 4-C compares an immutable ProjectOS analytic version with a preserved legacy snapshot. SQLite remains the source of truth. A reconciliation report is append-only: changed input, policy, or an Owner waiver produces a new report rather than rewriting earlier evidence.

## Reconciliation contract

The required dimensions are asset counts, relationships, findings, dashboards, tracker mappings, validation, refresh, and credential usage. Every normalized item receives exactly one outcome: `MATCH`, `MISMATCH`, `MISSING_SOURCE`, `MISSING_TARGET`, or `WAIVED`.

A report becomes `READY` only when every required item is either `MATCH` or `WAIVED`. Only the protected active Owner may waive a mismatch, and each waiver records the reason, actor, timestamp, parent report, and audit event. Admin and User roles cannot waive, import, rebuild analytics, refresh Google, or change cutover state.

The ordinary CLI provides three local operations:

```text
<python> -m projectos.cli --db <projectos.sqlite> looker reconcile stage <project-id> <intake-run-id> <analytic-version> <legacy-snapshot.json> <policy.json> --owner-email <protected-owner-email> --actor <protected-owner-email>
<python> -m projectos.cli --db <projectos.sqlite> looker reconcile report <reconciliation-id>
<python> -m projectos.cli --db <projectos.sqlite> looker reconcile waive <reconciliation-id> <dimension> <item-key> <reason> --owner-email <protected-owner-email> --actor <protected-owner-email>
```

Do not edit a report in SQLite or reinterpret a blocked report as ready. Correct the source evidence, create a new analytic version, or record an explicit Owner waiver.

## Guarded refresh receipt

`RefreshReceipt` validates a returned real-world refresh as one bound chain: project and intake, source Git revision, matching summary and graph analytic version, ready reconciliation, active verified projection revision, completed sync run, Google binding, and the exact passing validation-command set.

The verifier is read-only and rejects simulated, unbound, incomplete, failed, or mixed-version receipts. Automated fixtures therefore use `support_state: SIMULATED` and are expected to fail the real-receipt gate. Advancing that value to `REAL` is allowed only after a separately authorized Google refresh returns matching external evidence; changing the label alone cannot satisfy verification.

The Phase 4-C simulated evidence package consists of:

- one schema-3 SQLite fixture with an invented PUBLIC Looker project;
- one immutable intake and analytic version;
- one ready reconciliation report covering all eight dimensions;
- one invented active projection and completed sync record;
- one `SIMULATED` receipt used to prove fail-closed rejection;
- test output proving the same facts succeed only when the fixture is explicitly modeled as returned `REAL` evidence.

No credentials or resolved credential values are present. Identifiers, Git revision, Sheet binding, validation result, and timestamps are invented test data.

## ContextOS adoption

Schema-3 extension manifests may declare these read-only capabilities: `looker-status`, `looker-assets`, `looker-dependencies`, `looker-findings`, `looker-impact`, and `looker-reconciliation`.

Discovery exposes them only when both the installed extension manifest and the opened database meet schema 3. Older extension or database state strips all Looker capabilities. The generated skill explicitly prohibits import, waiver, refresh, cutover, arbitrary SQL, and credential resolution.

Every query opens the configured SQLite database in immutable read-only mode and closes it after the bounded result is created. No query accepts role overrides, SQL, paths, commands, or state-changing capability names. Project visibility remains enforced by the upstream adopted ProjectOS authorization and projection contracts; this adapter is an internal ContextOS capability surface, not a public browser endpoint.

## Troubleshooting

- `only REAL refresh receipts can be verified`: expected for fixture evidence; obtain separate authorization and a returned real refresh instead of editing the receipt.
- `analytics are unavailable or mixed`: rebuild from one verified intake and bind reconciliation to that exact version.
- `reconciliation is not ready or is unbound`: resolve required differences or record an Owner waiver that creates a ready child report.
- `projection is not active or is unbound`: stop and inspect the Google binding and active projection; do not activate a revision manually.
- `validation evidence is missing or failed`: rerun only the approved validation workflow and return a new receipt.
- Looker capabilities absent after adoption: verify both the extension declaration and actual SQLite schema are version 3, then rerun normal ContextOS discovery.

Phase 4-D may consume this evidence to prepare a reversible cutover package. It does not itself authorize legacy disablement.
