# Core Infrastructure — Dependency Management and Reproducibility

- **Doc**: Tech_Plan__Core_Infrastructure/13_Dependency_Management.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.dependencies`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`03_IDs_and_Time.md`](03_IDs_and_Time.md), [`10_Configuration_System.md`](10_Configuration_System.md), [`12_Privacy_Secrets_and_Export.md`](12_Privacy_Secrets_and_Export.md)
- **Primary responsibility**: Deterministic dependency checks (`doctor`), bounded bootstrap, and run reproducibility via tool fingerprints + env capture.

## 13) Dependency management (trust + friction)

### 13.1 Required external tools

Baseline:
- `git` (already present for developers)
- `jj` (Patch-Stream backbone)

Optional (per workflow):
- language toolchains (python/node/rust/etc)
- test runners, linters

### 13.2 `doctor` and `bootstrap` responsibilities

`workflowctl doctor` and `workflowctl bootstrap` are **trust and friction** utilities. They MUST be deterministic and must fail loudly.

#### 13.2.1 `workflowctl doctor` (normative checks)

`doctor` performs these checks, in this order. Each failing check MUST emit:
- one structured error (Core §8.2.4)
- one log event (`doctor_failed`)
- a non-zero process exit code

Checks:

1. **Locate repo root**
   - Command: `git rev-parse --show-toplevel`
   - Pass: command succeeds and returns a path
   - Fail (`E_NOT_FOUND`): “Not inside a git repository.”

2. **Derive or load `repo_uid`**
   - If `~/.workflow/repos/<repo_uid>/repo.json` exists, load it and use its `repo_uid`.
   - Otherwise, derive `repo_uid` per §3 and report that the repo is “not initialized”.

3. **Runtime root writable**
   - Attempt to create and delete: `~/.workflow/.write_test.<ulid>`
   - Attempt to create `~/.workflow/repos/<repo_uid>/` if missing
   - Fail (`E_NOT_ALLOWED`): insufficient permissions

4. **Tool availability**
   - `git`:
     - Pass if `git --version` succeeds
     - Fail (`E_DEPENDENCY_MISSING`) otherwise
   - `jj`:
     - Determine `jj_path`:
       1) repo-machine-local config override (if present)
       2) `PATH`
     - Pass if `jj --version` succeeds
     - Fail (`E_DEPENDENCY_MISSING`) otherwise

5. **`jj` version check**
   - Parse `jj --version` as a SemVer-like `MAJOR.MINOR.PATCH` (ignore suffixes like `-rc1` for minimum comparison).
   - Minimum required: `dependencies.jj_min_version` (Core config §11.4).
   - Fail (`E_DEPENDENCY_MISSING`) if installed version is less than minimum.

6. **Repo compatibility**
   - Pass if the repo is usable as a jj-backed Patch-Stream:
     - `jj root` succeeds, OR
     - repo is a git repo and `workflowctl bootstrap` is permitted to initialize jj (policy/config dependent)
   - Fail (`E_NOT_ALLOWED`) if jj is missing or repo cannot be used.

7. **Quick integrity checks**
   - `workflowctl fsck --quick` MUST run:
     - WSS JSON parse + schema_version checks
     - required fields present (§5.2)
     - log shard trailing partial line handling (§8.4)
   - Fail (`E_INTERNAL`) if corruption is detected.

On full success, `doctor` MUST emit:
- log event `doctor_ok`
- exit code `0`

#### 13.2.2 `workflowctl bootstrap` (low friction; bounded)

`bootstrap` may download or prepare dependencies when allowed by config.

Normative behavior:

- If `jj` is missing AND `dependencies.auto_bootstrap_jj=true`:
  - Download a pinned jj release into `~/.workflow/tools/jj/<version>/jj[.exe]`
  - Record the chosen `jj_path` in repo-machine-local config: `~/.workflow/repos/<repo_uid>/config.toml`
- Otherwise:
  - Fail with `E_DEPENDENCY_MISSING` and an actionable message

`bootstrap` MUST:
- print/log the exact actions it will perform before executing them
- never make network calls unless allowed by `[privacy].network_mode` (Core config §11.4)
### 13.3 Tool fingerprints and env capture

Every tool execution that matters MUST emit two artifacts:

- `tool_fingerprint` — a stable identifier for “what tool ran, with what argument shape, in what relevant environment”
- `env_capture.json` — a bounded, redact-safe snapshot of runtime environment (versions + platform) for reproducibility

Artifacts live under:

- `workspace/runs/<run_id>/artifacts/env/`

#### 13.3.1 Tool fingerprint format

A tool fingerprint is a string:

- `tfp1:sha256:<hex>`

It is computed from a canonical JSON payload.

##### Payload fields (v1)

```json
{
  "schema_version": 1,
  "tool_name": "pytest",
  "tool_path": "/usr/bin/pytest",
  "tool_realpath": "/usr/bin/pytest",
  "tool_version": "pytest 8.2.0",
  "args_class": "--maxfail <N> -q <PATH> ...",
  "env_sigs": {
    "PATH": "sha256:<hex>",
    "PYTHONPATH": "sha256:<hex>"
  },
  "binary_sha256": "sha256:<hex>|null"
}
```

Rules:

- `tool_path` MUST be the absolute path used for execution.
- `tool_realpath` MUST be the resolved symlink target of `tool_path`.
- `tool_version` MUST be obtained via a tool-specific version probe (usually `--version`).
- `binary_sha256`:
  - included only if enabled by config (`[tool_fingerprint] include_binary_hash = true`)
  - otherwise MUST be `null`
- `env_sigs` MUST store **hashes of values**, never raw values.

##### Selected env var set (default)

The fingerprint includes hashes for the following variables if present:

- `PATH`
- `PYTHONPATH`
- `VIRTUAL_ENV`, `CONDA_PREFIX`
- `NODE_OPTIONS`
- `JAVA_HOME`
- `GOROOT`, `GOMODCACHE`
- `CARGO_HOME`, `RUSTUP_HOME`
- `LANG`, `LC_ALL`

Workflows MAY extend this set via config (`[tool_fingerprint] extra_env = [...]`).

##### `args_class` definition

`args_class` is a deterministic normalization of `argv[1:]` intended to group runs that differ only in volatile values (paths, numbers).

Normative normalization:

- Split tokens on the first `=` for long options of the form `--opt=value` and rewrite as `--opt=<VAL>`.
- For tokens that are values to an option (the token immediately following a token starting with `-`), rewrite as `<VAL>`, except when the value is itself a flag (starts with `-`).
- For remaining non-flag tokens:
  - if it contains `/` or `\` → `<PATH>`
  - else if it ends with a common extension (`.py`, `.js`, `.ts`, `.go`, `.rs`, `.json`, `.yaml`, `.yml`) → `<PATH>`
  - else if it is an integer → `<N>`
  - else → `<ARG>`

The normalized tokens are joined with single spaces.

#### 13.3.2 Fingerprint computation

1. Build the payload object.
2. Serialize it as canonical JSON:
   - UTF-8
   - object keys sorted lexicographically
   - no insignificant whitespace
3. Compute:
   - `digest = sha256(canonical_bytes)`
4. Emit:
   - `tool_fingerprint = "tfp1:sha256:" + digest.hexdigest()`

The full payload SHOULD be persisted alongside the tool run record as `tool_fingerprint.json` for auditability.

#### 13.3.3 env_capture.json

`env_capture.json` is a bounded, redact-safe snapshot.

Minimum fields:

- `schema_version`
- `os` (name, version)
- `arch`
- `jj_version`
- language runtimes (when applicable): `python_version`, `node_version`, `java_version`, `go_version`, `rustc_version`
- `repo_uid`
- `base_rev` / `tip_rev` (when the tool run is tied to a ticket stack)

It MUST NOT include secret values. If environment variables are captured, they MUST be captured only as hashes.

