---
description: Use when onboarding a project to Context OS, repairing missing project context files, or creating a consistent Claude Code project identity and state structure.
---
# Project Bootstrap

Inspect the repository before creating files. Create `.claude/project.json` with stable project ID, name, project types, systems/resources, related projects, protected surfaces, and memory namespace. Create `.claude/state.md` with Current Objective, Completed, In Progress, Blockers, Known Problems, Next Steps, and Do Not Change. Keep secrets out of both files.

Create or refine project `CLAUDE.md` only for facts and rules that should be present every session. Put task-specific procedures in project skills and file-specific guidance in `.claude/rules/`.
