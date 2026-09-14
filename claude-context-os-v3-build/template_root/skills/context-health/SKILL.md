---
description: Use to audit Context OS health, investigate instruction drift, check project onboarding, verify hooks/settings, or diagnose excessive/stale Claude context.
---
# Context Health

Check that global CLAUDE.md is concise, rules are non-contradictory, project facts are not leaking into global context, procedures live in skills, project manifest/state files are current, hooks are configured once, migration review queues are not forgotten, and settings remain valid JSON.

Use `/context` in Claude Code to inspect actually loaded memory/rule files when diagnosing drift. Prefer removing duplication and narrowing scope over adding more global instructions.
