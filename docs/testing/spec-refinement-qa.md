# Spec Refinement Pipeline QA

QA processes for validating the spec refinement pipeline (Phases 1-6).

## Pipeline Overview

```text
Phase 1: Summarization     (glm-file-what-summarizer)
Phase 2: Library Synthesis  (opus-library-synthesizer)
Phase 3: Evidence Expansion (glm-library-evidence-mapper, chatgpt-evidence-gap-judge)
Phase 4: Spec Building      (glm-library-spec-integrator, chatgpt-library-spec-gap-judge)
Phase 5: Sublibrary Detect  (opus-sublibrary-planner)
Phase 6: Architecture       (opus-architecture-proposer, chatgpt-tradeoff-judge, glm-mapper)
```

## Running Tests

### Automated Tests (No LLM)

Run all spec refinement tests (mocked agents, no LLM calls):

```bash
uv run pytest scripts/tests/unit/spec_refinement/ scripts/tests/component/test_spec_building.py scripts/tests/component/test_evidence_expansion.py tests/spec_refinement/ -v
```

These tests validate:

* State transitions (phase lifecycle, gap audit tracking)
* Prompt construction (correct format, required fields)
* Output parsing (formats.py parsers for JSON and markdown)
* Workspace file I/O (charter, evidence, spec, gaps artifacts)
* Agent retry logic (subprocess mock with failures)
* Validation (evidence pointers, section references, citations)
* Gap closure convergence (iterative gap detection and merge)
* Monotonic spec growth (no content removal during integration)

### Manual E2E Validation

For end-to-end runs against real LLMs, execute phases sequentially:

```bash
uv run spec init <run_id> <input_folder>
uv run spec spec summarize <run_id> --sequential
uv run spec spec synthesize <run_id>
uv run spec spec expand-evidence <run_id>
uv run spec spec build-specs <run_id> --max-iterations 1
uv run spec spec detect-sublibraries <run_id>
uv run spec spec propose-architectures <run_id>
uv run spec spec select-architecture <run_id>
uv run spec spec map-libraries <run_id>
```

## Per-Phase QA Checklist

### Phase 1: Summarization

**Command:** `uv run spec spec summarize <run_id> --sequential`

**Check after run:**

1. State is COMPLETED: `uv run spec status <run_id>` shows summarization completed
2. Summary files exist: `ls runs/<run_id>/summaries/` has one `.what.md` per input file
3. Evidence pointers valid: Each summary contains `[FILE_ID::SECTION]` pointers
4. Structured sections present: Each summary has Algorithms, Components, Workflows,
   Candidate Responsibilities, Dependencies, Evidence Map headings

**Validation commands:**

```bash
# Check summary count matches input file count
ls runs/<run_id>/summaries/*.what.md | wc -l

# Verify evidence pointers exist in summaries
grep -c '\[F' runs/<run_id>/summaries/*.what.md

# Check state
uv run spec status <run_id>
```

**Common failures:**

* Agent returns empty output: Check `runs/<run_id>/agent_prompts/` for the prompt file
  and verify the agent name `glm-file-what-summarizer` exists in `.agents/agents/`
* >50% file failures: Phase marks as FAILED; check state.json for error details
* Missing evidence pointers: Agent output doesn't follow the template format

### Phase 2: Library Synthesis

**Command:** `uv run spec spec synthesize <run_id>`

**Check after run:**

1. Library index exists: `runs/<run_id>/libraries/library_index.md`
2. Library directories created: `ls runs/<run_id>/libraries/` shows `LIB-0001/`, `LIB-0002/`, etc.
3. Each library has artifacts: `charter.md`, `evidence.json`, `gaps.md`, `decisions.md`
4. Library IDs follow format: `LIB-\d{4}` (e.g., LIB-0001, LIB-0002)
5. Evidence sources reference valid files from the manifest

**Validation commands:**

```bash
# Check library directories
ls -d runs/<run_id>/libraries/LIB-*/

# Verify each library has required artifacts
for lib in runs/<run_id>/libraries/LIB-*/; do
  echo "=== $(basename $lib) ==="
  ls "$lib"
done

# Check evidence.json is valid JSON
for f in runs/<run_id>/libraries/LIB-*/evidence.json; do
  uv run python -c "import json; json.load(open('$f'))" && echo "$f OK" || echo "$f INVALID"
done
```

**Common failures:**

* No `LIB-\d{4}` IDs in output: Agent didn't follow the expected format
* Overlap resolution missing: Check charter.md for "Overlap Resolutions" section

### Phase 3: Evidence Expansion

**Command:** `uv run spec spec expand-evidence <run_id>`

**Check after run:**

1. Evidence sources added: Output shows `evidence_sources_added > 0`
2. Libraries expanded: At least some libraries got new evidence
3. Confidence filtering: Only entries with confidence >= 0.5 are added
4. Section validation: All sections reference known section IDs from the manifest

**Validation commands:**

```bash
# Check evidence.json has sources with sections
for f in runs/<run_id>/libraries/LIB-*/evidence.json; do
  echo "=== $(basename $(dirname $f)) ==="
  uv run python -c "
import json
data = json.load(open('$f'))
for s in data.get('sources', []):
    print(f\"  {s['file_id']}: {s.get('sections', [])} conf={s.get('confidence', 'N/A')}\")
"
done
```

**Common failures:**

* 0 libraries expanded: Token-based pre-filter excluded all pairs (charter terms don't
  overlap with summary terms). Check charter keywords vs summary content.
* All agent calls fail: Verify `glm-library-evidence-mapper` agent is configured
* Summary heading confusion: GLM agent returns summary headings (Components,
  Workflows, Candidate Responsibilities) instead of source file section labels
  (INTRO, BOUNDARIES, REQS, CONSTRAINTS). The pipeline's section validator
  correctly filters these as `unknown_section_reference` issues. Only valid
  sections from the section_manifest are kept.

### Phase 4: Spec Building

**Command:** `uv run spec spec build-specs <run_id> --max-iterations 1`

**Check after run:**

1. Spec files exist: `runs/<run_id>/libraries/LIB-*/spec.md`
2. Specs contain citations: `[FILE_ID::SECTION]` pointers in Requirements/Constraints
3. Gap files updated: `runs/<run_id>/libraries/LIB-*/gaps.md`
4. Decisions tracked: `runs/<run_id>/libraries/LIB-*/decisions.md`
5. Convergence: Output shows converged_count vs libraries_built

**Validation commands:**

```bash
# Check spec files exist and have content
for f in runs/<run_id>/libraries/LIB-*/spec.md; do
  echo "=== $(basename $(dirname $f)) ==="
  wc -l "$f"
done

# Check for evidence pointers in specs
grep -c '\[F' runs/<run_id>/libraries/LIB-*/spec.md

# Check gap status
for f in runs/<run_id>/libraries/LIB-*/gaps.md; do
  echo "=== $(basename $(dirname $f)) ==="
  grep -c 'status:' "$f" 2>/dev/null || echo "No gaps"
done
```

**Common failures:**

* Non-monotonic integration: Agent removed existing content; spec reverted
* No evidence sources: Library has empty evidence.json; skip with error
* Gap judge parse failure: JSON output doesn't match expected schema
* Monotonic deadlock: Charter introduces a boundary claim not in source files;
  integrator can't delete it (monotonic rule); gap judge keeps flagging it.
  Example: charter says "Does NOT own throughput management" but source only says
  "Does NOT own request routing or input validation". The claim stays in the spec
  and gaps never converge.
* Self-referencing citations: Integrator cites the spec itself
  (e.g., `[libraries/LIB-0002/spec.md::Boundaries]`) instead of source files.
  Citation validator rejects these as `unknown_file_reference`.
* GPT-5.2 xhigh latency: Gap judge calls take 60-120s each; with 2 libraries
  and 2 files, a single iteration takes ~6-8 minutes. Plan max-iterations
  accordingly.

### Phase 5: Sublibrary Detection

**Command:** `uv run spec spec detect-sublibraries <run_id>`

**Check after run:**

1. Sublibraries created: `runs/<run_id>/libraries/LIB-*/sublibraries/` directories
2. Each sublibrary has: `charter.md`, `evidence.json`, `gaps.md`, `decisions.md`
3. Evidence partitions: Sublibraries don't share >20% evidence overlap
4. Recursive refinement: Sublibraries get evidence expansion and spec building

**Common failures:**

* Missing spec.md/charter.md: Library skipped
* Evidence overlap >20%: Sublibrary creation blocked with validation issue

### Phase 6: Architecture

**Commands (run in order):**

```bash
uv run spec spec propose-architectures <run_id>
uv run spec spec select-architecture <run_id>
uv run spec spec map-libraries <run_id>
```

**Check after run:**

1. Candidates exist: `runs/<run_id>/architecture/candidates/arch_*.md`
2. Selection made: `runs/<run_id>/architecture/selected.md`
3. Rejected recorded: `runs/<run_id>/architecture/rejected.md`
4. Mapping complete: `runs/<run_id>/architecture/mapping.md`
5. No unmapped libraries (or documented why unmapped)

## Debugging Agent Execution

### Agent Not Found

If you see `Error: Agent not found: <agent-name>`:

1. Check agent file exists: `ls .agents/agents/<agent-name>.md`
2. Check frontmatter has model field: `head -5 .agents/agents/<agent-name>.md`
3. Check model exists: `ls .agents/models/<model-name>.toml`

### Agent Returns Empty Output

1. Check the prompt file: `ls runs/<run_id>/agent_prompts/`
2. Run the agent manually: `uv run agents <agent-name> --file <prompt-file> --project .`
3. Check stderr for agent-exec metadata lines
4. Verify the model command works: e.g., `opencode run -m cerebras/zai-glm-4.7 "test"`

### Agent Returns Non-Parseable Output

1. Check the raw output in agent_prompts directory
2. Common issues:
   * Agent includes markdown fences around JSON (parser handles this)
   * Agent includes `[agent-exec]` metadata lines (parser strips these)
   * Agent returns prose instead of structured JSON
   * Agent uses wrong section headings (case-sensitive matching)

### Subprocess Debugging

The agent execution path is:

```text
run_agent() -> subprocess.run(["uv", "run", "agents", <name>, "--file", <file>])
  -> scripts/agents/__main__.py -> load agent config -> subprocess.run([model.command, *model.args, prompt])
```

To trace execution:

```bash
# Check what command the agent framework would run
uv run agents <agent-name> --file <prompt-file> --project . 2>&1 | head -5
# stderr shows: [agent-exec] model=... cmd=... args=... mode=... prompt_len=...
```

## State Inspection

### Check Phase Status

```bash
uv run spec status <run_id>
```

### Inspect State JSON Directly

```bash
python3 -c "
import json
state = json.load(open('runs/<run_id>/state.json'))
for phase, result in state.get('phases', {}).items():
    status = result.get('status', 'unknown')
    error = result.get('error', '')
    print(f'{phase}: {status}' + (f' ERROR: {error}' if error else ''))
"
```

### Check Gap Audit History

```bash
python3 -c "
import json
state = json.load(open('runs/<run_id>/state.json'))
for phase, result in state.get('phases', {}).items():
    iterations = result.get('gap_audit_iterations', 0)
    if iterations > 0:
        converged = result.get('gap_audit_converged', False)
        open_gaps = result.get('open_gaps_count', 0)
        print(f'{phase}: {iterations} iterations, converged={converged}, open_gaps={open_gaps}')
"
```

## Test Architecture

Tests are structured to validate pipeline behaviors without LLM calls:

```text
scripts/tests/unit/spec_refinement/
  test_summarization.py         # Phase 1 with mocked agent
  test_library_synthesis.py     # Phase 2 with mocked agent
  test_sublibrary_detection.py  # Phase 5 with mocked agent
  test_formats.py               # All parsers (pure logic, no mocks)
  test_agent_utils.py           # Agent execution (mocked subprocess)
  core/
    test_gap.py                 # Gap dataclass, synthesizer, serialization
  workspace/
    test_manager_gaps.py        # Gap read/write/audit
    test_manager_sublibraries.py # Sublibrary path management

scripts/tests/component/
  test_evidence_expansion.py    # Phase 3 with mocked agent
  test_spec_building.py         # Phase 4 with mocked agent

tests/spec_refinement/
  test_architecture_workflows.py # Phase 6 with mocked agent
```

### Mock Pattern

All workflow tests mock `run_agent` to return deterministic outputs:

```python
from unittest.mock import patch

def _fake_run_agent(outputs: dict[str, str]):
    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        match = re.search(r"File ID: (F\d{4})", prompt)
        file_id = match.group(1) if match else "unknown"
        return outputs[file_id]
    return _run_agent

with patch("spec_manager.refinement.workflows.summarization.run_agent",
           side_effect=_fake_run_agent(outputs)):
    result = summarize_all("run1", parallel=False)
```

### Workspace Setup Pattern

Tests use pyfakefs for filesystem isolation:

```python
def _setup_workspace(fs, monkeypatch) -> Path:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n")
    manager = WorkspaceManager(run_id="run1", input_folder=input_dir)
    manager.initialize(force=True)
    return input_dir
```
