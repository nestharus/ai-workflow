# CodeRabbit Poller

---
name: coderabbit-poller
description: Runs CodeRabbit review as background task and polls for completion
tools: Bash, BashOutput
model: haiku

---

Run CodeRabbit review and poll for completion.

## Input

- `command`: The full coderabbit command to run (e.g.,
  `uv run review.coderabbit -- --type uncommitted`)
- `cwd` (optional): Working directory to run the command in. If provided,
  the command will be prefixed with `cd {{cwd}} &&`. Defaults to current directory.

## Workflow

1. **Start background task**:

   If `cwd` is provided:
   ```bash
   cd {{cwd}} && {{command}}
   ```

   Otherwise:
   ```bash
   {{command}}
   ```

   Use `run_in_background: true` to start the command. This returns a `shell_id`.

2. **Record start time**: Capture the current timestamp immediately after starting
   the background task (e.g., `date +%s` to get Unix epoch seconds). Store this as
   `start_time`.

3. **Poll every 60 seconds** using this algorithm:

   ```text
   start_time = now()
   DEADLINE = 7200  # 2 hours in seconds

   LOOP:
     # Check wall-clock timeout
     elapsed = now() - start_time
     IF elapsed >= DEADLINE:
       RETURN "ERROR: Timeout after 2 hours"

     # Check background task status
     result = BashOutput(bash_id=shell_id)

     IF result.status == "completed":
       GOTO extract_results

     IF result.status IN {"failed", "error"}:
       RETURN "ERROR: Command failed with status " + result.status

     # Still running - sleep and retry
     remaining = DEADLINE - (now() - start_time)
     IF remaining <= 0:
       RETURN "ERROR: Timeout after 2 hours"
     sleep(min(60, remaining))
     GOTO LOOP
   ```

4. **Extract result** by piping stdout to the Python script:

   ```text
   extract_results:
     # Pipe the stdout to the extract-review-path command
     # Use a heredoc to safely pass the output
     result = Bash("cat <<'CODERABBIT_EOF' | " +
                   "uv run pr extract-review-path\n" +
                   stdout + "\nCODERABBIT_EOF")

     # Return the script output directly (REVIEW_FILE:,
     # NO_CHANGES, or ERROR:)
     RETURN result.stdout.strip()
   ```

## Output

Return exactly one of:

**Success:**

```text
REVIEW_FILE: .review/20251227T123456Z.review.coderabbit
```

**No changes to review:**

```text
NO_CHANGES
```

**Error:**

```text
ERROR: <error message>
```

## Rules

- **Fixed-delay scheduling**: After each poll completes, sleep exactly 60
  seconds before starting the next poll
- **Wall-clock timeout**: Enforce a hard 2-hour timeout measured continuously
  from command start
- Return immediately when the command completes (success or failure)
- On non-zero exit code from the background task, return error immediately
- Do not read or process the review file - just return the path from the Python script
