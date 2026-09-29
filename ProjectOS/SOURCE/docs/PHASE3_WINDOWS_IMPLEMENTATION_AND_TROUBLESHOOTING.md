# ProjectOS Phase 3C — Windows Implementation and Troubleshooting Handoff

> Phase 3D-B now supersedes the native-acceptance portions of this handoff. Use `PHASE3D_HOST_OPERATIONS.md` for schema-2 preparation, read-only preflight, separately authorized native execution, recovery, and evidence return; use `PHASE3D_B_IMPLEMENTATION_AND_TROUBLESHOOTING.md` for durable-state diagnosis. This document remains the Phase 3B/3C fixture preparation reference.

This is the clean-room handoff for Claude or another implementer on a real Windows host. It verifies the portable Phase 3A contracts, Phase 3B definition transaction, and Phase 3C fixture scheduler/skill activation against newly created isolated fixtures. It does not adopt ProjectOS into live ContextOS, initialize production SQLite, contact Google, or create a native scheduled task.

## Authority and fixed inputs

Record these values before starting. Do not invent or silently substitute them:

```text
SOURCE_REVISION=5502a1d
WHEEL_FILE=projectos-0.1.0-py3-none-any.whl
WHEEL_SHA256=f47eaca3b37bed57028c3397004d5c2f45c918623c845ff0e341c3fe958a619c
SUPPORTED_PYTHON=>=3.11
CONTEXTOS_VERSION=>=3.0.1,<4.0.0
EXTENSION_CONTRACT_VERSION=1
```

The current user must provide the actual wheel, its independently communicated hash, and the exact read-only ContextOS roots to test. Use a non-developer Windows account without Developer Mode or symlink privileges. Never copy paths from the build Mac.

## Clean-room setup

Open ordinary PowerShell, not an elevated console:

```powershell
$ErrorActionPreference = 'Stop'
$Work = Join-Path $env:TEMP ('projectos-phase3c-' + [guid]::NewGuid().ToString('N'))
$Venv = Join-Path $Work 'venv'
$Evidence = Join-Path $Work 'evidence'
New-Item -ItemType Directory -Path $Work, $Evidence | Out-Null
Copy-Item -LiteralPath 'C:\Provided\projectos-0.1.0-py3-none-any.whl' -Destination $Work
$Wheel = Join-Path $Work 'projectos-0.1.0-py3-none-any.whl'
(Get-FileHash -Algorithm SHA256 -LiteralPath $Wheel).Hash.ToLowerInvariant()
py -3.11 -m venv $Venv
& (Join-Path $Venv 'Scripts\python.exe') -m pip install --no-index $Wheel
& (Join-Path $Venv 'Scripts\projectos.exe') --help
```

Stop if the hash differs, Python is older than 3.11, installation contacts a package index, or the console command fails. Preserve the exact error in `00-prerequisites.txt`; do not bypass the gate.

## Required read-only cases

Confirm `%LOCALAPPDATA%` is non-empty and local:

```powershell
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is unavailable' }
'LOCALAPPDATA_AVAILABLE=true' | Set-Content -LiteralPath (Join-Path $Evidence '01-localappdata.txt')
```

Test both an exact drive-letter installation and an exact UNC installation supplied by the Owner. The UNC location is ContextOS definitions only; ProjectOS runtime must remain under `%LOCALAPPDATA%` or another explicit local path.

```powershell
$ProjectOS = Join-Path $Venv 'Scripts\projectos.exe'
$Python = Join-Path $Venv 'Scripts\python.exe'
$DriveInspect = (& $ProjectOS adoption inspect --host-family windows `
  --contextos-root 'C:\Exact\ContextOS' | ConvertFrom-Json)
$DriveProfile = (& $ProjectOS adoption profile plan --host-family windows `
  --contextos-root 'C:\Exact\ContextOS' --python-executable $Python | ConvertFrom-Json)
$UncInspect = (& $ProjectOS adoption inspect --host-family windows `
  --contextos-root '\\server\share\ExactContextOS' | ConvertFrom-Json)
$UncProfile = (& $ProjectOS adoption profile plan --host-family windows `
  --contextos-root '\\server\share\ExactContextOS' --python-executable $Python | ConvertFrom-Json)
if (-not $DriveInspect.ok -or -not $UncInspect.ok) { throw 'ContextOS inspection failed' }
if (-not $DriveProfile.ok -or -not $DriveProfile.data.ready) { throw 'drive profile failed' }
if (-not $UncProfile.ok -or -not $UncProfile.data.ready) { throw 'UNC profile failed' }
[ordered]@{
  ok = $DriveInspect.ok
  contract_version = $DriveInspect.data.contract.contract_version
  contextos_version = $DriveInspect.data.contract.contextos_version
  supported_hosts = $DriveInspect.data.contract.supported_hosts
} | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $Evidence '02-drive-inspect.json')
[ordered]@{
  ok = $DriveProfile.ok
  ready = $DriveProfile.data.ready
  host_family = $DriveProfile.data.profile.host_family
  scheduler_kind = $DriveProfile.data.profile.scheduler_kind
  checks = @($DriveProfile.data.checks | ForEach-Object { [ordered]@{ name = $_.name; ok = $_.ok } })
} | ConvertTo-Json -Depth 5 -Compress | Set-Content -LiteralPath (Join-Path $Evidence '03-drive-profile.json')
[ordered]@{
  ok = $UncInspect.ok
  contract_version = $UncInspect.data.contract.contract_version
  contextos_version = $UncInspect.data.contract.contextos_version
  supported_hosts = $UncInspect.data.contract.supported_hosts
} | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $Evidence '04-unc-inspect.json')
[ordered]@{
  ok = $UncProfile.ok
  ready = $UncProfile.data.ready
  host_family = $UncProfile.data.profile.host_family
  scheduler_kind = $UncProfile.data.profile.scheduler_kind
  checks = @($UncProfile.data.checks | ForEach-Object { [ordered]@{ name = $_.name; ok = $_.ok } })
} | ConvertTo-Json -Depth 5 -Compress | Set-Content -LiteralPath (Join-Path $Evidence '05-unc-profile.json')
```

Each successful envelope must contain `"ok":true`; each planned profile must use `host_family:"windows"`, `scheduler_kind:"windows-task-scheduler"`, a local runtime under `%LOCALAPPDATA%\ProjectOS` unless explicitly overridden, and no runtime/database path within the drive or UNC ContextOS root. The commands must not create a database, machine profile, extension entry, skill, or task.

## Artifact and no-symlink checks

Build only from the supplied portable payload and manifest into the clean-room staging directory. Pass both the exact ContextOS root and any machine-specific strings as forbidden values.

```powershell
$Bundle = Join-Path $Work 'projectos-extension.zip'
& $ProjectOS adoption manifest validate (Join-Path $Work 'manifest.json') |
  Set-Content -LiteralPath (Join-Path $Evidence '06-manifest.json')
& $ProjectOS adoption bundle build (Join-Path $Work 'manifest.json') `
  (Join-Path $Work 'payload') $Bundle --contextos-root 'C:\Exact\ContextOS' |
  Set-Content -LiteralPath (Join-Path $Evidence '07-bundle-build.json')
& $ProjectOS adoption bundle verify $Bundle --contextos-root 'C:\Exact\ContextOS' |
  Set-Content -LiteralPath (Join-Path $Evidence '08-bundle-verify.json')
(Get-FileHash -Algorithm SHA256 -LiteralPath $Bundle).Hash.ToLowerInvariant() |
  Set-Content -LiteralPath (Join-Path $Evidence '09-bundle-sha256.txt')
Get-ChildItem -LiteralPath (Join-Path $Work 'payload') -Recurse -Force |
  Where-Object { $_.LinkType } |
  Format-List FullName, LinkType, Target |
  Out-String | Set-Content -LiteralPath (Join-Path $Evidence '10-links.txt')
```

`10-links.txt` must be empty. Bundle build also rejects links, traversal, absolute archive names, case-insensitive duplicate names, secret-like content, and resolved home paths. Do not enable Developer Mode or recreate a link as a copied file merely to make the test pass; correct the portable source upstream.

## Expected failures and bounded remediation

- Exit `2`, incompatible/missing contract: verify the exact root and contract file; otherwise stop and return evidence.
- Exit `3`, profile blocked: inspect the named check. Correct only the supplied target-local path or Python input; do not weaken locality or identity rules.
- Exit `2`, fixture authority failure: recreate a new empty fixture through `fixture init`; do not copy a marker or hand-edit a receipt.
- Exit `2`, operation mismatch: use `adopt` only when no ProjectOS entry exists and `upgrade` only when one exists.
- Exit `3`, fixture transaction failure: run `recover` with its generated transaction ID. If recovery fails, preserve state and stop.
- Exit `1`: preserve the redacted envelope and Python/Event Viewer context, then stop. Do not repeatedly retry unknown internal errors.
- `%LOCALAPPDATA%` missing: use an Owner-approved explicit local `--projectos-home`; never fall back to the ContextOS or UNC root.
- Hash mismatch: discard the artifact and request a new verified copy.

## Required Phase 3B definition transaction

Use a new local fixture root. It must be empty and must not be a link. Do not substitute an existing ContextOS directory. The runtime must remain local and separate:

```powershell
$Fixture = Join-Path $Work 'contextos-fixture'
$Runtime = Join-Path $env:LOCALAPPDATA ('ProjectOS\phase3c-fixture-' + [guid]::NewGuid().ToString('N'))
& $ProjectOS adoption fixture init $Fixture --runtime-root $Runtime `
  --host-family windows --machine-id 'windows-cleanroom-fixture' |
  Set-Content -LiteralPath (Join-Path $Evidence '11-fixture-init.json')

$ProfileEnvelope = & $ProjectOS adoption profile plan --host-family windows `
  --contextos-root $Fixture --projectos-home $Runtime --python-executable $Python |
  ConvertFrom-Json
if (-not $ProfileEnvelope.ok -or -not $ProfileEnvelope.data.ready) { throw 'profile plan failed' }
$Profile = Join-Path $Work 'machine-profile.json'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
  $Profile,
  ($ProfileEnvelope.data.profile | ConvertTo-Json -Depth 12 -Compress),
  $Utf8NoBom
)

& $ProjectOS adoption fixture preflight $Bundle --fixture-ack FIXTURE_ONLY `
  --contextos-root $Fixture --machine-profile $Profile |
  Set-Content -LiteralPath (Join-Path $Evidence '12-fixture-preflight.json')
& $ProjectOS adoption fixture adopt $Bundle --fixture-ack FIXTURE_ONLY `
  --contextos-root $Fixture --machine-profile $Profile |
  Set-Content -LiteralPath (Join-Path $Evidence '13-fixture-adopt.json')
$Adopt = Get-Content -Raw -LiteralPath (Join-Path $Evidence '13-fixture-adopt.json') | ConvertFrom-Json
if (-not $Adopt.ok -or $Adopt.data.state -ne 'ADOPTED') { throw 'fixture adoption failed' }
if ((Get-Content -Raw -LiteralPath (Join-Path $Fixture 'context-os\extensions\registry.json') | ConvertFrom-Json).extensions.projectos.enabled) {
  throw 'Phase 3B registry entry must remain disabled'
}
```

The preflight must not change fixture files. Adoption must return `ADOPTED`, create only a versioned `context-os\extensions\projectos\versions\...` definition, and write a disabled registry entry. Do not roll it back yet: Phase 3C activation must bind this completed definition transaction. Preserve `<runtime>\adoption\transactions` as evidence. Do not edit a failed journal or delete a version whose recovery reports an inventory mismatch.

If adoption returns exit `3`, obtain the newest generated transaction directory and run bounded recovery. Repeat the same command once to prove recovery is idempotent:

```powershell
$TransactionId = (Get-ChildItem -LiteralPath (Join-Path $Runtime 'adoption\transactions') -Directory |
  Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).Name
& $ProjectOS adoption fixture recover $TransactionId --fixture-ack FIXTURE_ONLY `
  --contextos-root $Fixture --machine-profile $Profile |
  Set-Content -LiteralPath (Join-Path $Evidence '14-fixture-recovery.json')
```

Stop if recovery reports an inventory mismatch. Current bytes are then no longer proven transaction-owned. Return the journal, snapshot manifest, relative file inventory, and error envelope without deleting anything.

## Required Phase 3C fixture activation

Continue only after Phase 3B adoption returned `ADOPTED` and left the registry entry disabled. Use the canonical profile written by the adoption store:

```powershell
$Profile = Join-Path $Runtime 'adoption\machine-profile.json'
$Db = Join-Path $Runtime 'projectos.db'
$Config = Join-Path $Runtime 'projectos.toml'
if (-not (Test-Path -LiteralPath $Profile -PathType Leaf)) { throw 'canonical profile missing' }
```

Prepare only the disposable fixture database. These identifiers must be invented and must not refer to a real spreadsheet or credential:

```powershell
$Owner = 'fixture-owner@example.invalid'
& $ProjectOS --db $Db init | Out-Null
& $ProjectOS --db $Db user seed-owner --owner-email $Owner --display-name 'Fixture Owner' | Out-Null
$Credential = (& $ProjectOS --db $Db credential create --provider GOOGLE --label fixture `
  --credential-type ADC --purpose sync --storage-system KEYCHAIN `
  --storage-reference 'projectos/windows-fixture' --actor $Owner | ConvertFrom-Json).data
$Binding = (& $ProjectOS --db $Db google binding create --environment DEV `
  --spreadsheet-id 'fixture-sheet-id' --display-name 'Fixture ProjectOS' `
  --contract-version 1 --credential-id $Credential.credential_id --enabled --write-enabled `
  --actor $Owner | ConvertFrom-Json).data
$ProfileData = Get-Content -Raw -LiteralPath $Profile | ConvertFrom-Json
$ConfigLines = @(
  'contract_version = 1'
  ('machine_id = "{0}"' -f $ProfileData.machine_id)
  'environment = "DEV"'
  ('binding_id = "{0}"' -f $Binding.binding_id)
  'spreadsheet_id = "fixture-sheet-id"'
  ('expected_owner_email = "{0}"' -f $Owner)
  ('credential_reference_id = "{0}"' -f $Credential.credential_id)
  'google_enabled = true'
  'google_write_enabled = true'
)
[IO.File]::WriteAllLines($Config, $ConfigLines, $Utf8NoBom)
```

Render and validate the Windows definition without invoking Task Scheduler:

```powershell
$RenderJson = & $ProjectOS adoption fixture scheduler render --fixture-ack FIXTURE_ONLY `
  --contextos-root $Fixture --machine-profile $Profile
$Render = $RenderJson | ConvertFrom-Json
if (-not $Render.ok -or $Render.data.enabled -or $Render.data.interval_seconds -ne 7200) {
  throw 'scheduler render contract failed'
}
if ($Render.data.scheduler_kind -ne 'windows-task-scheduler') { throw 'wrong scheduler kind' }
[ordered]@{
  ok = $Render.ok
  command = $Render.command
  scheduler_kind = $Render.data.scheduler_kind
  task_id = $Render.data.task_id
  interval_seconds = $Render.data.interval_seconds
  execution_limit_seconds = $Render.data.execution_limit_seconds
  enabled = $Render.data.enabled
  sha256 = $Render.data.sha256
} | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $Evidence '14-scheduler-render.json')
```

Activate through the fixture runner, inspect discovery, then deactivate:

```powershell
& $ProjectOS adoption fixture activate $Adopt.data.transaction_id --fixture-ack FIXTURE_ONLY `
  --contextos-root $Fixture --machine-profile $Profile |
  Set-Content -LiteralPath (Join-Path $Evidence '15-activate.json')
$Activation = Get-Content -Raw -LiteralPath (Join-Path $Evidence '15-activate.json') | ConvertFrom-Json
if (-not $Activation.ok -or $Activation.data.state -ne 'PROVED') { throw 'fixture activation failed' }
$SkillJson = & $ProjectOS adoption fixture skill inspect --fixture-ack FIXTURE_ONLY `
  --contextos-root $Fixture --machine-profile $Profile
$Skill = $SkillJson | ConvertFrom-Json
if (-not $Skill.ok -or $null -eq $Skill.data.skill) { throw 'skill discovery failed' }
[ordered]@{
  ok = $Skill.ok
  command = $Skill.command
  skill_id = $Skill.data.skill.skill_id
  version = $Skill.data.skill.version
  capabilities = $Skill.data.skill.capabilities
  diagnostic = $Skill.data.diagnostic
} | ConvertTo-Json -Depth 5 -Compress |
  Set-Content -LiteralPath (Join-Path $Evidence '16-skill-inspect.json')
& $ProjectOS adoption fixture deactivate $Activation.data.activation_id `
  --fixture-ack FIXTURE_ONLY --contextos-root $Fixture --machine-profile $Profile |
  Set-Content -LiteralPath (Join-Path $Evidence '17-deactivate.json')
$Deactivation = Get-Content -Raw -LiteralPath (Join-Path $Evidence '17-deactivate.json') | ConvertFrom-Json
if (-not $Deactivation.ok -or $Deactivation.data.state -ne 'DEACTIVATED') {
  throw 'fixture deactivation failed'
}
& $ProjectOS adoption fixture rollback $Adopt.data.transaction_id `
  --fixture-ack FIXTURE_ONLY --contextos-root $Fixture --machine-profile $Profile |
  Set-Content -LiteralPath (Join-Path $Evidence '18-definition-rollback.json')
$Rollback = Get-Content -Raw -LiteralPath (Join-Path $Evidence '18-definition-rollback.json') | ConvertFrom-Json
if (-not $Rollback.ok -or $Rollback.data.state -ne 'ROLLED_BACK') {
  throw 'definition rollback after deactivation failed'
}
```

The activation proof uses the package's fake gateway. It must not prompt for Google authentication or make a network request. The fixture runner persists state only below `$Runtime\adoption\scheduler-fixtures`; after deactivation its task state must be absent. Do not run `runtime sync` in this handoff because that command intentionally constructs the guarded real Google gateway.

If activation exits `3`, identify the newest activation ID and run recovery twice:

```powershell
$ActivationId = (Get-ChildItem -LiteralPath (Join-Path $Runtime 'adoption\activations') -Directory |
  Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).Name
1..2 | ForEach-Object {
  & $ProjectOS adoption fixture activation-recover $ActivationId `
    --fixture-ack FIXTURE_ONLY --contextos-root $Fixture --machine-profile $Profile |
    Set-Content -LiteralPath (Join-Path $Evidence ('19-recovery-{0}.json' -f $_))
}
```

Both results must be `ROLLED_BACK` and byte-equivalent apart from the outer command name only if different commands were used. Stop on an ownership, inventory, registry, or definition mismatch. Do not edit or delete the failed state.

Native Task Scheduler creation, the real two-hour trigger, non-overlap execution, missed-run behavior, disablement, and removal belong to Phase 3D. Do not run `schtasks`, Task Scheduler COM, PowerShell task-registration commands, or an elevated console. Do not target an existing ContextOS root or perform Google/GAS/Looker work.

## Evidence return

Return one archive named `projectos-phase3c-windows-evidence-<YYYYMMDD>.zip` containing:

```text
00-prerequisites.txt
01-localappdata.txt
02-drive-inspect.json
03-drive-profile.json
04-unc-inspect.json
05-unc-profile.json
06-manifest.json
07-bundle-build.json
08-bundle-verify.json
09-bundle-sha256.txt
10-links.txt
11-fixture-init.json
12-fixture-preflight.json
13-fixture-adopt.json
14-scheduler-render.json
15-activate.json
16-skill-inspect.json
17-deactivate.json
18-definition-rollback.json
19-recovery-1.json (only after failure)
19-recovery-2.json (only after failure)
20-python-version.txt
21-projectos-version.txt
22-source-revision.txt
23-wheel-sha256.txt
24-host-summary.txt
25-adoption-artifact-inventory.txt
```

`24-host-summary.txt` may contain Windows edition/build, architecture, account type (standard/admin), and whether Developer Mode is off. `25-adoption-artifact-inventory.txt` lists relative paths and SHA-256 hashes only for definition and activation journals, snapshots, staged versions, scheduler fixture artifacts, proofs, and archives. Do not include the fixture database or configuration, usernames, home paths, machine names, account emails, tokens, credentials, real Google identifiers, or private project data. A controlling review must reconcile every returned hash and envelope before Windows is marked verified.
