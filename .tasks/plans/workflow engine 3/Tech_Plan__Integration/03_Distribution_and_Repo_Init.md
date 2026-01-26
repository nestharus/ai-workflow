# Tech Plan: Integration — Distribution & Repo Init

- **Doc**: Tech_Plan__Integration/03_Distribution_and_Repo_Init.md
- **Updated**: 2026-01-26
- **Shard**: Integration §3–§3.4
- **Libraries / packages**:
  - `workflowctl/` (installation, bootstrap, init UX)
  - `scripts/core/protocol/*` and `scripts/core/storage/*` (artifact evidence for `init_report.json`)
- **Depends on**:
  - `Tech_Plan__Configuration_&_Onboarding.md` (full onboarding flow)
  - `Tech_Plan__Core_Infrastructure.md` (WSS paths, run/artifact conventions)

## 3) Distribution (low friction)

### 3.1 Preferred distribution (single binary per platform)
To minimize installs and version drift:

- Distribute `workflowctl` + the interactive CLIs as a single self-contained executable per platform (bundled Python runtime + dependencies).
- External installs should be limited to:
  - `git` (assumed present for developers)
  - `jj` (auto-bootstrap supported; see §10)

### 3.2 Auto-bootstrap tools (optional but recommended)
If configured (`dependencies.auto_bootstrap_jj=true`), `workflowctl bootstrap` can download a pinned `jj` binary into:
`~/.workflow/tools/jj/<version>/jj[.exe]`

This reduces user friction without requiring system package managers.


### 3.3 Supported install modes (choose 1)

To match different user preferences while keeping friction low:

1. **Prebuilt executable (recommended)**  
   - Single file per platform (bundled Python runtime + dependencies).
   - Fastest onboarding and least version drift.

2. **Remote bootstrap script (recommended for prototypes)**  
   - One command downloads the pinned executable and installs a small shim into a user-writable bin dir.
   - Script never mutates the repo; it only installs under `~/.workflow/` and the user’s PATH.

3. **Python package (workflow authoring / library use)**  
   - `workflowctl` can also be installed as a Python package so users can write Python workflows against the library.
   - The engine still enforces the gateway/capability model at runtime.

All modes converge to the same on-disk runtime root: `~/.workflow/`.

### 3.4 Repo init (first-run UX)

`workflowctl init` is the per-repo onboarding action. It is self-bootstrapping.

**Detailed behavior**: See **Tech_Plan__Configuration_&_Onboarding.md §2** for the full onboarding flow.

**Self-bootstrapping flow**:
1. `init` asks user which CLI they use (interactive prompt)
2. `init` launches that CLI with a bootstrap prompt
3. Agent installs the workflow-manager skill
4. Agent uses the skill to configure everything else

**Key principles**:
- **Zero project pollution by default**: `init` writes only to `~/.workflow/repos/<repo_uid>/`
- **Project files are opt-in**: `--project` flag required to create `<repo>/.workflow/`
- **Self-bootstrapping**: Agent installs skill first, then uses it to configure

**Responsibilities**
- Create `~/.workflow/repos/<repo_uid>/` and `repo.json` (always)
- Ask user which CLI they use (always)
- Launch that CLI with bootstrap prompt (always)
- With `--project` flag: also create `<repo>/.workflow/` structure

**Non-goals**
- `init` does **not** create tickets, does **not** import docs, and does **not** start a background daemon.

**Evidence**
- `init_report.json` written under `workspace/runs/<run_id>/artifacts/` for auditability (what files were created/modified).
