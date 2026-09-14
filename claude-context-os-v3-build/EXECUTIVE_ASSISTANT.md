# Executive Assistant

## Purpose

The Executive Assistant (EA) is the human-facing intelligence layer over Context OS V3. It is **not** the controller of Context OS and it is **not** the normal coding worker.

Context OS continues to manage indexing, integrity, tasks, state, policy, snapshots, migration, and maintenance deterministically. Claude Code continues project work. The EA is invoked only when the user wants a cross-project brief, investigation, historical recall, impact analysis, resource lookup, comparison, or task/delegation preparation.

## Invoke inside Claude Code

```text
/ea brief me
/ea what is happening with this project?
/ea did we solve something like this elsewhere?
/ea find the production GAS URL for Inventory
/ea what projects use this dataset?
/ea check whether Claude is rebuilding something we already solved
```

The V3 `ea` skill is configured as:

- manual invocation only
- `context: fork`
- custom `context-executive-assistant` agent
- background execution

That isolates the EA's working context from the coding worker's main thread and allows the worker conversation to remain focused. The result returns to the main conversation prefixed:

```text
◆ EA
```

## Authority model

The EA may:

- read Context OS status, project brains, task state, resources, dependencies, events, and approved knowledge
- search project files and code with read-oriented tools
- compare projects and prior fixes
- perform impact analysis
- explain warnings and contradictions
- prepare a context handoff
- create a tracked task only when explicitly delegated through the Context OS CLI
- store a lasting EA preference only when the user explicitly confirms it

The EA may not:

- directly edit application code
- directly rewrite authoritative Context OS state
- read secrets/credentials
- bypass policy
- disable auditing
- delete backups or authoritative knowledge
- silently convert an inference into durable engineering truth

## Personality

The default EA is named **Avery**. Personality lives separately from engineering knowledge under the Context OS assistant configuration. Default traits are organized, direct, concise by default, personable, lightly witty, technically adaptive, and willing to call out risk or contradictory state.

The personality can be changed without changing the OS schemas or project knowledge.

## Learning model

EA learning has two separate pathways.

### Interaction preferences

Examples:

- "When I ask for project status, put blockers first."
- "Keep my brief concise unless something is high risk."

A confirmed preference can be stored with:

```bash
python3 contextctl.py assistant-remember \
  "Lead project status summaries with blockers." \
  --confirmed \
  --root /path/to/claude-root
```

Unconfirmed casual observations are not promoted as permanent preferences.

### Engineering knowledge

Project facts, fixes, decisions, resource locations, and reusable patterns do **not** go into EA preference memory. They enter Context OS through governed project/knowledge/task pathways with provenance, status, and verification fields.

The EA therefore learns from the entire OS without becoming a competing source of truth.

## Worker handoff

When a useful historical fix or decision is found, the EA should produce a compact handoff such as:

```text
EA CONTEXT NOTE
Project: regional-dashboard
Task: TASK-481
Relevant fix: FIX-218
Decision: ADR-44
Risk: preserve production Sheet output contract
Evidence: Inventory Dashboard regression test
```

The coding worker gets the compact facts, not the EA's entire research transcript.

## Outside Claude Code

A deterministic terminal shell is also available:

```bash
python3 contextctl.py assistant --root /path/to/claude-root
```

That shell exposes local OS queries but does not pretend to provide LLM personality/reasoning by itself. Personality-driven reasoning is supplied by the Claude Code EA subagent (or a future approved local-model adapter).
