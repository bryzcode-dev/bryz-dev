---
description: Use during Context OS migration when reviewing an existing Claude root snapshot and organizing legacy CLAUDE.md/rules/commands/skills into the staged architecture before activation.
---
# Context Adoption

Work only against the staged migration root and immutable backup. Never edit the source snapshot.

Read `context-os/migration/migration-report.json`, `context-os/migration/review/legacy-CLAUDE.md`, and `claude-sections.json`. For each legacy section: retain only information that remains useful; place universal concise behavior in global rules; move multi-step procedures to skills or skill references; identify project-specific facts for project migration rather than global loading; identify URLs/IDs as resource-registry candidates; remove exact duplication; and flag contradictions instead of guessing.

No source content may disappear silently. Anything not confidently adopted remains in `context-os/migration/review/` or `context-os/legacy-preserved/` with a mapping entry. Never copy likely secret contents into rules, skills, knowledge, or reports.

After semantic organization, run `python3 contextctl.py verify --workspace <migration-workspace>` from the package and do not activate unless verification passes.

When the staged reorganization is complete and all legacy sections are either adopted, preserved, or explicitly queued for review, run the package command:

`python3 contextctl.py mark-reviewed --workspace <migration-directory> --root <current-claude-root> --reviewer claude-code --notes "semantic adoption complete"`

Then run verification again. Activation remains blocked while `semantic-review.json` is pending unless a human deliberately uses the bypass flag.
