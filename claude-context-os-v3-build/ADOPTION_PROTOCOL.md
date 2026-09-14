# Context OS V3 Adoption Protocol

This protocol replaces an existing Claude root only after a verified staged migration. Choose the single-system flow for one local `.claude` directory or the `shared-nas-v1` flow for the existing `shared/` plus `machines/` topology.

## Safety rules

1. Never build the replacement directly inside the active Claude root.
2. Inventory and hash the source first.
3. Create and hash-verify a full backup.
4. Build a staged V3 root separately.
5. Preserve legacy collisions under `context-os/legacy-preserved/native-collisions/`; V3 managed runtime files always win their managed namespace.
6. Run recursive secret inspection and exclude sensitive material from memory/index promotion.
7. Semantically review the legacy `CLAUDE.md` before activation when it contains content.
8. Verify source coverage, settings, managed integrity, and runtime layout.
9. Activate using a destination-filesystem sibling stage so NAS/local cross-device renames are not assumed.
10. Retain the previous root for rollback.

## Shared NAS topology: Mac Mini primary

The authoritative container is `/Volumes/BryzConfig/Claude`, but the migration target is only `/Volumes/BryzConfig/Claude/shared`. The shared transaction must never rename, replace, or copy into any `machines/*` directory. Run these commands from the deployable package directory.

### 1. Validate storage and stage only

```bash
python3 contextctl.py storage-validate --root /Volumes/BryzConfig/Claude

python3 contextctl.py adopt-shared \
  --root /Volumes/BryzConfig/Claude \
  --workspace "$HOME/ContextOS-Shared-Migrations" \
  --primary-machine mac-mini-m4 \
  --secondary-machine bryans-macbook-pro \
  --secondary-machine bryan-mac-neo \
  --facade "$HOME/.claude"
```

`adopt-shared` is stage-only. Record the exact timestamped `workspace` returned in its JSON output. All follow-up shared commands reject the parent workspace and require that exact directory.

### 2. Review the staged shared root

Inspect these files under the exact workspace:

```text
topology-guard.json
source-manifest.json
backup-manifest.json
backup-verification.json
primary-enrollment-plan.json
stage/context-os/config/topology.json
stage/context-os/migration/migration-report.json
stage/context-os/migration/review/legacy-CLAUDE.md
stage/context-os/migration/review/claude-sections.json
stage/context-os/migration/review/secret-scan.json
```

Confirm the migration report contains no `machines` or `shared` top-level mapping, all three machine roots still exist, the enrollment plan is `ready`, and the staged runtime template is `~/Library/Application Support/ClaudeContextOS/home`.

After semantic adoption is genuinely complete, mark the staged shared root reviewed:

```bash
python3 contextctl.py mark-reviewed \
  --workspace "$HOME/ContextOS-Shared-Migrations/<migration-id>" \
  --root /Volumes/BryzConfig/Claude/shared \
  --reviewer claude-code
```

### 3. Verify and prove rollback on the NAS filesystem

```bash
python3 contextctl.py verify-shared \
  --root /Volumes/BryzConfig/Claude \
  --workspace "$HOME/ContextOS-Shared-Migrations/<migration-id>" \
  --primary-machine mac-mini-m4 \
  --secondary-machine bryans-macbook-pro \
  --secondary-machine bryan-mac-neo \
  --facade "$HOME/.claude" \
  --require-source-unchanged

python3 contextctl.py probe-shared-rollback \
  --root /Volumes/BryzConfig/Claude \
  --workspace "$HOME/ContextOS-Shared-Migrations/<migration-id>" \
  --primary-machine mac-mini-m4 \
  --secondary-machine bryans-macbook-pro \
  --secondary-machine bryan-mac-neo \
  --facade "$HOME/.claude"
```

The probe uses a unique temporary sibling inside the container, verifies the actual rename/restore behavior, and removes only its validated probe directory. It does not activate the shared root.

### 4. Activation gate

Do not run either command below until the staged content, semantic review, topology evidence, source-unchanged check, and rollback probe have been reviewed and activation is explicitly authorized.

```bash
python3 contextctl.py activate-shared \
  --root /Volumes/BryzConfig/Claude \
  --workspace "$HOME/ContextOS-Shared-Migrations/<migration-id>" \
  --primary-machine mac-mini-m4 \
  --secondary-machine bryans-macbook-pro \
  --secondary-machine bryan-mac-neo \
  --facade "$HOME/.claude"

python3 contextctl.py enroll-machine \
  --root /Volumes/BryzConfig/Claude \
  --workspace "$HOME/ContextOS-Shared-Migrations/<migration-id>" \
  --primary-machine mac-mini-m4 \
  --secondary-machine bryans-macbook-pro \
  --secondary-machine bryan-mac-neo \
  --facade "$HOME/.claude" \
  --machine-id mac-mini-m4 \
  --apply
```

Without `--apply`, `enroll-machine` is a non-mutating dry run. The apply transaction may create only `context-os`, `commands`, `rules`, `context-os-machine.json`, and the local runtime directory; it preserves existing facade links and local settings.

### 5. Post-activation and rollback

Run `doctor`, `reindex`, and `/ea brief me` from the active shared root. If rollback is needed, first roll back the Mac Mini enrollment using the exact transaction manifest returned by `enroll-machine`, then restore the previous shared root:

```bash
python3 contextctl.py rollback-machine --manifest /exact/enrollment-transaction-<id>.json

python3 contextctl.py rollback-shared \
  --root /Volumes/BryzConfig/Claude \
  --workspace "$HOME/ContextOS-Shared-Migrations/<migration-id>" \
  --primary-machine mac-mini-m4 \
  --secondary-machine bryans-macbook-pro \
  --secondary-machine bryan-mac-neo \
  --facade "$HOME/.claude"
```

The two secondary Macs are enrolled only after the Mac Mini passes its real activation and rollback validation. Their existing machine directories are not wiped by the shared adoption flow.

## Single-system local `.claude` flow

### Storage validation

For a single local system:

```bash
cd /path/to/claude-context-os-v3
python3 contextctl.py storage-validate --root "$HOME/.claude"
```

This command performs only a sibling create/rename/readback probe and removes the probe afterward. It does not modify the Claude root.

The result must report `ok: true` before proceeding.

### 1. Inventory

```bash
python3 contextctl.py inventory \
  --root "$HOME/.claude" \
  > ~/Desktop/claude-root-inventory.json
```

Review the inventory for anything unexpected, especially custom hooks, agents, skills, commands, settings, and secret-bearing files.

### 2. Stage adoption

Use a local migration workspace and runtime:

```bash
python3 contextctl.py adopt \
  --root "$HOME/.claude" \
  --workspace "$HOME/ContextOS-Migrations" \
  --runtime "$HOME/Library/Application Support/ClaudeContextOS/home" \
  --profile home
```

Do not add `--activate` on the first real migration.

The command creates a timestamped migration workspace containing:

```text
backup/
stage/
source-manifest.json
backup-manifest.json
migration-paths.json
```

The staged root contains the V3 runtime app so the installed system is self-contained.

### 3. Review migration output

Inside the returned migration workspace inspect:

```text
stage/context-os/migration/migration-report.json
stage/context-os/migration/review/legacy-CLAUDE.md
stage/context-os/migration/review/claude-sections.json
stage/context-os/migration/review/secret-scan.json
stage/context-os/legacy-preserved/
```

Legacy native-name collisions are intentionally preserved outside the managed runtime namespace rather than silently replacing V3 files.

### 4. Semantic adoption

If the migration reports legacy `CLAUDE.md` sections, use the staged `context-adopt` skill to move durable information into the proper V3 destinations. Uncertain content stays in review/preserved storage rather than being discarded.

After review:

```bash
python3 contextctl.py mark-reviewed \
  --workspace "$HOME/ContextOS-Migrations/<migration-id>" \
  --root "$HOME/.claude" \
  --reviewer claude-code
```

### 5. Verify the stage

```bash
python3 contextctl.py verify \
  --workspace "$HOME/ContextOS-Migrations/<migration-id>" \
  --root "$HOME/.claude"
```

Activation remains blocked when semantic review is pending unless an explicit bypass is supplied. Do not use the bypass for a real populated root merely to save five minutes and purchase an afternoon of regret.

### 6. Activate

```bash
python3 contextctl.py activate \
  --workspace "$HOME/ContextOS-Migrations/<migration-id>" \
  --root "$HOME/.claude"
```

V3 first copies the verified stage to a temporary sibling of the target root on the target filesystem, then performs the swap. The original root is retained at the rollback path recorded by the migration.

### 7. Post-activation checks

Run the installed self-contained CLI:

```bash
python3 "$HOME/.claude/context-os/runtime/app/contextctl.py" doctor \
  --root "$HOME/.claude"
```

Then rebuild/confirm the local runtime index:

```bash
python3 "$HOME/.claude/context-os/runtime/app/contextctl.py" reindex \
  --root "$HOME/.claude"
```

Start Claude Code and confirm:

- V3 user instructions/rules load.
- `/ea brief me` is discoverable and returns `◆ EA`.
- existing skills/agents still exist or are preserved under collision review.
- current projects still resolve.
- hooks execute without path errors.

### 8. Optional local self-management service

Generate, but do not automatically load, the macOS LaunchAgent:

```bash
python3 "$HOME/.claude/context-os/runtime/app/contextctl.py" service-plist \
  --root "$HOME/.claude"
```

The generated service runs deterministic maintenance against the local runtime. Loading it is a separate deliberate step after manual validation.

### Rollback

Read:

```text
$HOME/.claude/context-os/migration/ACTIVE_MIGRATION.json
```

Then run:

```bash
python3 "$HOME/.claude/context-os/runtime/app/contextctl.py" rollback \
  --root "$HOME/.claude" \
  --rollback-root /path/from/ACTIVE_MIGRATION.json
```

Rollback moves the V3 root aside and restores the retained previous root. It does not destroy the failed/new root.

## Live-root backup behavior (V3.0.1)

The Claude root may change while Claude Code is active. V3.0.1 treats the backup as a defined snapshot: the copied tree must match a complete source state measured immediately before or immediately after the copy. If neither boundary matches, migration retries up to three times. Successful live changes are recorded in `live-drift.json`. If all retries fail, `backup-verification.json` lists the changing paths; close Claude Code and retry rather than bypassing verification.
