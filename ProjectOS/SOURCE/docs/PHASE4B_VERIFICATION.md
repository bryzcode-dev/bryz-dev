# ProjectOS Phase 4-B Verification

Status: `SIMULATED`.

The candidate was exercised only with invented local fixtures. It did not inspect another machine, connect to Google, refresh a Sheet, call GAS, alter a native scheduler, disable a legacy workflow, push, or merge.

## Automated gates

- Focused CLI/projection TDD gate: `6` passed.
- Phase 4-B affected regression: `50` passed.
- Complete Python regression, final candidate: `463` passed.
- GAS regression: `20` passed.
- Python compilation of `src`, `build_backend.py`, and `tests`: exit `0`.
- Full Python-suite executions: `2` (initial release-candidate gate plus one correction rerun).
- Correction rounds: `1`; two stale schema-2 test expectations were advanced to schema 3. No production behavior changed in the correction.
- Agent runs: `0`.

The focused gates cover database-free verify/preview, verify-before-open import, explicit SQLite selection, Owner-only mutation, role-resolved reads, absence of force/purge/SQL/role options, schema-3 migration and rollback, immutable per-run occurrences, deterministic analytic versioning, cycle-safe dependency traversal, removed-node impact, PUBLIC projection filtering, and PRIVATE aggregate/search/graph non-disclosure.

## Installed-wheel and simulated-import evidence

| Artifact | Size | Members | SHA-256 |
|---|---:|---:|---|
| `projectos-0.1.0-py3-none-any.whl` | 195221 bytes | 100 | `93e6f1f66f03b99c1d510228f5ade181f7435290be3fd10915f2eabd191d0412` |
| `simulated-intake.zip` | 2722 bytes | 10 | `5f2705ec97010d0d11f49bdfba43c877ed6f261b6e2f77ce4e8a5c6cdc15ea8c` |
| `simulated.sqlite` | 471040 bytes | n/a | `8b1dad597e96883eebe76244d79055ea25457665ff97bccc7389852cc13c6bf6` |
| `simulated-import-receipt.json` | 245 bytes | n/a | `d6d946b0aa4b49f62174bbbceb61749cd8b6b6a854837006512f964710153ea1` |

The extracted wheel contained `projectos/migrations/0003.sql` and every Looker collector, importer, repository, analytics, CLI, and projection module. A scan found no current-machine home path, private-key marker, test secret, or GitHub-token marker in the installed package.

Using only the extracted wheel, the simulated flow initialized schema 3, imported `fixture-run`, built analytic version 1, projected one PUBLIC Looker asset, and passed `doctor` with integrity, foreign-key, and schema checks all `ok`. The receipt declares support `SIMULATED`; it is not a real refresh or source-machine acceptance record.
