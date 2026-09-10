# Release evidence

## Required local gates

| Check ID | Evidence | Passing condition |
| --- | --- | --- |
| `contract-validation` | Validator report | Contract is structurally valid and versioned |
| `fixture-reconciliation` | Reconciliation report | Every metric is within its approved tolerance |
| `idempotency-simulation` | Repeat-run report | The same version and inputs produce the same published result |
| `api-contract` | Test report | GAS request and response envelopes match the versioned contract |
| `secret-scan` | Scan report | No credentials or private keys are present in release artifacts |
| `rollback-manifest` | Validation report | A tested, immutable last-known-good target exists |

Each local PASS needs `evidence.origin: "local-test"` and an artifact path. Use `FAIL` for an executed failing check, `NOT RUN` for an unexecuted check, and `BLOCKED` when a prerequisite prevents execution.

## Connected gates

`bigquery-dry-run` and `gas-deployment-smoke-test` require a connected Google environment. Offline work may prepare commands and expectations but must leave their status as `NOT RUN` or `BLOCKED`. A connected PASS is valid only with `evidence.origin: "connected-environment"` and durable evidence from that environment.

## Atomic promotion

Build a new immutable target, validate it, then switch one small version pointer or configuration value. Readers resolve that pointer before querying. Never replace a live table or sheet in multiple visible steps.

## Rollback packet

Record the previous cube version, physical target, local rollback rehearsal result, connected rollback command or runbook step, and the owner authorized to execute it. Keep the last-known-good target readable throughout the observation window.
