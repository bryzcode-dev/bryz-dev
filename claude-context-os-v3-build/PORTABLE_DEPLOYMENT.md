# Portable Deployment

Context OS V3 separates the platform from environment-specific knowledge so the same OS can be used at home and work without copying personal/home project history into an enterprise environment.

## Export the platform

```bash
python3 contextctl.py export-portable \
  --output ~/Desktop/context-os-v3-portable.zip
```

The export contains the platform implementation, templates, schemas, skills, agent definition, and documentation. It does not export the active user's project knowledge, EA preference database, runtime SQLite database, logs, caches, or secrets.

## Home profile

Example:

```text
Claude root:  /Volumes/BryzConfig/Claude
Runtime:      ~/Library/Application Support/ClaudeContextOS/home
Profile:      home
```

## Work profile

A work machine can use a normal local Claude root:

```text
Claude root:  ~/.claude
Runtime:      ~/Library/Application Support/ClaudeContextOS/work
Profile:      work
```

Adopt with a fresh local work knowledge domain:

```bash
python3 contextctl.py adopt \
  --root ~/.claude \
  --workspace ~/.context-os-migrations \
  --runtime "$HOME/Library/Application Support/ClaudeContextOS/work" \
  --profile work
```

Follow the same review/verify/activate sequence from `ADOPTION_PROTOCOL.md`.

## Air-gapped/offline rule

V3 core requires only Python standard-library components and SQLite supplied by Python. Optional binaries/models must be installed or transferred into the environment ahead of time. V3 never downloads them at runtime.

Optional local-only integrations are capability profiles, not correctness dependencies:

- Gitleaks: deeper secret scanning
- OPA: external local policy evaluator
- ast-grep / Tree-sitter / Serena: code intelligence
- Restic: encrypted snapshot repositories
- Basic Memory / approved local embeddings: semantic retrieval layer

If an optional tool is absent, core V3 continues to work.

## Knowledge isolation

Home and work should have separate:

- project registries
- task ledgers
- knowledge cards
- event logs
- EA interaction preferences when required by policy
- SQLite indexes

The executable platform may be identical; the knowledge domains are not automatically synchronized.
