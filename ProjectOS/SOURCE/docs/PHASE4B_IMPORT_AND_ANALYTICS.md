# ProjectOS Phase 4-B Import and Analytics

Status: `SIMULATED`. This release does not authorize source-machine intake, Google access, a real Sheet refresh, scheduler changes, legacy disablement, push, or merge.

Phase 4-B makes SQLite schema 3 the source of truth for verified Looker evidence. It imports only the canonical Phase 4-A archive, retains immutable per-intake asset occurrences, builds versioned analytics, and exposes role-filtered projection rows for the existing Google Sheet and GAS application.

## Safe command sequence

Use the same Python 3.11+ environment on macOS or Windows. Replace placeholders with local paths and identifiers; never place secrets in an argument or archive.

```text
<python> -m projectos.cli looker intake verify <archive.zip>
<python> -m projectos.cli looker intake preview <archive.zip>
<python> -m projectos.cli --db <projectos.sqlite> looker intake import <archive.zip> <project-id> --owner-email <protected-owner-email> --actor <protected-owner-email>
<python> -m projectos.cli --db <projectos.sqlite> looker analytics build <project-id> <intake-run-id> --owner-email <protected-owner-email> --actor <protected-owner-email>
<python> -m projectos.cli --db <projectos.sqlite> looker analytics show <project-id> --owner-email <protected-owner-email> --actor <caller-email>
```

`verify` and `preview` are database-free. Import verifies the complete archive before opening SQLite, requires an explicit database, and permits only the protected active Owner. Analytics build is also Owner-only. Analytics show resolves the caller from the SQLite User Manifest; it never accepts a role claim.

For a dependency or reverse-impact query, add `--node <type:name> --direction dependencies` or `--direction impact`. A caller who cannot view the project receives only `Looker analytics are unavailable`, so project names, counts, graph nodes, search terms, and connection names cannot disclose a PRIVATE project.

The ordinary command surface intentionally has no force, purge, arbitrary-SQL, credential-resolution, Google-refresh, scheduler-disablement, or legacy-teardown option.

## Schema and analytics contract

Migration 3 adds intake runs, source-member inventory, immutable asset occurrences, relationships, findings, validation results, legacy mappings, reconciliation records, and cutover-package records. `looker_assets` remains the canonical inventory; `looker_asset_occurrences` binds each imported occurrence to its intake run so a later import cannot rewrite earlier analytic facts.

Each analytics build appends a summary and graph version. Summary facts include asset/file/connection-reference counts, relationship and finding counts, unresolved and duplicate counts, typed orphans, Git branch/divergence/dirty state, validation and code status, parser versions, legacy coverage, safe credential-reference aggregates, schema version, import provenance, and refresh availability. Credential values are never resolved or serialized.

The workbook projection adds `Looker_Assets`, `Looker_Relationships`, `Looker_Findings`, and `Looker_Analytics`. Each row carries the canonical project identifier, projection revision, and row hash. The public projection includes rows only for PUBLIC projects; Owner-only projection state may contain authorized PRIVATE rows. Browser input cannot select or override a role.

## Troubleshooting

- `Looker command requires an explicit database`: place `--db <path>` before `looker` for import, build, and show.
- `Owner authorization is required`: confirm the actor is the active protected Owner in the SQLite User Manifest. Admin cannot import or build analytics.
- `Looker analytics are unavailable`: the project is missing, not visible to the caller, or has no completed analytic version. The message is deliberately non-disclosing.
- `Looker graph direction is required`: supply both `--node` and `--direction`.
- Evidence validation failure: rerun database-free `verify`; do not edit the ZIP. Recollect from the source machine only after separate authorization.
- Schema health failure: stop. Preserve the database, run `doctor`, and restore from a verified backup rather than editing migration tables manually.

No real Google or legacy comparison is proven by a fixture import. Phase 4-C reconciliation and a separately authorized refresh receipt are required before any cutover claim.
