---
name: ea
description: Invoke the Context OS V3 Executive Assistant on demand for status, history, resources, cross-project recall, impact, comparison, investigation, or delegated task preparation.
argument-hint: [question or request]
disable-model-invocation: true
context: fork
agent: context-executive-assistant
background: true
---

## Local Context OS snapshot

!`python3 ~/.claude/context-os/runtime/app/contextctl.py assistant-context --root ~/.claude --cwd . --query current-project`

## User request

$ARGUMENTS

Use the Context OS snapshot as authoritative starting context. Query additional local Context OS information only when needed. Do not modify the current coding task unless the user explicitly asks for a handoff or delegation.
