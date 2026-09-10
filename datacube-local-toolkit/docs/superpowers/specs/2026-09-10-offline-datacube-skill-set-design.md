# Offline DataCube Skill Set Design

## Purpose

Create a repository-contained skill toolkit that guides Claude Code and Codex
through the design, implementation, testing, and release of a BigQuery-backed
DataCube whose sources are Google Drive CSV files and Google Sheets and whose
front-facing process is Google Apps Script (GAS).

The coding agent must be able to use the toolkit without internet access,
external MCP servers, live Google Cloud access, GitHub access, or package
downloads. The deployed application can use approved Google services.

## Outcomes

The toolkit will provide four focused skills:

1. `datacube-design-contract` defines the cube's grain, dimensions, measures,
   mappings, data-quality rules, privacy classification, and freshness target.
2. `datacube-ingestion-build` designs Drive/Sheets ingestion, BigQuery staging,
   canonical models, idempotent watchdog processing, quality gates, and atomic
   publication.
3. `datacube-gas-query-api` designs a thin GAS facade with parameterized and
   bounded BigQuery queries, caching, authorization boundaries, and a versioned
   response contract.
4. `datacube-release-operations` evaluates local release evidence, preserves a
   last-known-good version, and separates offline verification from connected
   deployment checks.

## Architectural boundaries

### Offline agent boundary

Skill execution must not require:

- network access or web searches;
- GitHub or marketplace access;
- MCP servers;
- live Drive, Sheets, Apps Script, BigQuery, Logging, Monitoring, or Lineage
  calls;
- automatic package installation;
- unapproved mutation of cloud resources.

Skills may generate commands and connected-environment handoff instructions,
but must label them as unexecuted. A connected check can never be reported as
passed from local evidence.

### Runtime boundary

The target production architecture is:

1. Drive CSV and Google Sheets sources.
2. A lightweight GAS trigger or approved scheduler that detects source
   versions and starts an ingestion run.
3. BigQuery staging tables.
4. Canonical fact and dimension tables.
5. Quality and reconciliation results.
6. A versioned aggregate mart or stable view pointer.
7. A thin GAS query facade returning small, versioned responses.

GAS must not parse 50-75 MB of CSV data for every dashboard request and must
not publish a single mutable `datacube.json` by deleting the previous file.

## Repository layout

```text
skills/
  datacube-design-contract/
  datacube-ingestion-build/
  datacube-gas-query-api/
  datacube-release-operations/
shared/
  references/
  templates/
  fixtures/
scripts/
tests/
.agents/skills/       # relative links for Codex
.claude/skills/       # relative links for Claude Code
AGENTS.md
CLAUDE.md
```

The canonical skill implementation lives under `skills/`. Both host-specific
directories use relative symbolic links to the same folders so instructions
cannot drift.

## Common contract

Every skill must:

- have a distinct, trigger-only `description` beginning with `Use when`;
- declare the offline boundary near the beginning;
- inspect existing project files before proposing new conventions;
- preserve user decisions and require approval before destructive or live
  actions;
- identify its required inputs and concrete outputs;
- distinguish `PASS`, `FAIL`, `NOT RUN`, and `BLOCKED` evidence;
- route to local supporting references only when relevant;
- avoid host-specific dynamic prompt syntax;
- avoid remote dependencies and installation steps;
- work with ordinary local shell and filesystem capabilities.

## Skill responsibilities

### DataCube design contract

Required inputs include the source inventory, representative local samples,
business questions, target freshness, privacy constraints, and expected data
volume. It produces source and metric contracts and a contract-validation
report. It blocks implementation when grain, keys, types, dimensions, measures,
or aggregation rules are ambiguous.

### DataCube ingestion and build

Required inputs include approved contracts and local source samples. It
produces a pipeline design, state-machine definition, staging/canonical/mart
SQL artifacts, data-quality checks, and an offline test report. It requires
stable source identifiers, source-version fingerprints, a build lock,
idempotent run IDs, quarantine behavior, and atomic promotion.

### DataCube GAS query API

Required inputs include an approved mart interface and dashboard request
requirements. It produces a request/response contract, query templates, GAS
adapter design, caching policy, authorization rules, and local contract tests.
It prohibits unrestricted full-cube downloads and unbounded or interpolated SQL.

### DataCube release operations

Required inputs include contracts, test outputs, build and release manifests,
and a connected-validation plan. It produces a release decision report and
rollback instructions. Release is blocked by failed local checks, missing
evidence, incompatible contracts, absent rollback identity, or connected checks
incorrectly represented as local passes.

## Deterministic local utilities

The toolkit will use Node.js built-in modules only.

- `validate-contract.mjs` validates required contract structure, unique field
  names, key references, dimensions, measures, and aggregation functions.
- `profile-csv.mjs` profiles a local CSV sample for headers, row width,
  emptiness, inferred primitive types, and duplicate keys.
- `reconcile-fixtures.mjs` compares expected and actual metric results with
  absolute and relative tolerances.
- `release-preflight.mjs` evaluates a release manifest and returns a nonzero
  status when required evidence is missing or failed.

Utilities must accept local file paths, emit JSON, use meaningful exit codes,
and never make network calls.

## Evaluation strategy

Tests will be written before each utility or skill. Because the environment
forbids external agents, behavioral evaluation will be represented by local
scenario fixtures and assertions over observable skill invariants. This does
not replace future fresh-agent evaluations in an authorized environment; the
release documentation must state that limitation.

Tests cover:

- trigger discrimination and required skill sections;
- absence of required external dependencies;
- successful and failing contract validation;
- CSV profile behavior and duplicate detection;
- exact and tolerance-based reconciliation;
- release blocking and success states;
- valid relative links for Claude Code and Codex;
- complete local-only packaging.

## Success criteria

The implementation is acceptable when:

- all four skills pass structural and scenario tests;
- all deterministic utilities pass their red-green test cycles;
- no utility imports a non-built-in dependency or performs a network call;
- both host skill directories resolve to the canonical skill folders;
- invalid contracts and incomplete releases fail closed;
- locally unverifiable connected checks remain `NOT RUN` or `BLOCKED`;
- the package is committed to local git and exported as a portable archive;
- the archive contains no `.git` directory, secrets, generated logs, or
  absolute workspace paths.

## Deferred work

Live BigQuery dry runs, GAS deployment, Drive/Sheets permission checks,
Cloud Logging queries, Monitoring metric discovery, and Data Lineage analysis
are connected-environment activities. They are explicitly outside this offline
toolkit build.
