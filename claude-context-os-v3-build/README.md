# Claude Context OS V3

Claude Context OS V3 is a local-only context, memory, project-state, and governance layer for Claude Code and other coding agents. It keeps authoritative knowledge in human-readable files, builds disposable local indexes for fast retrieval, manages project/task continuity independently of chat context, and exposes an on-demand Executive Assistant without making that assistant the controller of the system.

## V3.0.1 live-root snapshot fix

V3.0.1 corrects backup verification for active Claude roots, especially NAS-mounted roots. Migration now verifies the backup against a complete pre-copy or post-copy snapshot boundary, retries an unstable copy up to three times, records live drift separately, and later verifies against the frozen snapshot manifest rather than re-hashing the live root. If the source cannot stabilize, the error names the changing paths and points to `backup-verification.json`.

V3.0.1 also supports the existing three-machine `shared-nas-v1` layout. In that mode, `/Volumes/BryzConfig/Claude/shared` is the only migration and activation target. `/Volumes/BryzConfig/Claude/machines/*` remains outside the shared transaction, and each Mac keeps SQLite, hook queues, offsets, locks, and transient state in its own local `~/Library/Application Support/ClaudeContextOS/home` runtime.

The `/ea` snapshot command resolves through the enrolled `~/.claude/context-os` facade and uses a statically analyzable Claude Code permission rule. It does not depend on a session-level `CONTEXT_OS_HOME` variable.

## Design goals

- **Local runtime only.** Core V3 makes no web requests and requires no cloud memory/index service.
- **Portable.** Claude roots may be local or mounted/network storage; paths are configuration, not architecture.
- **Deterministic control plane.** Integrity, migration, policy, indexing, task state, backup, health, and recovery do not depend on an LLM making the right choice.
- **AI is replaceable.** Markdown/JSON plus SQLite are the durable representation. Indexes can be rebuilt.
- **Context is bounded.** Agents retrieve the smallest relevant context instead of preloading the archive.
- **Executive Assistant is separate.** `/ea` runs an on-demand, read-oriented assistant in an isolated Claude subagent. It knows V3 state but does not control V3.
- **Safe adoption.** Existing Claude roots are inventoried, hashed, backed up, staged, semantically reviewed, verified, and only then activated.

## V3 architecture

```text
User
 ├─ Claude Code worker ───────────────┐
 └─ /ea Executive Assistant ─────────┤
                                     v
                              Context OS V3 API/CLI
                                     |
        +----------------------------+----------------------------+
        |                 |                |                      |
     Projects          Knowledge          Tasks               Policy
        |                 |                |                      |
  project brains    JSON + FTS5      persistent ledger      deterministic
        |                 |                |                      |
        +-----------------+----------------+----------------------+
                                     |
                            local SQLite runtime
                                     |
                     integrity / events / maintenance
```

## Included

- V3 control CLI: `contextctl.py`
- SQLite + FTS5 local index
- temporal/supersedable knowledge cards with confidence/provenance fields
- project/resource/dependency registry and impact analysis
- persistent task ledger
- bounded context compiler
- project-brain compilation
- deterministic policy engine with optional local OPA adapter detection
- recursive secret-aware inspection with optional local Gitleaks integration
- integrity manifest and drift detection
- SessionStart, PreToolUse, PostToolUse, PreCompact, PostCompact, and SessionEnd hooks
- local-runtime hook event queue to avoid high-frequency NAS writes
- rebuildable indexes and maintenance workflow
- local snapshots and rollback
- storage validation for mounted roots
- portable export for work/local installations
- Executive Assistant (`/ea`) skill + custom read-oriented subagent
- optional local-only tool profiles for Gitleaks, OPA, ast-grep, Serena, Restic, and Basic Memory

## Storage model

V3 separates authoritative data from high-frequency runtime state.

```text
Claude root / authoritative storage
  CLAUDE.md
  settings.json
  rules/
  skills/
  agents/
  context-os/
    config/
    knowledge/
    projects/
    tasks/
    integrity/
    migration/

Local runtime storage
  context.db
  hook-events.jsonl
  locks/checkpoints
  transient logs/index state
```

For a NAS-mounted Claude root, keeping SQLite and frequent hook activity on the local Mac avoids depending on network-file locking for the hot runtime path.

### Supported deployment topologies

Single-system mode treats one local `.claude` directory as the authoritative root and uses the existing `adopt`, `verify`, `activate`, and `rollback` commands.

Shared NAS mode preserves the full topology:

```text
/Volumes/BryzConfig/Claude/
  shared/                 authoritative shared Context OS root
  machines/
    mac-mini-m4/          existing machine-specific state, never shared-swapped
    bryans-macbook-pro/
    bryan-mac-neo/

~/.claude/                per-Mac facade of governed symlinks plus local files
~/Library/Application Support/ClaudeContextOS/home/
                          per-Mac runtime, never stored on the NAS
```

Use `adopt-shared` for this topology. It stages by default and cannot activate implicitly. Use `enroll-machine` to preview a path-scoped facade transaction; mutation requires the explicit `--apply` flag. See `ADOPTION_PROTOCOL.md` for the gated sequence.

## Executive Assistant

Invoke inside Claude Code:

```text
/ea what is happening with this project?
/ea have we solved this problem elsewhere?
/ea brief me
/ea what depends on this dataset?
```

The skill is manual-only, runs in a forked/background custom subagent, and returns a response prefixed `◆ EA`. The EA reads Context OS as its source of truth, can investigate and prepare handoffs, but is not allowed to directly edit application code or managed OS files.

See `EXECUTIVE_ASSISTANT.md`.

## Main CLI commands

```bash
python3 contextctl.py doctor --root /path/to/claude-root
python3 contextctl.py reindex --root /path/to/claude-root
python3 contextctl.py search-knowledge "store hierarchy" --root /path/to/claude-root
python3 contextctl.py find-project "inventory" --root /path/to/claude-root
python3 contextctl.py task-list --root /path/to/claude-root
python3 contextctl.py impact "dataset-name" --root /path/to/claude-root
python3 contextctl.py assistant-brief --root /path/to/claude-root
```

Run `python3 contextctl.py --help` for the full command set.

## Home NAS validation target

The user's home Claude root is mounted at:

```text
/Volumes/BryzConfig/Claude
```

This path is **not hard-coded** into V3. It is a deployment/test profile. For the existing shared topology, validate the container but migrate only its `shared/` child:

```bash
python3 contextctl.py storage-validate --root /Volumes/BryzConfig/Claude
```

Then follow `ADOPTION_PROTOCOL.md`.

## Work portability

V3 can be exported without home knowledge, personal EA memory, caches, logs, or machine-specific paths:

```bash
python3 contextctl.py export-portable --output ~/Desktop/context-os-v3-portable.zip
```

The same platform can then be adopted against a local work Claude root (typically `~/.claude`) with a fresh work knowledge domain. See `PORTABLE_DEPLOYMENT.md`.

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall context_os template_root contextctl.py
python3 contextctl.py local-only-audit
```

The real shared NAS root was activated for the Mac Mini only after `storage-validate`, staged adoption, semantic review, verification, rollback probing, guarded activation, machine enrollment, and post-activation `doctor` passed. The two secondary Macs are not yet enrolled.
