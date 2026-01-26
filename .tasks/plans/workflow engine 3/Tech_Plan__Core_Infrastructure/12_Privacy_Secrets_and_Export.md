# Core Infrastructure — Privacy, Secrets, and Export Controls

- **Doc**: Tech_Plan__Core_Infrastructure/12_Privacy_Secrets_and_Export.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.privacy`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md)
- **Primary responsibility**: Secrets storage, outbound network policy, mandatory redaction/secret scanning, and scrubbed evidence exports.

## 12) Secrets, privacy, and export controls (trust requirement)

### 12.1 Secrets storage (low-friction, cross-platform)

All long-lived secrets (model provider keys, tokens) MUST be stored in the OS credential store via the Python **keyring** interface when available.

- Keyring project: https://pypi.org/project/keyring/

Fallback (when no system keyring is available):
- store an encrypted local secrets file under `~/.workflow/secrets/`
- encryption key is stored in the best available OS facility; if none exists, require user passphrase (last resort)

**Never** store secrets in:
- WSS JSON docs
- log events
- workflow YAML
- exported bundles

### 12.2 Network policy (explicit, default-safe)

`privacy.network_mode` governs outbound network:

- `off`: no outbound network; remote models disabled; only local tooling allowed
- `llm_only` (default): only known model provider endpoints are allowed (best-effort enforcement; also logged)
- `unrestricted`: no restriction (advanced users)

All remote LLM calls MUST:
- go through a cancellable subprocess boundary (so PAUSE can stop them)
- use redaction policies (§12.3)
- log only request metadata, not raw prompts by default (see below)

### 12.3 Secret scanning and redaction (mandatory on outbound)

Before sending any text to a remote model OR exporting a bundle, run secret scanning.

Minimum detectors:
- PEM private keys (`BEGIN ... PRIVATE KEY`)
- AWS access keys
- GitHub tokens
- generic high-entropy token heuristics (bounded to avoid false positives)
- `.env` and known secret file patterns (path-based)

Policy:
- `block_on_secret` (default): abort outbound operation; emit notification with offending evidence refs
- `redact_and_continue`: replace secret substrings with `REDACTED(<kind>:<hash>)` and proceed

### 12.4 Prompt logging (avoid accidental retention)

Default:
- store a **prompt manifest** (hashes + pointers) rather than full prompts:
  - `prompt_hash`
  - `bundle_id`
  - referenced file slice hashes
- store full prompts only when `privacy.allow_prompt_capture = true`

### 12.5 Export scrubber (shareable evidence bundles)

`workflowctl export scrub <run_id|ticket_id>` produces a shareable archive that:
- removes secrets (scanner + redaction)
- replaces file contents with hashes unless explicitly included
- includes:
  - run/step metadata
  - logs (optionally truncated)
  - environment capture
  - conclusions and conflict records
- emits a manifest of what was removed/redacted

Export is **always explicit** (no background uploads).

