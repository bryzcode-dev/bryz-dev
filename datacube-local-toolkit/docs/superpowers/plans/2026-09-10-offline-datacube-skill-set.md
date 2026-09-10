# Offline DataCube Skill Set Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify four repository-contained, offline DataCube skills that work with Claude Code and Codex.

**Architecture:** Canonical skills live under `skills/` and are exposed through relative links in `.agents/skills` and `.claude/skills`. Shared local references, templates, fixtures, and Node.js built-in utilities provide deterministic validation without remote services.

**Tech Stack:** Markdown, YAML and JSON data files, JavaScript ES modules, Node.js built-in test runner, Bash, Git.

**Spec:** `docs/superpowers/specs/2026-09-10-offline-datacube-skill-set-design.md`

## Global Constraints

- The coding-agent workflow must work without network, MCP, GitHub, Google API, or package-download access.
- The deployed application may use approved Google Drive, Sheets, Apps Script, and BigQuery connections.
- Connected checks must never be represented as locally passed.
- Node.js utilities must use built-in modules only.
- Canonical skill content must not be duplicated between Claude Code and Codex locations.
- Each new skill is tested before work begins on the next skill.

---

### Task 1: Establish specification and package tests

**Files:**
- Create: `docs/superpowers/specs/2026-09-10-offline-datacube-skill-set-design.md`
- Create: `tests/toolkit.test.mjs`

**Interfaces:**
- Consumes: approved in-chat architecture and source review.
- Produces: repository invariants used by every later task.

- [ ] Write tests asserting the four canonical skill folders, required sections, offline-boundary wording, local reference integrity, and host links.
- [ ] Run `node --test tests/toolkit.test.mjs` and confirm failure because the skills and links do not exist.
- [ ] Keep the failing test as the package-level regression suite.

### Task 2: Build `datacube-design-contract`

**Files:**
- Create: `tests/design-contract.test.mjs`
- Create: `skills/datacube-design-contract/SKILL.md`
- Create: `skills/datacube-design-contract/references/contract-fields.md`
- Create: `scripts/validate-contract.mjs`
- Create: `shared/templates/source-contract.example.json`
- Create: `shared/fixtures/valid/source-contract.json`
- Create: `shared/fixtures/invalid/source-contract.json`

**Interfaces:**
- Consumes: local source samples and business definitions.
- Produces: validated source and metric contracts for ingestion.

- [ ] Write tests for valid contract acceptance and missing grain, invalid key references, duplicate field names, and unsupported aggregations.
- [ ] Run `node --test tests/design-contract.test.mjs` and confirm failure because the validator and skill are absent.
- [ ] Implement the validator using only `node:fs`, `node:path`, and ordinary language features.
- [ ] Write the skill and focused reference to enforce contract approval before implementation.
- [ ] Run the test again and require all cases to pass.
- [ ] Run the skill structural validator and commit the verified skill.

### Task 3: Build `datacube-ingestion-build`

**Files:**
- Create: `tests/ingestion-build.test.mjs`
- Create: `skills/datacube-ingestion-build/SKILL.md`
- Create: `skills/datacube-ingestion-build/references/pipeline-invariants.md`
- Create: `scripts/profile-csv.mjs`
- Create: `shared/fixtures/valid/sales.csv`
- Create: `shared/fixtures/invalid/sales-ragged.csv`

**Interfaces:**
- Consumes: approved contracts and representative local CSV exports.
- Produces: source profiles and a pipeline design with idempotency, quality, and atomic-publish requirements.

- [ ] Write tests for header and row counts, inferred values, duplicate keys, and ragged-row failure.
- [ ] Run `node --test tests/ingestion-build.test.mjs` and confirm failure because the profiler and skill are absent.
- [ ] Implement the local profiler with an RFC-4180-compatible parser for quoted fields and escaped quotes.
- [ ] Write the skill and pipeline-invariants reference.
- [ ] Run the test again and require all cases to pass.
- [ ] Run the skill structural validator and commit the verified skill.

### Task 4: Build `datacube-gas-query-api`

**Files:**
- Create: `tests/gas-query-api.test.mjs`
- Create: `skills/datacube-gas-query-api/SKILL.md`
- Create: `skills/datacube-gas-query-api/references/api-contract.md`
- Create: `shared/templates/api-contract.example.json`

**Interfaces:**
- Consumes: approved mart fields and dashboard query requirements.
- Produces: a bounded request/response contract and testable GAS/BigQuery adapter design.

- [ ] Write structural scenario tests for parameterization, allowlists, partition bounds, response versioning, caching, authorization, and full-cube prohibition.
- [ ] Run `node --test tests/gas-query-api.test.mjs` and confirm failure because the skill is absent.
- [ ] Write the skill, API reference, and concrete contract example.
- [ ] Run the test again and require all cases to pass.
- [ ] Run the skill structural validator and commit the verified skill.

### Task 5: Build `datacube-release-operations`

**Files:**
- Create: `tests/release-operations.test.mjs`
- Create: `skills/datacube-release-operations/SKILL.md`
- Create: `skills/datacube-release-operations/references/release-evidence.md`
- Create: `scripts/release-preflight.mjs`
- Create: `shared/templates/release-manifest.example.json`
- Create: `shared/fixtures/valid/release-manifest.json`
- Create: `shared/fixtures/invalid/release-manifest.json`

**Interfaces:**
- Consumes: local quality evidence and connected-validation plan.
- Produces: deterministic release decision with pass, fail, not-run, and blocked states.

- [ ] Write tests that accept complete local evidence and block missing, failed, or falsely local connected checks.
- [ ] Run `node --test tests/release-operations.test.mjs` and confirm failure because the preflight utility and skill are absent.
- [ ] Implement preflight evaluation using Node.js built-ins only.
- [ ] Write the skill and release-evidence reference.
- [ ] Run the test again and require all cases to pass.
- [ ] Run the skill structural validator and commit the verified skill.

### Task 6: Add reconciliation utility and host routing

**Files:**
- Create: `tests/reconcile.test.mjs`
- Create: `scripts/reconcile-fixtures.mjs`
- Create: `shared/fixtures/valid/reconciliation-expected.json`
- Create: `shared/fixtures/valid/reconciliation-actual.json`
- Create: `AGENTS.md`
- Create: `CLAUDE.md`
- Create: `.agents/skills/*` relative symbolic links
- Create: `.claude/skills/*` relative symbolic links

**Interfaces:**
- Consumes: expected and actual local metric fixtures.
- Produces: reconciliation results and cross-host skill discovery.

- [ ] Write exact, absolute-tolerance, relative-tolerance, and failure tests.
- [ ] Run `node --test tests/reconcile.test.mjs` and confirm failure because the utility is absent.
- [ ] Implement reconciliation using Node.js built-ins only.
- [ ] Add thin host routing files and relative skill links.
- [ ] Run reconciliation and toolkit tests.
- [ ] Commit the verified shared infrastructure.

### Task 7: Verify and package

**Files:**
- Create: `USAGE.md`
- Create: `SECURITY.md`
- Create: `tests/offline-safety.test.mjs`
- Create: `datacube-local-toolkit.zip` outside the repository.

**Interfaces:**
- Consumes: complete toolkit and all earlier test output.
- Produces: verified portable archive and recorded local git revision.

- [ ] Add tests that scan runtime scripts for networking modules, child processes, and non-built-in imports.
- [ ] Run the full suite with `node --test tests/*.test.mjs`.
- [ ] Run the official skill quick validator against all four skills.
- [ ] Verify all symbolic links resolve within the repository.
- [ ] Scan for placeholders, absolute workspace paths, secrets, and accidental `.git` packaging.
- [ ] Commit the final verified package.
- [ ] Create the ZIP archive excluding `.git`, logs, and the archive itself.
- [ ] List and test the archive before delivery.
