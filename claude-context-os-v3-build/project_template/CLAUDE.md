# Project Context

This project participates in Context OS V3.

## Startup
- Read `.claude/project.json` and `.claude/state.md` before substantial work.
- Use Context OS retrieval for cross-project history instead of guessing from chat history.
- Preserve every item listed in `protected_surfaces` unless the user explicitly authorizes a change.

## During work
- Keep the current task narrow and verify assumptions before changing business logic.
- Record durable decisions, verified fixes, resource locations, and dependencies through Context OS rather than expanding this file indefinitely.
- Do not store credentials or secrets in project context.

## Completion
- Verify the change.
- Update project state when the current objective, blockers, or next steps materially change.
- Promote only verified, reusable knowledge.
