---
name: datacube-gas-query-api
description: Use when designing or changing a Google Apps Script dashboard endpoint, BigQuery-backed cube query, filter API, cache policy, response contract, or frontend data interface.
---

# DataCube GAS Query API

## Overview

Keep GAS as a thin, secure facade over a published BigQuery mart. Return only
the bounded data required for the current dashboard interaction.

## Offline boundary

Use local contracts, code, SQL, and fixtures only. Do not call GAS, BigQuery,
Drive, Sheets, an MCP, or the web. A locally constructed query is not a
successful BigQuery dry run; record connected validation as `NOT RUN`.

## Entry gate

Require an approved mart interface and DataCube contract. If a requested field
or metric is absent from those contracts, return `BLOCKED` rather than exposing
an arbitrary table column.

## Required workflow

1. Inspect the approved mart contract, existing GAS handlers, SQL builders,
   authorization logic, caches, fixtures, and tests before changing interfaces.
2. Define a versioned request and response using
   `shared/templates/api-contract.example.json` as the minimum shape.
3. Allowlist dimensions, measures, filters, sort fields, and groupings. Reject
   unknown values before creating SQL.
4. Use BigQuery named parameters for every value. Build identifiers only from
   allowlisted mappings; never interpolate user-provided identifiers or values.
5. Require a partition-bounded date range and enforce maximum days, maximum
   rows, maximum bytes billed, execution timeout, and result-size limits.
6. Query only the stable published mart interface. Never read staging tables or
   an unapproved build version.
7. Generate a normalized cache key from API version, cube version, caller scope,
   sorted dimensions/measures, filters, date range, sort, and page. Never share
   cached results across authorization scopes.
8. Return a versioned envelope containing `apiVersion`, `cubeVersion`, `data`,
   `meta`, and `errors`. Include cache status, row count, and connected query
   metadata when genuinely available.
9. Keep authorization on the server side. Store configuration in approved
   properties or deployment configuration, never source-controlled secrets.
10. Test pure validation, mapping, cache-key, and response functions locally.
   Keep GAS and BigQuery service calls behind thin adapters.

## Guardrails

- Do not expose a full-cube download or unrestricted SQL endpoint.
- Do not return more than the contract's maximum rows.
- Do not accept a missing partition filter by silently selecting all dates.
- Do not report bytes processed, latency, IAM, or deployment as `PASS` from
  local tests.

## Result

Report contract changes, local tests, allowlists, query limits, authorization
scope, cache behavior, response compatibility, and outstanding connected checks
as `PASS`, `FAIL`, `NOT RUN`, or `BLOCKED`.

Read [api-contract.md](references/api-contract.md) before writing endpoint or
query-construction code.

## Common mistakes

- Returning one large JSON cube because it is precomputed.
- Parameterizing values while interpolating untrusted identifiers.
- Caching without the user or authorization scope.
- Letting the dashboard choose raw table and column names.
