# Claude Context OS Design

## Purpose
Build a local-first, vendor-readable context and memory framework for Claude Code that reduces repeated explanation, prevents instruction drift, preserves per-project state, enables cross-project reuse of verified fixes, and safely migrates an existing `~/.claude` root into the new architecture.

## Design principles

1. Keep always-loaded context concise. User-level `CLAUDE.md` is a routing and behavior document, not a knowledge dump.
2. Separate behavioral rules, reusable procedures, project facts, operational state, and historical memory.
3. Prefer plain Markdown and JSON so the system is auditable without proprietary software.
4. Use Claude Code native mechanisms first: `CLAUDE.md`, `~/.claude/rules/`, skills, hooks, project auto-memory, and settings.
5. Make cross-project recall opt-in and targeted. Never load an entire knowledge base into each session.
6. Use hooks for hard guardrails where instructions alone are insufficient.
7. Treat migration as a transaction: snapshot, stage, verify, replace, verify again, retain rollback.
8. Never silently discard existing content. Unclassified or conflicting material goes to a migration review queue.
9. Never copy secrets into the knowledge layer. Detect likely credentials and quarantine references for manual review.
10. Keep the core framework dependency-free using Python 3 standard library.

## Target architecture

### User-level `~/.claude`

- `CLAUDE.md`: concise global operating contract, under 200 lines.
- `rules/`: unconditional or path-aware personal rules.
- `skills/`: reusable procedures for memory, GAS, SQL/data work, debugging, project bootstrap, adoption, and health checks.
- `hooks/`: local scripts for session hydration, destructive-action guardrails, and durable activity logging.
- `context-os/`: framework-owned registries, schemas, migration state, and shared knowledge.
- `projects/`: Claude Code native per-repository auto-memory remains intact and is migrated/preserved.
- `settings.json`: merged rather than blindly replaced. Context OS hook entries are added while unrelated existing settings are preserved.

### Project-level contract

A participating project receives:

- `CLAUDE.md`: project architecture and rules that should always be present.
- `CLAUDE.local.md`: machine/private URLs and local-only project facts when appropriate.
- `.claude/project.json`: stable project manifest and resource registry.
- `.claude/state.md`: current objective, completed work, blockers, next steps, and protected surfaces.
- `.claude/rules/`: project-specific scoped rules.
- `.claude/skills/`: project-only procedures when needed.
- `docs/decisions/`: durable architecture decisions.

## Memory model

Memory is divided into scopes:

- Global: stable preferences, universal engineering rules, reusable validated patterns.
- Domain: GAS, BigQuery, Teradata, Google Sheets, DataCube, web apps, debugging.
- Project: facts specific to one project, URLs, system IDs, dependencies, decisions, state.
- Session: temporary working state and activity history.

Durable entries use these types:

- `ADR`: architecture decision
- `BUG`: diagnosed defect/root cause
- `FIX`: verified fix
- `PATTERN`: reusable engineering pattern
- `DATA`: schema/data-source fact
- `URL`: resource location
- `PROC`: runbook/procedure
- `STATE`: current project state
- `DEP`: dependency/relationship
- `WARN`: known hazard
- `PREF`: durable user workflow preference

Promotion levels are `temporary → session → project → reusable → global`. Only verified, future-useful information should be promoted.

## Cross-project registry

`context-os/registry/projects.json` stores project identities and relationships. `context-os/knowledge/` stores plain Markdown knowledge cards with JSON frontmatter-compatible metadata. A local index file maps tags, project IDs, domains, and resource keys to file paths. Core operation does not require embeddings or network access.

Optional MCP memory can be added later, but the baseline package does not require it. This avoids making the migration dependent on a third-party service and keeps the first adoption fully local.

## Hooks

### SessionStart

The hook determines the working project, reads `.claude/project.json` and `.claude/state.md` when present, and emits a compact context envelope to stdout. Claude Code adds this stdout to session context. The envelope identifies project ID, project type, current objective, protected surfaces, and where to search for historical knowledge.

### PreToolUse

The hook evaluates Bash commands and blocks a narrow set of clearly destructive operations: recursive deletion of broad paths, `git reset --hard`, force push, destructive database statements without an explicit framework escape hatch, and deletion of the framework backup/archive directory. It returns Claude Code's structured deny response with a reason. It does not attempt to replace Claude Code's normal permissions system.

### PostToolUse activity log

A lightweight hook records timestamp, project ID, tool name, and affected path/command summary as JSONL. It deliberately avoids storing tool outputs, source code contents, prompts, credentials, or SQL results.

## Skills

User-level skills:

- `context-memory`: retrieve and promote durable knowledge without bloating context.
- `project-bootstrap`: create/repair a participating project's manifest/state/rules structure.
- `gas-engineering`: Apps Script architecture, quotas, triggers, deployments, properties, and validation workflow.
- `sql-engineering`: grain-first query work, schema verification, join-cardinality checks, warehouse safety.
- `root-cause-debugging`: evidence-first debugging and reusable fix capture.
- `context-adopt`: semantic migration workflow for an existing Claude root snapshot.
- `context-health`: audit loaded files, manifests, hook configuration, stale state, conflicts, and migration residue.

## Adoption and migration protocol

### Phase 0: Preconditions

- Resolve target Claude root, defaulting to `~/.claude`.
- Confirm it exists or create an empty-source migration.
- Refuse to run if a prior migration lock exists unless `--resume` is used.
- Check free space is at least 2.5 times the source size plus 50 MB.

### Phase 1: Inventory

Produce a manifest containing path, type, size, SHA-256, permissions, and classification hints for every source item. Flag symlinks, external symlink targets, likely secret-bearing files, unknown binary content, and unsupported file types.

### Phase 2: Immutable snapshot

Copy the entire source to a timestamped backup using metadata-preserving copy. Write a backup manifest and verify every regular file by hash. The backup is never edited by the migration.

### Phase 3: Classification

Classify known Claude structures directly: settings, commands, skills, agents, hooks, projects/auto-memory, rules, plugins, stats/logs/cache, and user instruction files. Split legacy root `CLAUDE.md` into heading-based sections and assign suggestions using deterministic topic heuristics. Conflicts, likely secrets, and low-confidence sections are queued in `migration/review/` rather than silently moved.

### Phase 4: Stage

Create a complete replacement root in a sibling staging directory. Install Context OS baseline files, merge existing supported content, preserve native auto-memory, copy unknown user-authored content into `context-os/legacy-preserved/`, and merge settings while preserving unrelated keys.

### Phase 5: Semantic adoption

Run the `context-adopt` skill against the staged root and migration report. Claude reviews section candidates, removes duplication, resolves contradictions in favor of the most specific/current rule when evidence supports it, and moves content to global rule, skill reference, project context, or preserved-review location. No source snapshot is modified.

### Phase 6: Verification

Verification must pass before swap:

- JSON files parse.
- Every migrated source file is represented by a destination, explicit preserve mapping, or review item.
- Source and backup manifests hash-match.
- Required baseline files exist.
- `CLAUDE.md` stays below the configured line threshold.
- Hook scripts execute against fixture inputs.
- Settings contain valid hook structures and preserve original non-Context-OS keys.
- No file classified as likely-secret was copied into knowledge cards.
- Project auto-memory counts and hashes match unless explicitly transformed.

### Phase 7: Atomic replacement

Rename current root to a timestamped `claude-pre-context-os-*` rollback directory, then rename staging root into the configured Claude root path. The two renames happen on the same filesystem. If the second rename fails, immediately restore the first rename.

### Phase 8: Post-swap health check

Run the same structural verifier against the active root, execute hook fixture checks, and write `context-os/migration/ACTIVE_MIGRATION.json`. The prior root remains available for rollback until the user explicitly removes it.

## Rollback

`contextctl rollback --migration <id>` verifies the rollback archive and active root, moves the active Context OS root aside, restores the archived root, then verifies it against its pre-migration manifest. Rollback never deletes the failed Context OS root.

## Security

The migration scanner flags names and content patterns associated with API keys, tokens, credentials, private keys, `.env` files, and auth caches. Such files remain in their native required location when necessary, but their contents are never copied to knowledge cards, migration summaries, activity logs, or context envelopes. Activity logs store metadata only.

## Testing strategy

Use standard-library `unittest` with temporary directories. Tests cover inventory hashing, CLAUDE section parsing/classification, secret detection, settings merge idempotency, source-coverage verification, safe staging behavior, guard-hook allow/deny behavior, session context generation, atomic swap rollback on simulated failure, and end-to-end migration of a synthetic legacy root.

## Success criteria

A migration is successful when the old root can be fully reconstructed from the immutable snapshot; every existing user-authored item is migrated, deliberately preserved, or explicitly queued for review; the staged root passes all automated checks; replacement is atomic and reversible; Claude Code receives concise project context at session start; destructive guardrails are enforced by hooks; and project/domain knowledge has a defined local path instead of being buried in an ever-growing root CLAUDE.md.
