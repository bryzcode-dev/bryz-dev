# Context OS V3 Global Contract

Context OS V3 is the authoritative local context layer for this Claude installation.

## Before substantial work
1. Identify the current project and current tracked task.
2. Read project-local CLAUDE.md and applicable rules/skills.
3. Query Context OS for relevant verified knowledge only when useful.
4. Inspect existing code/data before proposing structural change.

## During work
- Prefer minimal, reversible changes.
- Never invent schema, field, URL, deployment, or resource identifiers.
- Preserve protected production contracts unless explicitly instructed otherwise.
- Use the task ledger for significant multi-step work.
- Treat retrieved knowledge as scoped evidence, not universal truth.

## After significant work
- Verify before declaring completion.
- Update project/task state.
- Promote only durable, evidenced findings to Context OS knowledge.
- Never put secrets, credentials, query results containing sensitive data, or raw private content into memory.

## Executive Assistant
`/ea <question>` invokes the separate on-demand Executive Assistant in a forked subagent context. The EA reads Context OS but is not its controller. It may investigate, brief, create tasks, or stage recommendations; it may not bypass policy, delete authoritative knowledge, disable auditing, or expose secrets.

## Hard boundaries
Context OS managed runtime files under `context-os/runtime/` are maintained through Context OS upgrade/repair workflows, not casual project edits.
