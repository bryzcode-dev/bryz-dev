---
name: datacube-ingestion-build
description: Use when designing or changing Drive CSV or Google Sheets ingestion, BigQuery staging and marts, watchdog state, rebuild logic, source profiling, data quality, or cube publication.
---

# DataCube Ingestion and Build

## Overview

Design a repeatable path from approved source contracts to a versioned
BigQuery-backed cube. Protect correctness before optimizing throughput.

## Offline boundary

Use repository files, local samples, and local commands only. Do not call Drive,
Sheets, GAS, BigQuery, an MCP, or the web. Generate connected-environment
handoff steps without executing them, and mark them `NOT RUN`.

## Entry gate

Require a `PASS` result from `datacube-design-contract`. If grain, keys,
mappings, or measures changed without a new contract version, return `BLOCKED`.

## Required workflow

1. Inspect existing contracts, ingestion adapters, SQL, run-state storage,
   tests, fixtures, and deployment files before proposing new conventions.
2. Profile each representative CSV export with
   `node scripts/profile-csv.mjs <file> --key <field[,field]>`. Compare headers,
   types, blanks, row width, and duplicates with the contract.
3. Define adapters for stable Drive file IDs and Sheet ID/tab/range identities.
   A filename or timestamp alone is not an identity or sufficient fingerprint.
4. Define a source fingerprint from stable identity plus available revision,
   modified time, size, and checksum. State what the connected adapter can
   actually obtain.
5. Define a run state machine: `DETECTED`, `LOCKED`, `STAGED`, `VALIDATED`,
   `BUILT`, `PUBLISHED`, `FAILED`. Persist run ID, contract version, source
   fingerprints, counts, checks, and timestamps.
6. Make the run idempotent. The same contract and source fingerprints must not
   duplicate facts or publish a second logical version. Acquire a lock before
   mutation and define stale-lock recovery.
7. Separate raw staging, typed staging, canonical facts/dimensions, quality
   results, quarantine, and aggregate marts. Never silently discard malformed
   rows.
8. Reconcile row counts, key uniqueness, required fields, accepted/rejected
   totals, and business measures before publication.
9. Build a new version beside the live version. Promote a stable view or
   manifest pointer atomically only after all blocking quality checks pass.
   Preserve the last-known-good version and rollback identity.

## Result

Return the proposed artifacts, local test evidence, quality thresholds,
idempotency key, lock strategy, publish/rollback strategy, and connected checks
as `PASS`, `FAIL`, `NOT RUN`, or `BLOCKED`.

Read [pipeline-invariants.md](references/pipeline-invariants.md) before writing
pipeline or watchdog code.

## Common mistakes

- Parsing the full 50-75 MB source set inside a dashboard request.
- Assuming sequential GAS parsing guarantees memory reclamation.
- Deleting the current cube before the replacement is valid.
- Treating retries as safe without an idempotency key.
- Publishing when rejected rows or metric differences lack approved limits.
