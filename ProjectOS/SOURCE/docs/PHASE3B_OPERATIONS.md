# ProjectOS Phase 3B Fixture Operations

Phase 3B proves the ProjectOS definition transaction against an isolated ContextOS fixture. It cannot target a live ContextOS installation. Every installed registry entry remains `enabled:false`; skill discovery, schedulers, synchronization activation, Google, GAS, Looker, and production SQLite are outside this phase.

## Safety contract

All three fixture authorities are mandatory:

1. the canonical marker created while the fixture root was new or empty;
2. the matching receipt under the separate local runtime root;
3. the exact CLI acknowledgement `--fixture-ack FIXTURE_ONLY`.

Copying a marker is insufficient because the receipt binds its hash, fixture ID, host family, and normalized root. The ContextOS root and ProjectOS runtime cannot contain one another. Managed paths cannot contain symlinks. There is no live-target constructor, `--force`, registry enablement, or scheduler command.

## Configuration and local state

Fixture transaction commands require explicit `--contextos-root` and `--machine-profile`; neither is inferred from a live installation. The profile supplies the host family and local runtime. The explicit root, inspected fixture contract, receipt, and profile must all agree.

Local state is kept below `<runtime-root>/adoption/`:

```text
machine-profile.json
fixture-receipts/<fixture-id>.json
transactions/<transaction-id>/journal.json
transactions/<transaction-id>/snapshot/
transactions/<transaction-id>/staged/
archives/<transaction-id>/
```

SQLite databases, configuration, locks, logs, and unrelated ContextOS files are never copied into transaction snapshots or archives. Artifact scanning automatically forbids the current home path, username, hostname, and explicit ContextOS root; repeatable `--forbid VALUE` options add target-specific identifiers.

## Create a fixture and profile

The root must be new or empty and must not be a symlink:

```bash
projectos adoption fixture init /absolute/test/contextos \
  --runtime-root /absolute/local/projectos-fixture \
  --host-family macos \
  --machine-id fixture-macos
```

Plan a profile from the new fixture, then save only `data.profile` from the JSON envelope as the machine-profile JSON used below:

```bash
projectos adoption profile plan \
  --host-family macos \
  --contextos-root /absolute/test/contextos \
  --projectos-home /absolute/local/projectos-fixture \
  --python-executable /absolute/path/to/python3
```

The fixture profile must remain local to the test machine. Do not copy a build-machine profile to another host.

## Preflight and transactions

Preflight validates the fixture, profile, registry, bundle hash, compatibility, and locality without changing the fixture target:

```bash
projectos adoption fixture preflight projectos-extension.zip \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root /absolute/test/contextos \
  --machine-profile /absolute/local/machine-profile.json
```

Adoption and upgrade run ordered preflight, snapshot, stage, verify, immutable version copy, and one atomic registry replacement:

```bash
projectos adoption fixture adopt projectos-extension.zip \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root /absolute/test/contextos \
  --machine-profile /absolute/local/machine-profile.json

projectos adoption fixture upgrade projectos-extension-v2.zip \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root /absolute/test/contextos \
  --machine-profile /absolute/local/machine-profile.json
```

Adopt refuses an existing ProjectOS registry entry; upgrade requires one. Both return a generated `transaction_id`. The registry entry is always disabled.

Rollback uses the upgrade/adoption transaction ID, restores the exact registry bytes captured before the transaction, and removes the new version only if its complete inventory still matches the transaction:

```bash
projectos adoption fixture rollback TRANSACTION_ID \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root /absolute/test/contextos \
  --machine-profile /absolute/local/machine-profile.json
```

Uninstall creates its own transaction, archives hash-matching managed versions, removes only the `projectos` registry namespace and managed version directories, and preserves the database, profile, journals, and unrelated ContextOS state:

```bash
projectos adoption fixture uninstall \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root /absolute/test/contextos \
  --machine-profile /absolute/local/machine-profile.json
```

## Failure recovery

A failed state-changing command returns one redacted JSON envelope with exit `3`. Validation or compatibility failures return exit `2`. Find the generated transaction directory under the local runtime and run:

```bash
projectos adoption fixture recover TRANSACTION_ID \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root /absolute/test/contextos \
  --machine-profile /absolute/local/machine-profile.json
```

Recovery is idempotent after it reaches `ROLLED_BACK`. It restores the exact registry snapshot and removes a copied version only when current hashes prove transaction ownership. If that inventory changed, recovery stops and preserves the directory for manual review; do not delete or bypass it.

## Expected result envelope

Successful transaction data contains only bounded fields:

```json
{"command":"adoption fixture adopt","data":{"bundle_sha256":"...","managed_paths":["context-os/extensions/projectos/versions/..."],"operation":"ADOPT","state":"ADOPTED","transaction_id":"..."},"errors":[],"meta":{"schema_version":2},"ok":true}
```

Phase 3B completion is fixture evidence only. It does not authorize running these commands against an existing installation, installing a skill or scheduler, starting the two-hour sync, or touching external services.
