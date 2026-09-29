# ProjectOS Phase 3D-B Verification

Status: `SIMULATED`. The host-execution implementation is complete in the detached local candidate; no native macOS or Windows acceptance run was performed.

## Verified implementation gates

- schema-2 seven-member package binds the wheel and embedded ContextOS extension bundle;
- one-shot preparation is local, receipt-bound, standard-user-only, and rollback-safe;
- definition and activation controllers reuse durable Phase 3B/3C transactions;
- native triggers require enabled hash ownership and fixed argument arrays;
- receipt, release, definition, run, case, and sequence-bound trigger windows reject direct, stale, foreign, duplicate, reordered, and timed-out events;
- every native effect records intent before invocation and recovery inspects before cleanup;
- evidence binds the manifest, package, wheel, extension bundle, preparation record, and scheduler definition;
- installed-wheel tests run without the source checkout and prohibit network and real native execution;
- macOS and Windows operations and Claude troubleshooting instructions are packaged.

## Release-candidate results

- Source revision bound into the candidate package: `0e2172038699d9212e58cd46dba1486569b74531`
- Focused Task 1-7 gates: `47`, `34`, `36`, `44`, `47`, `28`, and `19` passed.
- Affected Phase 3D-B regression: `192` passed.
- Complete Python regression: `427` passed; GAS regression: `20` passed; Python compilation: exit `0`.
- Failure-injection boundaries: `16`.
- Recording-executor lifecycle actions: `15` (`8` macOS and `7` Windows).
- Agent runs: `0`; automatic correction rounds: `1`; full-suite executions: `3`. The first output was truncated by the tool transport, the second exposed a self-review evidence-provenance finding, and the third verified the corrected final candidate.

## Deterministic artifacts

| Artifact | Size | Members | SHA-256 |
|---|---:|---:|---|
| `projectos-0.1.0-py3-none-any.whl` | 175265 bytes | 88 | `5c3618088148518bba149aa20b99055c68b579d41c2c59af3e393e19601a3e02` |
| `projectos-extension.zip` | 169790 bytes | 3 | `a674d53a0fd859c7b7c42cdd46763ce24b15b91bb14e2d30396ba4f36787d79a` |
| `projectos-phase3d-b-acceptance.zip` | 342994 bytes | 7 | `fd13703082474891e4495f1f49da00c5103be1e334bc4db3dbac1eebb06bce85` |
| `projectos-simulated-native-shaped-evidence.zip` | 1534 bytes | 2 | `70eb637459095e00d49bcb7cabcf84ced361410b5fc52bbe65ca210937833c58` |
| `projectos-reconciliation.json` | 386 bytes | 1 | `d8350a45bbbf064c26ac53ca646c2b5c90d1600facaf9507e839d94d5e1e94ed` |

All archives passed corruption, case-folded duplicate, traversal, regular-file, and symlink checks. Scans found zero current-host identifiers and zero credential markers. The native-shaped evidence passed structural verification but was deliberately excluded from reconciliation; it is simulated test evidence, not native host evidence. Reconciliation therefore has no verified hosts and remains `SIMULATED`.

## Authorization boundary

The next state-changing step is a separately authorized clean standard-user macOS run or Windows run. Authorization for one platform does not authorize the other. Do not push, merge, publish, or execute either native run from this candidate without the Owner's explicit instruction.
