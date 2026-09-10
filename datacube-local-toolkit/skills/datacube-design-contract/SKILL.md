---
name: datacube-design-contract
description: Use when defining or changing a DataCube grain, source mapping, dimensions, measures, keys, quality rules, freshness target, or privacy classification before pipeline implementation.
---

# DataCube Design Contract

## Overview

Turn business definitions and representative local data into an explicit,
testable DataCube contract. The contract is the authority for later ingestion,
query, and release work.

## Offline boundary

Use only repository files and local commands. Do not browse, call an MCP or
Google API, install a package, or claim that a connected system was inspected.
Record missing connected evidence as `NOT RUN`.

## Required workflow

1. Inspect existing contracts, schemas, SQL, GAS code, fixtures, and sample
   exports before proposing names.
2. Inventory every source with a stable logical ID, kind (`drive-csv` or
   `google-sheet`), owner, local sample, expected cadence, and sensitivity.
3. Define one sentence for the fact grain. Stop on mixed or ambiguous grain.
4. Define canonical fields, types, nullability, source aliases, primary and
   deduplication keys, dimensions, hierarchies, and measures.
5. For every measure, specify its source field, aggregation, unit, null rule,
   and reconciliation tolerance. Separate additive, semi-additive, and
   non-additive measures.
6. Define duplicate, malformed, late-arriving, timezone, deletion, and schema
   drift behavior. Classify sensitive fields and required access boundaries.
7. Save the contract as JSON using
   `shared/templates/source-contract.example.json` as the shape.
8. Run `node scripts/validate-contract.mjs <contract.json>` and resolve every
   `FAIL` before approving implementation.

## Gate

**No pipeline implementation** may begin until grain, keys, mappings,
dimensions, measures, quality rules, freshness, and privacy decisions are
explicit and the local validator returns `PASS`. Ambiguity or missing evidence
is `BLOCKED`; it is never silently defaulted.

## Result

Report:

- contract path and version;
- `PASS`, `FAIL`, `NOT RUN`, or `BLOCKED` status;
- decisions made and unresolved questions;
- local samples inspected;
- connected checks still required;
- approved downstream interfaces.

Read [contract-fields.md](references/contract-fields.md) when creating or
reviewing a contract.

## Common mistakes

- Calling a measure a dimension because both appear in a filter UI.
- Treating a timestamp-only file check as a source identity.
- Combining order, order-line, and daily-summary grain.
- Defining totals without currency, sign, null, or deduplication rules.
- Inferring production access or freshness from a local sample.
