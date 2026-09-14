# V3 Security Model

## Trust boundaries

1. **Authoritative files**: project/knowledge/config/task source.
2. **Derived runtime**: SQLite/index/log queues; safe to rebuild.
3. **Claude worker**: can perform project work subject to Claude permissions/hooks.
4. **Executive Assistant**: read-oriented subagent; no Write/Edit tools.
5. **Optional tools**: local binaries only, never assumed available.

## Defense layers

### Instructions

Concise `CLAUDE.md`, rules, and skills describe expected behavior.

### Claude permissions

Migration merges deny rules for secret-like paths into `settings.json` and narrow allows for the V3 query commands needed by the EA.

### PreToolUse enforcement

Managed hook blocks selected destructive commands and direct modification of the managed runtime namespace.

### Policy engine

The built-in deterministic policy engine denies operations such as reading secrets, deleting authoritative knowledge/backups, or disabling policy/auditing. Optional local OPA can be added as another evaluator without becoming a runtime web dependency.

### Secret handling

The migration recursively identifies likely sensitive material. Sensitive data is not promoted into knowledge merely because it exists under the Claude root. Optional local Gitleaks can add deeper detection.

### Integrity

Managed files receive SHA-256 entries in the managed integrity manifest. `doctor` compares the active installation against those hashes and reports drift.

## Non-goals

V3 is not an operating-system sandbox. A user or process with unrestricted filesystem permissions can still alter files directly. V3 provides agent-layer policy, integrity detection, safe workflows, and recovery, not a substitute for macOS permissions/enterprise endpoint controls.
