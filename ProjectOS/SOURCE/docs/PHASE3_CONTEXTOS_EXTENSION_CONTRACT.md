# ContextOS Extension Contract for ProjectOS

ProjectOS Phase 3 requires ContextOS to expose a read-only, versioned extension contract at:

```text
<contextos-root>/context-os/config/extension-contract.json
```

ProjectOS never creates or repairs this file during discovery. A missing, malformed, unsupported, or incompatible contract blocks adoption without changing either product.

## Contract version 1

```json
{
  "contract_version": 1,
  "contextos_version": "3.0.1",
  "extensions_root": "context-os/extensions",
  "skills_root": "skills",
  "runtime_root_template": "~/Library/Application Support/ClaudeContextOS/home",
  "supported_hosts": ["macos", "windows"]
}
```

Fields:

- `contract_version` is the integer `1`.
- `contextos_version` is a three-component numeric version. Phase 3A accepts versions greater than or equal to `3.0.1` and lower than `4.0.0`.
- `extensions_root` is a relative path beneath the discovered ContextOS root.
- `skills_root` is a relative path beneath the discovered ContextOS root.
- `runtime_root_template` documents the machine-local ContextOS runtime convention. It is not a ProjectOS runtime path and is not copied into a shared ProjectOS bundle.
- `supported_hosts` contains one or both exact values: `macos`, `windows`.

Absolute extension or skill paths and any path containing a parent traversal component are rejected. The contract must not contain credentials, tokens, personal identifiers, resolved home paths, drive assignments, or deployment-specific NAS names.

## Windows example

Windows may use the same portable relative extension and skill paths while declaring its local runtime convention:

```json
{
  "contract_version": 1,
  "contextos_version": "3.0.1",
  "extensions_root": "context-os\\extensions",
  "skills_root": "skills",
  "runtime_root_template": "%LOCALAPPDATA%\\ClaudeContextOS\\home",
  "supported_hosts": ["macos", "windows"]
}
```

The Windows installation does not require symlinks or Developer Mode. The active installation supplies its own machine profile separately; distributable definitions never embed the installing user's resolved path.

## Discovery precedence

ProjectOS locates ContextOS in this order:

1. explicit `--contextos-root` input;
2. `CONTEXTOS_ROOT`;
3. the current user's `.claude` directory.

A higher-precedence value is authoritative. ProjectOS does not silently fall back to a different installation when that value is incompatible.

## Failure behavior

Contract discovery is read-only. Failure does not create a ProjectOS database, extension registry, skill directory, scheduler definition, ContextOS profile, or replacement contract. Compatibility changes belong to a separately staged ContextOS build and require their own verification before adoption.
