# Claude Context OS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dependency-free local Context OS package that structures Claude Code context, migrates an existing `~/.claude` safely, verifies coverage, and atomically replaces the root with rollback support.

**Architecture:** Python 3 standard-library CLI and hook scripts manage migration, manifests, staging, verification, swap, and rollback. Markdown/JSON templates provide Claude Code rules, skills, project manifests, and state. The active Claude root remains readable and portable, while migration is transaction-like and never mutates the source until a verified staging root exists.

**Tech Stack:** Python 3.11+ standard library, POSIX filesystem semantics with safe fallbacks, Markdown, JSON, Claude Code native hooks/skills/rules.

**Spec:** `docs/superpowers/specs/2026-09-12-claude-context-os-design.md`

## Global Constraints

- Core migration and runtime hooks must not require network access or third-party Python packages.
- Existing source content must never be silently discarded.
- Existing `settings.json` keys unrelated to Context OS must be preserved.
- Replacement must be staged, verified, atomic where supported, and reversible.
- Likely secret contents must never be copied into generated knowledge files or logs.
- Global `CLAUDE.md` should remain concise and under 200 lines.

---

### Task 1: Inventory and classification core

**Files:**
- Create: `context_os/inventory.py`
- Create: `context_os/classify.py`
- Test: `tests/test_inventory.py`
- Test: `tests/test_classify.py`

**Interfaces:**
- Produces `inventory_tree(root: Path) -> list[dict]`
- Produces `split_markdown_sections(text: str) -> list[dict]`
- Produces `classify_section(title: str, body: str) -> dict`
- Produces `looks_secret(path: Path, text: str | None) -> bool`

- [ ] Write failing tests for hashing, symlink inventory, Markdown section splitting, deterministic classification, and secret flags.
- [ ] Run tests and confirm failures are caused by missing implementation.
- [ ] Implement minimal inventory/classification functions.
- [ ] Run tests and confirm green.

### Task 2: Settings merge and baseline templates

**Files:**
- Create: `context_os/settings.py`
- Create: `template_root/CLAUDE.md`
- Create: `template_root/rules/*.md`
- Create: `template_root/skills/*/SKILL.md`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces `merge_context_os_settings(existing: dict, hook_paths: dict) -> dict`
- Baseline files copied by staging layer.

- [ ] Write failing tests proving unrelated settings are preserved and merge is idempotent.
- [ ] Run red tests.
- [ ] Implement merge logic and baseline templates.
- [ ] Run green tests.

### Task 3: Hook runtime

**Files:**
- Create: `template_root/hooks/session_start.py`
- Create: `template_root/hooks/pre_tool_guard.py`
- Create: `template_root/hooks/post_tool_log.py`
- Test: `tests/test_hooks.py`

**Interfaces:**
- Hooks consume Claude Code JSON from stdin where applicable and emit supported stdout/JSON responses.

- [ ] Write failing fixture tests for project context output, safe Bash command allow, destructive command deny, and metadata-only logging.
- [ ] Run red tests.
- [ ] Implement hook scripts.
- [ ] Run green tests.

### Task 4: Migration staging and coverage verifier

**Files:**
- Create: `context_os/migrate.py`
- Create: `context_os/verify.py`
- Test: `tests/test_migrate.py`

**Interfaces:**
- Produces `prepare_migration(source_root, workspace) -> MigrationPaths`
- Produces `build_stage(paths, template_root) -> dict`
- Produces `verify_stage(paths) -> VerificationReport`

- [ ] Write failing tests for immutable backup hashes, source coverage, preservation of unknown files, auto-memory preservation, secret quarantine, and staging without source mutation.
- [ ] Run red tests.
- [ ] Implement minimal staging and verification.
- [ ] Run green tests.

### Task 5: Atomic activate and rollback

**Files:**
- Modify: `context_os/migrate.py`
- Create: `context_os/rollback.py`
- Test: `tests/test_activation.py`

**Interfaces:**
- Produces `activate_verified_stage(paths) -> dict`
- Produces `rollback(active_root, rollback_root, manifest) -> dict`

- [ ] Write failing tests for successful rename swap and restoration when the second rename is simulated to fail.
- [ ] Run red tests.
- [ ] Implement activation/rollback.
- [ ] Run green tests.

### Task 6: CLI and adoption protocol

**Files:**
- Create: `contextctl.py`
- Create: `ADOPTION_PROTOCOL.md`
- Create: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Commands: `inventory`, `stage`, `verify`, `activate`, `adopt`, `health`, `rollback`, `bootstrap-project`.

- [ ] Write failing CLI tests against a synthetic Claude root.
- [ ] Run red tests.
- [ ] Implement command wiring and operator documentation.
- [ ] Run green tests.

### Task 7: End-to-end adoption fixture

**Files:**
- Create: `tests/fixtures/legacy-root/*`
- Create: `tests/test_end_to_end.py`

**Interfaces:**
- End-to-end test asserts all source files are accounted for, settings survive, classified sections land in migration candidates, unknown content is preserved, active root passes health, and rollback reconstructs the source root.

- [ ] Write and run failing end-to-end test.
- [ ] Complete any minimal implementation needed for green.
- [ ] Run full test suite.
- [ ] Run compile checks and package self-audit.
