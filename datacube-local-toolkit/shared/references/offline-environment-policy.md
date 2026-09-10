# Offline environment policy

This toolkit may inspect and modify only files inside the current project and may execute deterministic local commands. It must not browse the web, call APIs, use MCP servers, contact package registries, clone repositories, or rely on authenticated services.

## Evidence states

| State | Meaning |
| --- | --- |
| `PASS` | The stated check ran in the named environment and its evidence is available. |
| `FAIL` | The check ran and a stated acceptance criterion failed. |
| `NOT RUN` | The check was not executed, commonly because it requires Google connectivity. |
| `BLOCKED` | Work cannot proceed safely because a prerequisite, decision, or required artifact is missing. |

Local tests can prove contract shape, parsing, pure transformations, query construction, security allowlists, fixture reconciliation, and release-manifest completeness. They cannot prove Google Drive permissions, Sheet revision behavior, BigQuery syntax acceptance or bytes billed, IAM, Apps Script deployment, quotas, latency, or production freshness.

## Connected handoff

For every connected check, record the target environment, exact command or operator action, prerequisites, expected evidence, pass criterion, owner, and current state. Do not include credentials. A future connected runner may execute the handoff, but the offline assistant must leave it `NOT RUN`.
