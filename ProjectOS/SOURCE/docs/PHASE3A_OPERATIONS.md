# ProjectOS Phase 3A Operations

Phase 3A provides read-only ContextOS discovery, cross-platform path planning, machine-profile planning, extension-manifest validation, and deterministic staging-bundle construction. It does not install an extension, expose a skill, initialize or migrate SQLite, contact Google, or create a scheduler task.

## Safety boundary

The `adoption` command group is database-free. It does not resolve the default SQLite location or instantiate `ProjectOSDatabase`. Only `adoption bundle build` writes, and it writes the one requested staging archive atomically. All other Phase 3A commands are read-only.

Every command emits one JSON envelope. Exit `0` means success, `2` means invalid input or incompatible ContextOS, `3` means a controlled preflight failure, and `1` means a redacted internal error.

## Requirements and configuration precedence

- Python 3.11 or newer.
- ProjectOS installed from the verified `py3-none-any` wheel.
- A ContextOS installation containing `context-os/config/extension-contract.json` contract version `1`, ContextOS version `>=3.0.1,<4.0.0`, and the selected host in `supported_hosts`.

ContextOS root precedence is `--contextos-root`, `CONTEXTOS_ROOT`, then `<home>/.claude`. ProjectOS runtime-root precedence is `--projectos-home`, `PROJECTOS_HOME`, then the platform default. The SQLite path follows `PROJECTOS_DB`, otherwise `<runtime-root>/projectos.db`; Phase 3A only reports that planned value.

Platform defaults:

| Host | Runtime | Log root | Planned scheduler |
|---|---|---|---|
| macOS | `$HOME/Library/Application Support/ProjectOS` | `$HOME/Library/Logs/ProjectOS` | `launchd` |
| Windows | `%LOCALAPPDATA%\ProjectOS` | `%LOCALAPPDATA%\ProjectOS\logs` | Task Scheduler |

Windows onboarding fails if `%LOCALAPPDATA%` is missing unless `PROJECTOS_HOME` or `--projectos-home` supplies an absolute local path. Runtime, database, configuration, lock, log, and staging paths must not be contained by the ContextOS/shared root.

## Read-only inspection and planning

macOS:

```bash
projectos adoption inspect --contextos-root "/absolute/contextos/root"
projectos adoption profile plan \
  --contextos-root "/absolute/contextos/root" \
  --python-executable "/absolute/python"
```

PowerShell:

```powershell
projectos adoption inspect --contextos-root 'C:\ContextOS'
projectos adoption profile plan `
  --contextos-root 'C:\ContextOS' `
  --python-executable 'C:\Python311\python.exe'
```

Use `--host-family macos` or `--host-family windows` only for contract tests and planning simulations. It does not turn the current operating system into that host and is not real-host evidence.

A ready profile remains an in-memory plan with `adoption_state` set to `PLANNED`. Phase 3B will own local persistence and staged definition adoption.

## Manifest and bundle staging

Validate a manifest without changing it:

```bash
projectos adoption manifest validate /staging/manifest.json
```

Build and then independently verify a deterministic archive:

```bash
projectos adoption bundle build \
  /staging/manifest.json /staging/payload /staging/projectos-extension.zip \
  --contextos-root "/absolute/contextos/root"
projectos adoption bundle verify \
  /staging/projectos-extension.zip \
  --contextos-root "/absolute/contextos/root"
```

PowerShell uses the same arguments with native absolute paths. Repeat `--forbid VALUE` for any additional target-host identifier that must not appear in the artifact. The current home, username, and hostname are rejected automatically. Payload symlinks, absolute/traversal paths, case-insensitive duplicate names, secret-like material, resolved home paths, hash mismatches, and non-canonical manifests fail closed.

The requested output archive is the only durable build output. Temporary archives are created beside it and removed after failure. If a build fails, preserve the JSON error, inspect the input tree and manifest, correct the input, and build to a new staging filename. Do not reuse or activate a partially trusted output.

## Compatibility failures

- `ContextOS extension contract is missing`: supply the correct read-only root or stage the required ContextOS contract separately.
- `ContextOS contract version is incompatible`: stop; do not rewrite the target contract.
- `ContextOS version is incompatible`: use a supported release or prepare a separately reviewed compatibility change.
- `machine identity does not match`: resolve the actual target profile; do not override identity.
- `path must be local`: move ProjectOS runtime state outside ContextOS, NAS, or other shared roots.
- `bundle payload contains a forbidden host identifier`: replace the resolved value with a portable token or target-local machine-profile reference.

Phase 3A never authorizes live ContextOS adoption, skill installation, scheduler installation, SQLite movement, Google/GAS activity, shared-root writes, or Looker migration.
