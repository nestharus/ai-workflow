# Update PRD Synthesis

## Quick Start

Update a PRD synthesis file from messy input (PRD documents, feedback, prose).
Preserves original text fidelity through decomposition and violation-driven patching.

**Placeholder IDs**: During synthesis, elements are assigned temporary placeholder
IDs with `-XX` suffix (e.g., `RES-XX`, `GOAL-XX`, `INV-XX`). Before finalizing,
replace these with sequential numbered IDs (e.g., `RES-01`, `RES-02`). The final
grep command below helps locate any remaining placeholders.

```bash
# Ingest a PRD file
/update-prd .tasks/plans/my-feature/synthesis.md .tasks/plans/my-feature/raw-prd.md

# Add inline feedback
/update-prd .tasks/plans/my-feature/synthesis.md "Add a new goal for caching support"

# Review output: check for placeholder IDs and partial resolutions
grep -n '\-XX' .tasks/plans/my-feature/synthesis.md
```

---

description: Update PRD synthesis file from messy input (PRD, feedback, prose)
argument-hint: "[synthesis-file] [input-file or inline prompt...]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task

---

Update a PRD synthesis file by ingesting messy input through a fidelity-preserving
decomposition and violation-driven patching process.

**Key Principle**: Never rewrite source text until final patch. Original
fidelity is preserved through all stages. Only the patcher transforms source
into synthesis format.

## Arguments

* First argument: Path to synthesis file (will be created if it doesn't exist)
* Remaining: Either a path to an input file OR inline prompt text

### Environment Variables (Optional)

* `SKIP_SYNTHESIS_VALIDATION` (optional): Set to `1` to bypass synthesis
  markup validation. Intended only for development/debugging; production runs
  should not skip validation.

## Examples

```bash
# Ingest a messy PRD file
/update-prd .tasks/plans/my-feature/synthesis.md \
    .tasks/plans/my-feature/raw-prd.md

# Ingest inline feedback
/update-prd .tasks/plans/my-feature/synthesis.md \
    "Add a new goal for caching support"

# Rerun to catch missed violations
/update-prd .tasks/plans/my-feature/synthesis.md \
    .tasks/plans/my-feature/raw-prd.md
```

## Architecture

```text
Input → chunker → chunk-refiner → refined chunks (original text + metadata)
                                        ↓
Synthesis + Refined Chunks → violation-reviewer → constraint violations
                                        ↓
Per-violation → synthesis-patcher → patch using ORIGINAL chunk text
```

**Fidelity preservation**:
* Chunker: splits text (no modification)
* Refiner: adds metadata sidecar (original text untouched)
* Reviewer: identifies violations (no rewriting)
* Patcher: uses original text for patches (only transformation point)

## Workflow

### Step 1: Parse Arguments

```bash
# ARGUMENTS format: "<synthesis-file> <input-file-or-inline-prompt>"
# - Two space-separated tokens are expected
# - First token: path to synthesis file (created if missing)
# - Second token: either a file path or inline prompt text
# - Whitespace handling: multiple spaces are preserved; the remainder after
#   the first space is captured as-is (spaces in inline prompts are kept)
# - For inline prompts with spaces, the entire remainder after first
#   token is captured (including any leading/trailing spaces)
# - Recommended: callers should validate paths before invoking

# Parse first token as synthesis_file, remainder (including spaces) as input
# This handles inline prompts with spaces correctly

# Early check for empty ARGUMENTS before parsing
if [ -z "$ARGUMENTS" ]; then
    echo "Error: missing required arguments." >&2
    echo "Usage: /update-prd <synthesis-file> <input-file-or-prompt>" >&2
    exit 1
fi

if [[ "$ARGUMENTS" == *" "* ]]; then
    synthesis_file="${ARGUMENTS%% *}"
    input="${ARGUMENTS#* }"
else
    synthesis_file="$ARGUMENTS"
    input=""
fi

# Defensive validation: exit with clear error if arguments are missing
if [ -z "$synthesis_file" ]; then
    echo "ERROR: Missing synthesis file argument" >&2
    echo "Usage: /update-prd <synthesis-file> <input-file-or-prompt>" >&2
    echo "Example: /update-prd .tasks/plans/feature/synthesis.md" \
        "input.md" >&2
    exit 1
fi

if [ -z "$input" ]; then
    echo "ERROR: Missing input argument (file path or inline prompt)" >&2
    echo "Usage: /update-prd <synthesis-file> <input-file-or-prompt>" >&2
    echo "Example: /update-prd .tasks/plans/feature/synthesis.md" \
        "\"Add caching goal\"" >&2
    exit 1
fi
```

### Step 2: Prepare Workspace

```bash
# POSIX-compatible ISO 8601 timestamp function
# Note: date -Iseconds is GNU-specific and not portable to macOS/BSD
# This function provides a portable alternative using POSIX format strings
iso_timestamp() {
    # Output format: YYYY-MM-DDTHH:MM:SS+ZZZZ (or Z for UTC)
    # Using -u for UTC to ensure consistent timezone handling
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

# Generate collision-resistant workspace directory name
# Priority: mktemp -d > uuidgen > date+pid+urandom > date+pid+RANDOM
base_dir=".tmp/prd"
if ! mkdir -p "$base_dir"; then
    echo "ERROR: Failed to create base directory: $base_dir" >&2
    exit 1
fi

# Try mktemp -d first (most reliable for unique directories)
workspace_dir=$(mktemp -d "$base_dir/XXXXXX" 2>/dev/null) || workspace_dir=""
if [ -z "$workspace_dir" ] || [ ! -d "$workspace_dir" ]; then
    # mktemp failed or produced empty/non-existent result, try fallbacks
    if [ -n "$workspace_dir" ]; then
        echo "WARNING: mktemp returned '$workspace_dir' but directory" \
            "does not exist" >&2
    fi
    workspace_dir=""
    # Try uuidgen for UUID-based naming
    if command -v uuidgen >/dev/null 2>&1; then
        workspace_dir="$base_dir/$(uuidgen)"
    # Fall back to date + PID + high-entropy hex from /dev/urandom
    elif [ -r /dev/urandom ]; then
        hex_suffix=$(head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n')
        workspace_dir="$base_dir/$(date +%Y%m%d_%H%M%S)_$$_${hex_suffix}"
    # Last resort: date + PID + nanoseconds (if available) or RANDOM
    elif date +%N >/dev/null 2>&1 && [ "$(date +%N)" != "N" ]; then
        workspace_dir="$base_dir/$(date +%Y%m%d_%H%M%S_%N)_$$"
    else
        workspace_dir="$base_dir/$(date +%Y%m%d_%H%M%S)_$$_$RANDOM$RANDOM"
    fi
fi

mkdir -p "$workspace_dir/chunks"
mkdir -p "$workspace_dir/refined"
mkdir -p "$workspace_dir/resolutions"

# Initialize synthesis file if it doesn't exist
if [ ! -f "$synthesis_file" ]; then
    cat > "$synthesis_file" << 'EOF'
# PRD Synthesis

## Resources

<!-- Example entries:
- `RES-01`: API documentation for the target service
- `RES-02`: Existing codebase module at src/core/
-->

## Problem Statement

<!-- Example: Users cannot efficiently process large batches of input files,
leading to manual intervention and delayed workflows. -->

## Goal List

<!-- Example entries:
- **GOAL-01**: Enable batch processing of 1000+ files without manual intervention
- **GOAL-02**: Reduce processing time by 50% compared to current workflow
-->

## Indexed Rule List

### Invariants

<!-- Example entries:
- **INV-01**: All file operations must be atomic (complete fully or not at all)
- **INV-02**: User data must never be modified without explicit confirmation
-->

### Execution Rules

<!-- Example entries:
- **EXEC-01**: Process files in alphabetical order to ensure deterministic output
- **EXEC-02**: Retry failed operations up to 3 times before reporting error
-->

### Processing Rules

<!-- Example entries:
- **PROC-01**: Validate input format before processing begins
- **PROC-02**: Log all state transitions to the audit trail
-->

### Validation Rules

<!-- Example entries:
- **VAL-01**: Input files must be valid UTF-8 encoded text
- **VAL-02**: Output checksums must match expected values within tolerance
-->

## Success Metrics

| ID | Metric | Target | Measurement | Goals |
|----|--------|--------|-------------|-------|
<!-- Example row:
| SM-01 | Batch completion | >= 99% | Successful / total | GOAL-01 |
-->
EOF
fi
```

### Step 3: Determine Input Source

```bash
if [ -f "$input" ]; then
    input_file="$input"
    input_type="file"
else
    input_file="$workspace_dir/input.md"
    if ! echo "$input" > "$input_file"; then
        echo "ERROR: Failed to write inline input to $input_file" >&2
        exit 1
    fi
    input_type="inline"
fi
```

### Step 4: Chunk Input

```bash
uv run python -m scripts.prd.chunker "$input_file" \
    --output-dir "$workspace_dir/chunks" \
    --mode headers

# Fall back to paragraphs if no headers found (zero chunks produced)
# Ensure chunks directory exists before counting
if [ ! -d "$workspace_dir/chunks" ]; then
    echo "ERROR: Chunks directory not created: $workspace_dir/chunks" >&2
    exit 1
fi

# Count matching files using find with newline output piped to wc -l
# Capture find exit code separately to distinguish command failure from zero
chunk_count_output=$(find "$workspace_dir/chunks" -maxdepth 1 -type f \
    -name "chunk_*.md" 2>&1)
find_exit_code=$?
if [ $find_exit_code -ne 0 ]; then
    echo "WARNING: find command failed with exit code $find_exit_code:" \
        "$chunk_count_output" >&2
    chunk_count=0
    find_succeeded=false
else
    chunk_count=$(echo "$chunk_count_output" | grep -c . 2>/dev/null) || chunk_count=0
    find_succeeded=true
fi

# Ensure chunk_count is numeric (default to 0 if empty or non-numeric)
chunk_count=${chunk_count:-0}
if ! [[ "$chunk_count" =~ ^[0-9]+$ ]]; then
    echo "WARNING: Non-numeric chunk count '$chunk_count', defaulting to 0" >&2
    chunk_count=0
fi

# Only re-chunk if find succeeded and zero chunks were produced
# (not when find failed or when there's one valid chunk)
if [ "$find_succeeded" = true ] && [ "$chunk_count" -eq 0 ]; then
    rm -rf "$workspace_dir/chunks"/*
    uv run python -m scripts.prd.chunker "$input_file" \
        --output-dir "$workspace_dir/chunks" \
        --mode paragraphs \
        --min-size 500
fi

# Final validation: ensure chunks directory exists and contains at least one chunk
if [ ! -d "$workspace_dir/chunks" ]; then
    echo "ERROR: Chunks directory does not exist after chunking:" \
        "$workspace_dir/chunks" >&2
    exit 1
fi

# Re-count chunks after potential fallback to paragraph mode
final_chunk_count=$(find "$workspace_dir/chunks" -maxdepth 1 -type f \
    -name "chunk_*.md" 2>/dev/null | wc -l) || final_chunk_count=0
# Ensure final_chunk_count is numeric (default to 0 if empty or non-numeric)
final_chunk_count=${final_chunk_count:-0}
if ! [[ "$final_chunk_count" =~ ^[0-9]+$ ]]; then
    echo "ERROR: Failed to count chunk files (non-numeric result:" \
        "'$final_chunk_count')" >&2
    exit 1
fi

if [ "$final_chunk_count" -eq 0 ]; then
    echo "ERROR: No chunk files produced after chunking." >&2
    echo "Input file: $input_file" >&2
    echo "Chunks directory: $workspace_dir/chunks" >&2
    echo "The input may be empty or contain no extractable content." >&2
    exit 1
fi
```

### Task Execution Model

The workflow uses `Task()` to delegate work to specialized sub-agents. This
section documents the Task execution semantics.

**What is Task()?**

Task() is the Claude Code platform executor for spawning sub-agents. It runs
a prompt against a specified model and returns when the sub-agent completes.

**Signature (Conceptual Pseudocode):**

The following is conceptual pseudocode notation, not an actual API. The bash
examples below show the actual invocation pattern.

```text
Task(
    subagent_type,   # Agent type identifier (e.g., "prd-chunk-refiner")
    model,           # Model to use ("haiku", "sonnet", "opus")
    prompt           # The prompt/instructions for the sub-agent
) -> success/failure
```

**Bash Usage Pattern:**

The following shows how Task() calls appear in this document. Note that
`Task(...)` is a notation representing Claude Code's Task tool invocation,
not a literal bash function call.

```text
# Check return value with if statement (illustrative notation)
if ! Task(subagent_type="...", model="...", prompt="..."); then
    echo "Task failed" >&2
    # Handle failure
fi
```

**Return Semantics:**

* Returns `true` (exit code 0) on successful completion
* Returns `false` (non-zero exit code) on failure or timeout
* Sub-agent output is written to files specified in the prompt, not returned
  directly

**Parallelism:**

* Multiple Task() calls in a single response block execute concurrently
* Claude Code automatically parallelizes and waits for all tasks to complete
* Do NOT use `run_in_background` - parallelism is handled automatically
* Execution blocks until all parallel Task() calls complete before proceeding
  to the next code block

**Timeout Behavior:**

* Timeouts are enforced by the Claude Code Task tool, not in-code
* Default timeout is configured in Claude Code settings (typically 2-5 minutes)
* For custom timeouts, set `CLAUDE_TASK_TIMEOUT_SECONDS` environment variable
  (global setting; see Claude Code configuration documentation at
  [https://docs.anthropic.com/en/docs/claude-code](https://docs.anthropic.com/en/docs/claude-code)
  or your local `.claude/` settings for details)
* Timed-out tasks return non-zero exit code

**Failure Handling Patterns:**

* Check Task() return value to detect failures
* Log failures to `failures.log` with timestamp, task ID, and reason
* For non-critical tasks (refiners): skip and continue, report in summary
* For critical tasks (reviewer): exit immediately, cannot proceed without output

### Step 5: Refine Chunks (Parallel)

For each chunk, spawn a chunk-refiner agent. Run all refiners in parallel by
issuing multiple Task calls in a single response (Claude Code executes
concurrent Task calls simultaneously):

```bash
# Issue all Task calls in a single response block for parallel execution
# (see "Task Execution Model" section above for parallelism semantics)

# Track skipped refiners for summary reporting
skipped_refiners=()

for chunk_file in "$workspace_dir/chunks"/chunk_*.md; do
    chunk_name=$(basename "$chunk_file")

    # Each Task call returns success/failure - track failures
    # Note: Timeout is enforced externally by Claude Code Task tool
    if ! Task(
        subagent_type="prd-chunk-refiner",
        model="haiku",
        prompt="Refine this chunk by splitting and adding metadata.

chunk_file: $chunk_file
output_dir: $workspace_dir/refined/

Split into focused sub-chunks if needed. Add metadata sidecar files.
CRITICAL: Do not modify the original text - only split and annotate."
    ); then
        reason="Refiner agent failed or timed out"
        skipped_refiners+=("$chunk_name")
        echo "WARNING: Skipped refiner for $chunk_name: $reason" >&2
        echo "$(iso_timestamp) SKIPPED_REFINER $chunk_name \"$reason\"" >> "$workspace_dir/failures.log"
    fi
done
# Claude Code blocks until all parallel Task calls complete before proceeding

# Report skipped refiners if any
if [ ${#skipped_refiners[@]} -gt 0 ]; then
    echo "WARNING: ${#skipped_refiners[@]} refiner(s) skipped during" \
        "processing:" >&2
    for skipped in "${skipped_refiners[@]}"; do
        echo "  - $skipped" >&2
    done
    echo "Review $workspace_dir/failures.log for details." >&2
fi
```

### Step 6: Review for Violations

Run the violation-reviewer to compare synthesis against all refined chunks:

```bash
# Note: Timeout is enforced externally by Claude Code Task tool (see
# Step 5 comments). Reviewer failure causes script to exit since
# violations.json is required for patching.
if ! Task(
    subagent_type="prd-violation-reviewer",
    model="opus",
    prompt="Review synthesis against source chunks for violations.

synthesis_file: $synthesis_file
chunks_dir: $workspace_dir/refined/

Identify all constraint violations:
- Missing elements (resources, goals, rules not in synthesis)
- Incomplete elements (synthesis missing detail from source)
- Missing cross-references
- Misplaced elements
- Duplicate concepts

Write violations to: $workspace_dir/violations.json"
); then
    echo "ERROR: Violation reviewer agent failed or timed out" >&2
    echo "Cannot proceed without violations.json for patching." >&2
    echo "$(iso_timestamp) REVIEWER_FAILURE \"Agent failed or timed out\"" >> "$workspace_dir/failures.log"
    exit 1
fi

# Verify the expected artifact was produced
if [ ! -f "$workspace_dir/violations.json" ]; then
    echo "ERROR: Violation reviewer completed but did not produce" \
        "violations.json" >&2
    echo "Expected output at: $workspace_dir/violations.json" >&2
    echo "$(iso_timestamp) REVIEWER_FAILURE" \
        "\"No violations.json produced\"" >> "$workspace_dir/failures.log"
    exit 1
fi
```

### Step 7: Patch Violations (Sequential)

For each violation, spawn a patcher. Process sequentially to avoid conflicts:

```bash
# Validate violations.json exists and is valid JSON
if [ ! -f "$workspace_dir/violations.json" ]; then
    echo "ERROR: violations.json not found at $workspace_dir/violations.json" >&2
    echo "The violation-reviewer agent may have failed to complete." >&2
    exit 1
fi

# Validate JSON structure before reading content
if ! jq empty "$workspace_dir/violations.json" 2>/dev/null; then
    echo "ERROR: Invalid JSON in $workspace_dir/violations.json" >&2
    echo "First 1000 bytes of file content:" >&2
    head -c 1000 "$workspace_dir/violations.json" >&2
    echo "" >&2
    echo "First 20 non-empty lines:" >&2
    grep -v '^[[:space:]]*$' "$workspace_dir/violations.json" | \
        head -n 20 >&2
    exit 1
fi

violations=$(cat "$workspace_dir/violations.json") || {
    echo "ERROR: Failed to read $workspace_dir/violations.json" >&2
    exit 1
}

# Validate that .violations exists and is an array before computing length
violations_type=$(echo "$violations" | jq -r '.violations | type') || {
    echo "ERROR: Failed to parse JSON structure in" \
        "$workspace_dir/violations.json" >&2
    exit 1
}

if [ "$violations_type" != "array" ]; then
    echo "ERROR: Expected '.violations' to be an array but got:" \
        "$violations_type" >&2
    echo "Top-level keys:" \
        "$(echo "$violations" | jq -r 'keys | join(", ")')" >&2
    if [ "$violations_type" = "null" ]; then
        echo "Hint: The '.violations' key is missing or null." >&2
    fi
    exit 1
fi

violation_count=$(echo "$violations" | jq '.violations | length') || {
    echo "ERROR: Unexpected JSON structure in" \
        "$workspace_dir/violations.json" >&2
    echo "Expected '.violations' array but got different structure." >&2
    echo "Top-level keys:" \
        "$(echo "$violations" | jq -r 'keys | join(", ")')" >&2
    exit 1
}

# Handle zero violations case
if [ "$violation_count" -eq 0 ]; then
    echo "No violations reported by reviewer; synthesis unchanged" >&2
    echo "INFO: Reviewer completed successfully with no findings." >&2
    # Fall through to Step 8: summary output (no patches needed)
    # The patcher loop below (seq 0 to -1) will not execute any iterations.
fi

# Track patcher failures for summary reporting
patcher_failures=()

# Note: Timeout is enforced externally by Claude Code Task tool (see
# Step 5 comments). Patcher failures are logged but processing continues
# with remaining violations.
for i in $(seq 0 $((violation_count - 1))); do
    violation=$(echo "$violations" | jq ".violations[$i]")
    violation_id=$(echo "$violation" | jq -r '.id')

    if ! Task(
        subagent_type="prd-synthesis-patcher",
        model="opus",
        prompt="Resolve this violation using original source text.

synthesis_file: $synthesis_file
chunks_dir: $workspace_dir/refined/
violation: $violation

CRITICAL: Use the ORIGINAL text from the source chunk.
Do not paraphrase or 'improve' the wording.

Write resolution to: $workspace_dir/resolutions/${violation_id}.json"
    ); then
        reason="Patcher agent failed or timed out"
        patcher_failures+=("$violation_id")
        echo "WARNING: Patcher failed for violation $violation_id: $reason" >&2
        echo "$(iso_timestamp) PATCHER_FAILURE $violation_id \"$reason\"" >> "$workspace_dir/failures.log"
    fi
done

# Report patcher failures if any
if [ ${#patcher_failures[@]} -gt 0 ]; then
    echo "WARNING: ${#patcher_failures[@]} patcher(s) failed during" \
        "processing:" >&2
    for failed_id in "${patcher_failures[@]}"; do
        echo "  - $failed_id" >&2
    done
    echo "Review $workspace_dir/failures.log for details." >&2
fi
```

### Step 8: Output Summary

```bash
# Count violations by resolution (with directory existence check and JSON validation)
resolved=0
partial=0
skipped=0
unknown_status=0
malformed_resolutions=()

if [ -d "$workspace_dir/resolutions" ] && \
    ls "$workspace_dir/resolutions"/*.json >/dev/null 2>&1; then
    for res_file in "$workspace_dir/resolutions"/*.json; do
        # Validate JSON before processing
        if ! jq empty "$res_file" 2>/dev/null; then
            malformed_resolutions+=("$(basename "$res_file")")
            echo "WARNING: Malformed JSON in resolution file:" \
                "$res_file" >&2
            echo "$(iso_timestamp) MALFORMED_RESOLUTION" \
                "$(basename "$res_file")" >> \
                "$workspace_dir/failures.log"
            continue
        fi
        # Extract and normalize resolution_status (trim whitespace, lowercase)
        resolution_status=$(jq -r '.resolution // "unknown"' "$res_file" | \
            tr '[:upper:]' '[:lower:]' | xargs)
        case "$resolution_status" in
            resolved) ((resolved++)) ;;
            partial) ((partial++)) ;;
            skipped) ((skipped++)) ;;
            *)
                ((unknown_status++))
                echo "WARNING: Unexpected resolution_status" \
                    "'$resolution_status' in $(basename "$res_file")" >&2
                echo "$(iso_timestamp) UNKNOWN_STATUS $(basename "$res_file")" \
                    "\"$resolution_status\"" >> "$workspace_dir/failures.log"
                ;;
        esac
    done
fi

if [ ${#malformed_resolutions[@]} -gt 0 ]; then
    echo "WARNING: ${#malformed_resolutions[@]} malformed resolution" \
        "file(s) skipped: ${malformed_resolutions[*]}" >&2
fi

# Expected synthesis markup formats:
#   Resources:  - `RES-01`: Description
#   Goals:      - **GOAL-01**: Description  OR
#                 - *GOAL-01*: Description
#   Invariants: - **INV-01**: Description   OR
#                 - *INV-01*: Description
#   Rules:      - **EXEC-01**: Description  OR
#                 - **PROC-01**: Description  OR
#                 - **VAL-01**: Description
# List markers can be -, *, or +. Emphasis can be * or **.

# Validate synthesis file is readable before counting elements
if [ ! -r "$synthesis_file" ]; then
    echo "ERROR: Cannot read synthesis file: $synthesis_file" >&2
    exit 1
fi

# Count synthesis elements with proper grep error handling
# grep exit codes: 0=matches found, 1=no matches, 2+=error
count_grep() {
    local pattern="$1"
    local file="$2"
    local result
    result=$(grep -cE "$pattern" "$file" 2>&1)
    local exit_code=$?
    if [ $exit_code -eq 0 ]; then
        echo "$result"
    elif [ $exit_code -eq 1 ]; then
        echo 0
    else
        echo "ERROR: grep failed while counting pattern '$pattern'" \
            "in $file: $result" >&2
        exit 1
    fi
}

# Pattern: bullet marker (-, *, +), whitespace, backticked RES- ID
# Example match: "- `RES-01`: API documentation"
resource_count=$(count_grep '^[[:space:]]*[-*+][[:space:]]+`RES-' \
    "$synthesis_file")

# Pattern: bullet marker, whitespace, asterisks for emphasis, GOAL- ID
# Example: "- **GOAL-01**: Enable batch processing" or "- *GOAL-01*: ..."
goal_count=$(count_grep '^[[:space:]]*[-*+][[:space:]]+\*{1,2}GOAL-' \
    "$synthesis_file")

# Pattern: bullet marker, whitespace, asterisks, INV- ID
# Example: "- **INV-01**: All file operations must be atomic"
invariant_count=$(count_grep '^[[:space:]]*[-*+][[:space:]]+\*{1,2}INV-' \
    "$synthesis_file")

# Pattern: bullet marker, whitespace, emphasis, rule (EXEC/PROC/VAL)
# Example: "- **EXEC-01**: Files in order" or "- **PROC-02**: Log"
rule_count=$(count_grep \
    '^[[:space:]]*[-*+][[:space:]]+\*{1,2}(EXEC|PROC|VAL)-[0-9]+' \
    "$synthesis_file")

# Validate synthesis markup - fail if required patterns are missing
# Set SKIP_SYNTHESIS_VALIDATION=1 to allow non-blocking behavior for
# development/debugging
synthesis_validation_warnings=()
if [ "$resource_count" -eq 0 ]; then
    synthesis_validation_warnings+=("No Resources (RES-XX) found")
fi
if [ "$goal_count" -eq 0 ]; then
    synthesis_validation_warnings+=("No Goals (GOAL-XX) found")
fi
if [ "$invariant_count" -eq 0 ] && [ "$rule_count" -eq 0 ]; then
    synthesis_validation_warnings+=("No Invariants or Rules found")
fi

if [ ${#synthesis_validation_warnings[@]} -gt 0 ]; then
    echo "ERROR: Synthesis markup validation failed:" >&2
    for warn in "${synthesis_validation_warnings[@]}"; do
        echo "  - $warn" >&2
    done
    echo "  Expected formats: RES-XX in backticks," \
        "GOAL-XX/INV-XX/RULE-XX in emphasis (**/*)." >&2

    if [ "${SKIP_SYNTHESIS_VALIDATION:-0}" = "1" ]; then
        # Block bypass in production environments
        if [ "${NODE_ENV:-}" = "production" ] || \
           [ "${CI:-}" = "true" ] || \
           [ "${PRODUCTION:-}" = "1" ]; then
            echo "  ERROR: SKIP_SYNTHESIS_VALIDATION cannot be used in" \
                "production environments." >&2
            echo "  Detected production indicator: NODE_ENV=$NODE_ENV," \
                "CI=$CI, PRODUCTION=$PRODUCTION" >&2
            exit 1
        fi
        echo "" >&2
        echo "  ======================================================" >&2
        echo "  WARNING: DEVELOPMENT ONLY - DO NOT USE IN PRODUCTION" >&2
        echo "  ======================================================" >&2
        echo "  SKIP_SYNTHESIS_VALIDATION=1 is set; continuing despite" \
            "validation errors." >&2
        echo "  RISK: Invalid Resources/Goals/Rules may be shipped if" \
            "this runs in production." >&2
        echo "" >&2
    else
        echo "  To bypass validation (development only):" \
            "SKIP_SYNTHESIS_VALIDATION=1" >&2
        exit 1
    fi
fi
```

Count refined sub-chunks with proper pipeline error handling:

```bash
# Count refined sub-chunks with pipefail to catch pipeline failures
refined_count=0
if [ -d "$workspace_dir/refined" ]; then
    # Use a subshell with pipefail to detect failures in pipeline
    refined_count=$(
        set -o pipefail
        find "$workspace_dir/refined" -maxdepth 1 -type f -name "*.md" \
            2>/dev/null | wc -l
    ) || {
        echo "WARNING: Failed to count refined sub-chunks (pipeline error)" >&2
        echo "$(iso_timestamp) PIPELINE_ERROR refined_count" \
            "\"find | wc -l failed\"" >> "$workspace_dir/failures.log"
        refined_count="ERROR"
    }
fi
# Ensure refined_count is numeric (default to 0 if empty)
if [ "$refined_count" != "ERROR" ]; then
    refined_count=${refined_count:-0}
    if ! [[ "$refined_count" =~ ^[0-9]+$ ]]; then
        echo "WARNING: Non-numeric refined count '$refined_count'," \
            "defaulting to 0" >&2
        refined_count=0
    fi
fi
```

Print summary (to stdout):

```text
================================================================================
PRD SYNTHESIS UPDATE COMPLETE
================================================================================
Synthesis File: $synthesis_file
Input: $input_type ($input_file)
Workspace: $workspace_dir

Processing Pipeline:
  Raw chunks: $chunk_count
  Refined sub-chunks: $refined_count
  Skipped refiners: ${#skipped_refiners[@]}
  Violations found: $violation_count

Resolution Summary:
  Resolved: $resolved
  Partial: $partial
  Skipped: $skipped
  Unknown status: $unknown_status
  Patcher failures: ${#patcher_failures[@]}
  Malformed resolutions: ${#malformed_resolutions[@]}

Synthesis Statistics:
  Resources: $resource_count
  Goals: $goal_count
  Invariants: $invariant_count
  Rules: $rule_count

================================================================================
REVIEW ITEMS
================================================================================

1. Placeholder IDs (search for -XX):
   grep -n -- '-XX' "$synthesis_file"

2. Partial resolutions needing review:
   find "$workspace_dir/resolutions" -maxdepth 1 -name '*.json' -print0 \
       2>/dev/null | xargs -0 grep -l '"resolution": "partial"' 2>/dev/null \
       || echo "  (none)"

3. Items needing manual ID assignment:
   grep -En 'RES-XX|GOAL-XX|INV-XX' "$synthesis_file"

4. Processing failures (if any):
   cat $workspace_dir/failures.log

================================================================================
NEXT STEPS
================================================================================

1. Review and assign placeholder IDs (RES-XX → RES-05, etc.)

2. Check partial resolutions for conflicts

3. Review $workspace_dir/failures.log for any skipped refiners or patcher failures

4. Rerun to catch any missed violations:
   /update-prd "$synthesis_file" <original-input-file>
   (Use the original input file path you provided, not the workspace copy.
    If you used inline text, provide it again or save it to a file first.)

5. Clean up workspace when satisfied (see Operational Guidance below):
   rm -rf $workspace_dir

================================================================================
```

### Workspace Cleanup Operational Guidance

**Recommended Cleanup Timing:**

* **On success**: Clean up immediately after verifying synthesis output
* **On failure**: Retain workspace for debugging; archive artifacts if needed
  before deletion

**Estimating Disk Usage:**

Workspace disk usage depends on:
* Chunk count (typically 10-50 chunks per input file)
* Average chunk size (typically 1-5 KB per chunk)
* Resolution files (typically 0.5-2 KB per violation)

To estimate current usage:

```bash
du -sh "$workspace_dir"
du -sh "$workspace_dir/chunks" "$workspace_dir/refined" "$workspace_dir/resolutions"
```

**Archiving Failed Runs:**

Before deleting a failed run, consider archiving for debugging:

```bash
# Archive workspace for later analysis
tar -czf "prd-debug-$(date +%Y%m%d_%H%M%S).tar.gz" "$workspace_dir"

# Or selectively archive key artifacts
cp "$workspace_dir/failures.log" ./prd-failures-$(date +%Y%m%d).log
cp "$workspace_dir/violations.json" ./prd-violations-$(date +%Y%m%d).json
```

**CI-Safe Practices:**

For automated/CI environments:
* Set `PRD_WORKSPACE_RETENTION_HOURS` env var to control retention period
  (default: 0 = immediate cleanup on success)
* Gate deletion on success status - only auto-delete when exit code is 0
* Consider a dry-run/confirm flag for manual runs:

  ```bash
  if [ "${PRD_DRY_RUN:-0}" = "1" ]; then
      echo "DRY RUN: Would delete $workspace_dir" >&2
  else
      rm -rf "$workspace_dir"
  fi
  ```

* Enforce disk quota monitoring in CI pipelines:

  ```bash
  # Fail if .tmp/prd exceeds 500MB
  prd_size=$(du -sm .tmp/prd 2>/dev/null | cut -f1)
  if [ "${prd_size:-0}" -gt 500 ]; then
      echo "ERROR: PRD workspace exceeds 500MB quota" >&2
      exit 1
  fi
  ```

If any skipped refiners exist, append a final warning line (to stderr):

```bash
if [ ${#skipped_refiners[@]} -gt 0 ]; then
    echo "" >&2
    echo "WARNING: Synthesis may be incomplete -" \
        "${#skipped_refiners[@]} refiner(s) were skipped." >&2
    echo "Skipped chunk IDs: ${skipped_refiners[*]}" >&2
    echo "Review failures.log and consider rerunning after" \
        "investigating." >&2
fi
```

## Agent Roles

| Agent | Model | Role | Modifies Source? |
|-------|-------|------|------------------|
| chunk-refiner | haiku | Split + annotate | NO (sidecar only) |
| violation-reviewer | opus | Identify problems | NO (read only) |
| synthesis-patcher | opus | Apply patches | YES (uses original text) |

**Source text is NEVER rewritten until the patcher**:

1. **Chunker** → Splits file, no text modification
2. **Refiner** → Adds `.meta.json` sidecar, `.md` is byte-identical to source portion
3. **Reviewer** → Reads and compares, produces violation report
4. **Patcher** → First point where source is transformed into PRD format

This allows:
* Multiple reruns with same source
* Debugging by inspecting intermediate files
* Auditing that synthesis matches source

## Idempotency

The workflow is designed to be re-runnable:

* First run: Many violations found and resolved
* Second run: Fewer violations (resolved ones don't reappear)
* Nth run: Zero violations (synthesis complete)

**Note**: Idempotency only holds if all violations are fully resolved.
Violations marked as "partial" or "skipped" may reappear on subsequent runs
and require manual review before synthesis is considered complete.

If source changes, new violations will be detected on next run.

**Detection**: To verify synthesis is in sync, compare violation counts across
two consecutive runs:

* If counts remain stable (ideally zero), synthesis is stable and complete
* If counts increase, the source likely changed or prior resolutions were
  incomplete and require further review

## Error Handling

All errors and warnings are written to stderr and appended to
`$workspace_dir/failures.log`. Success messages and the final summary are
written to stdout.

| Error | Handling | Logged To |
|-------|----------|-----------|
| Chunker fails | Report error to stderr, exit | stderr only |
| Refiner fails | Skip chunk, log ID, reason, timestamp | stderr + failures.log |
| Reviewer fails | Report error to stderr, exit | stderr only |
| Patcher fails | Log violation ID, reason, timestamp | stderr + failures.log |
| Malformed JSON | Log file name, skip from counts | stderr + failures.log |
| Synthesis corrupted | User restores from git | N/A |

### Failure Log Format

The `$workspace_dir/failures.log` file records processing failures with the
following format:

```text
<ISO-8601-timestamp> <ERROR_TYPE> <ID> [reason]
```

Examples:

```text
2024-01-15T10:30:45Z SKIPPED_REFINER chunk_003.md \
    "Empty chunk after split"
2024-01-15T10:31:12Z PATCHER_FAILURE VIO-007 \
    "Conflict with existing element"
2024-01-15T10:31:45Z MALFORMED_RESOLUTION VIO-012.json
```

### Skipped Refiner Tracking

When chunk refiners are skipped, their IDs are tracked and reported in the
final summary. If any refiners were skipped, a warning is displayed:

```text
WARNING: 2 refiner(s) skipped during processing:
  - chunk_003.md: Empty chunk after split
  - chunk_007.md: Timeout exceeded
Review $workspace_dir/failures.log for details.
```

This ensures synthesis completeness is visible at a glance.
