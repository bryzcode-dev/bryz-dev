# ProjectOS Phase 4-A Verification

Status: `SIMULATED`.

The candidate provides strict macOS/Windows intake, non-executing LookML parsing, injected read-only inspection, ordered collection journals, deterministic evidence archives, recovery limited to temporary archives, a separate host CLI, and installed-wheel imports without a source checkout.

Automated tests use invented fixtures and recording executors. No source machine, Google account, Sheet, GAS deployment, scheduler, live ContextOS root, shared root, or production SQLite database is accessed or changed.

- Focused Phase 4-A gate: `35` passed.
- Complete Python regression: `448` passed.
- GAS regression: `20` passed.
- Python compilation: exit `0`.
- Full-suite executions: `1`; correction rounds: `0`; agent runs: `0`.

| Artifact | Size | Members | SHA-256 |
|---|---:|---:|---|
| `projectos-0.1.0-py3-none-any.whl` | 188010 bytes | 96 | `4b95b67b9717f8fc473346bcb1c92b19e58a83633c6a1ec9fc8bdce08488abee` |
| `projectos-looker-intake-v1.zip` | 2584 bytes | 10 | `b502542500980cf76240f65bd5d08416deef264045de9787acd5a72625d73f39` |

Both artifacts passed corruption, case-fold duplicate, traversal, regular-file, and link checks. Support remains `SIMULATED`.
