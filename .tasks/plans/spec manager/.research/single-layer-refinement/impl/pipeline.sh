#!/usr/bin/env bash
set -uo pipefail

# Single-layer refactoring pipeline
# Processes files 3-33 sequentially through:
#   1. codex-high   — expand/plan (no code, only IMPL notes)
#   2. codex-spark   — write code
#   3. pytest        — run tests
#   4. codex-high   — debug failures (if any)
#   5. ruff          — lint fix
#   6. git           — commit + push

REPO_ROOT="/mnt/c/Users/xteam/IdeaProjects/ai-workflow"
SM_ROOT="$REPO_ROOT/scripts/spec_manager/spec_manager"
PROPOSAL="$REPO_ROOT/.tasks/plans/spec manager/.research/single-layer-refinement/proposal.md"
IMPL_DIR="$REPO_ROOT/.tasks/plans/spec manager/.research/single-layer-refinement/impl"
LOG_DIR="$IMPL_DIR/logs"
PROMPT_DIR="$IMPL_DIR/prompts"

mkdir -p "$LOG_DIR" "$PROMPT_DIR"

# Alternate codex-high models for quota distribution
CODEX_MODELS=("gpt-5.3-codex-high" "gpt-5.3-codex-high2")
CODEX_CODE="gpt-5.3-codex-high2"

# Files in dependency order (1=config.py, 2=run_state.py already done)
FILES=(
  "routing/shapes.py"
  "routing/matcher.py"
  "routing/verifiers.py"
  "routing/__init__.py"
  "compliance/promotion/__init__.py"
  "compliance/promotion/algorithmic_gates.py"
  "compliance/promotion/architectural_quality.py"
  "compliance/promotion/introduction_checker.py"
  "compliance/promotion/provenance.py"
  "compliance/promotion/orchestrator.py"
  "orchestration/pattern_library.py"
  "orchestration/coordination/work_items.py"
  "orchestration/coordination/monitors.py"
  "orchestration/coordination/monitor_executor.py"
  "projection/lineage/builder.py"
  "orchestration/demotion/__init__.py"
  "orchestration/demotion/router.py"
  "orchestration/demotion/triage.py"
  "orchestration/review/findings_to_tickets.py"
  "orchestration/implementation/runner.py"
  "orchestration/promotion_loop.py"
  "orchestration/pdd_lifecycle.py"
  "orchestration/pdd_orchestrator.py"
  "planner/api.py"
  "planner/router.py"
  "planner/layers/l1.py"
  "planner/layers/l2.py"
  "planner/layers/l3.py"
  "planner/strategies/architecture_strategy.py"
  "refinement/evals/metrics.py"
  "refinement/evals/runner.py"
)

# Optional: start from a specific file number (pass as $1)
START_FROM=${1:-3}

# Abort after this many consecutive failures
MAX_CONSECUTIVE_FAILURES=${2:-3}

pick_model() { echo "${CODEX_MODELS[$(($1 % ${#CODEX_MODELS[@]}))]}" ; }

log() { echo "$(date +%H:%M:%S) $*" ; }

TOTAL=${#FILES[@]}
PASSED=0
FAILED=0
SKIPPED=0
CONSECUTIVE_FAILURES=0
START_TIME=$SECONDS

# ---- BASELINE: Capture pre-existing test failures ----
BASELINE_LOG="$LOG_DIR/baseline-failures.log"
if [ ! -f "$BASELINE_LOG" ] || [ "$START_FROM" -eq 3 ]; then
  log "Capturing baseline test failures..."
  uv run pytest scripts/spec_manager/tests/unit/ \
    -v -p no:randomly \
    --ignore=scripts/spec_manager/tests/component/ \
    --tb=no -q \
    > "$BASELINE_LOG" 2>&1 || true

  # Extract just the FAILED test IDs for comparison
  grep "^FAILED " "$BASELINE_LOG" | sed 's/^FAILED //' | sort \
    > "$LOG_DIR/baseline-failed-ids.txt"

  BASELINE_COUNT=$(grep -c "^" "$LOG_DIR/baseline-failed-ids.txt" 2>/dev/null || echo "0")
  log "Baseline: $BASELINE_COUNT pre-existing failures captured"
else
  BASELINE_COUNT=$(grep -c "^" "$LOG_DIR/baseline-failed-ids.txt" 2>/dev/null || echo "0")
  log "Using existing baseline ($BASELINE_COUNT pre-existing failures)"
fi

# ---- BASELINE: Capture initial test count ----
INITIAL_TEST_COUNT=$(grep -oP '\d+(?= passed)' "$BASELINE_LOG" 2>/dev/null || echo "0")
log "Baseline test count: $INITIAL_TEST_COUNT passed"

for i in "${!FILES[@]}"; do
  FILE="${FILES[$i]}"
  N=$((i + 3))  # file number in the 33-file sequence

  # Skip already-done files
  if [ "$N" -lt "$START_FROM" ]; then
    ((SKIPPED++))
    continue
  fi

  # Abort on too many consecutive failures
  if [ "$CONSECUTIVE_FAILURES" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
    log "ABORT: $CONSECUTIVE_FAILURES consecutive failures — stopping pipeline"
    log "  Resume from file $N with: bash pipeline.sh $N"
    break
  fi

  FULL="$SM_ROOT/$FILE"
  BASE=$(basename "$FILE" .py)
  # Derive python module path for imports
  MOD=$(echo "$FILE" | sed 's|/|.|g; s|\.py$||; s|\.__init__$||')
  HIGH=$(pick_model "$i")
  TS="$LOG_DIR/.ts-$N"

  log "========================================="
  log "[$N/33] $FILE"
  log "  expand=$HIGH  code=$CODEX_CODE"
  log "========================================="

  # Timestamp marker — anything modified after this is from this iteration
  touch "$TS"
  sleep 1  # ensure filesystem timestamp granularity

  # ---- STEP 1: EXPAND (codex-high, notes only) ----
  EXPAND="$PROMPT_DIR/${N}-expand.md"
  cat > "$EXPAND" <<EOF
# Expansion: $FILE (File $N of 33)

You are a **planner**. You read code, analyze dependencies, and write
planning notes. You do **NOT** write or modify source code.

## Target
\`$FULL\`

## Steps

1. **Read the target file** — focus on the \`ALGORITHM(single-layer)\` block.
2. **Read the authoritative design**:
   \`$PROPOSAL\`
   Focus on sections referenced in the ALGORITHM block.
3. **Find existing IMPL notes** from already-implemented files:
   \`\`\`
   rg "IMPL\\(single-layer\\)" $SM_ROOT --type py -C2
   \`\`\`
4. **Find all consumers** of this module:
   \`\`\`
   rg "from spec_manager\\.$MOD" $SM_ROOT --type py -l
   \`\`\`
5. **Add \`IMPL(single-layer)\` notes** to the target file at key
   integration points so downstream implementors know what changed.
   Format: \`# IMPL(single-layer): <description>\`
6. **Cross-file notes**: if decisions here affect OTHER files'
   TODO/ALGORITHM blocks, update those blocks with a note.
7. Do **NOT** write source code. Only add/update comment notes.
8. Do **NOT** remove \`ALGORITHM\` or \`TODO\` blocks.
EOF

  log "  [1/6] Expanding..."
  if ! uv run agents --model "$HIGH" --file "$EXPAND" \
       > "$LOG_DIR/${N}-expand.log" 2>&1; then
    log "  WARN: expand failed (continuing)"
  fi

  # ---- VERIFY: IMPL notes were written ----
  IMPL_COUNT=$(grep -c "IMPL(single-layer)" "$FULL" 2>/dev/null || echo "0")
  if [ "$IMPL_COUNT" -eq 0 ]; then
    log "  WARN: No IMPL(single-layer) notes found in $FILE after expand"
    log "  (expand may have failed to write notes — check ${N}-expand.log)"
  else
    log "  OK: $IMPL_COUNT IMPL notes in target file"
  fi

  # ---- STEP 2: CODE (codex-spark, write code) ----
  CODE="$PROMPT_DIR/${N}-code.md"
  cat > "$CODE" <<EOF
# Implement: $FILE (File $N of 33)

You are a **code implementor**. Write production source code.

## Target
\`$FULL\`

## Steps

1. **Read the target file** — it has \`ALGORITHM(single-layer)\` and
   \`IMPL(single-layer)\` blocks describing what to build.
2. **Find IMPL notes** from dependency files:
   \`\`\`
   rg "IMPL\\(single-layer\\)" $SM_ROOT --type py -C2
   \`\`\`
3. **Implement** the changes described in the ALGORITHM block.
4. **Keep** any \`IMPL(single-layer)\` comment notes at integration points.
5. **Do NOT remove** \`ALGORITHM\` or \`TODO\` comment blocks.
6. **Do NOT modify** any other source files — only the target.
7. Import \`PhaseId\` from \`spec_manager.compliance.promotion.config\`.
8. No backwards-compatibility shims. No extra docstrings on unchanged code.
EOF

  log "  [2/6] Coding..."
  if ! uv run agents --model "$CODEX_CODE" --file "$CODE" \
       > "$LOG_DIR/${N}-code.log" 2>&1; then
    log "  WARN: code step failed (continuing)"
  fi

  # ---- STEP 3: TEST ----
  log "  [3/6] Testing..."
  TEST_LOG="$LOG_DIR/${N}-test.log"
  NEED_DEBUG=false

  # Import check
  if ! uv run python -c "import spec_manager.$MOD" 2>"$LOG_DIR/${N}-import.log"; then
    log "  FAIL: import spec_manager.$MOD"
    NEED_DEBUG=true
  fi

  # Targeted tests (by basename keyword)
  uv run pytest scripts/spec_manager/tests/unit/ \
    -x -v -p no:randomly -k "$BASE" \
    --ignore=scripts/spec_manager/tests/component/ \
    > "$TEST_LOG" 2>&1 || true

  TLINE=$(tail -1 "$TEST_LOG")
  log "  $TLINE"

  # Check for NEW failures (not pre-existing)
  if grep -q "FAILED\|ERROR" "$TEST_LOG"; then
    # Extract failed test IDs from this run
    grep "^FAILED " "$TEST_LOG" | sed 's/^FAILED //' | sort \
      > "$LOG_DIR/${N}-failed-ids.txt"

    # Subtract baseline failures to find NEW ones
    NEW_FAILURES=$(comm -23 "$LOG_DIR/${N}-failed-ids.txt" \
      "$LOG_DIR/baseline-failed-ids.txt" 2>/dev/null | wc -l)

    if [ "$NEW_FAILURES" -gt 0 ]; then
      log "  $NEW_FAILURES NEW failure(s) detected (not pre-existing)"
      NEED_DEBUG=true
    else
      log "  All failures are pre-existing — skipping debug"
    fi
  fi

  # ---- STEP 4: DEBUG (if needed) ----
  if [ "$NEED_DEBUG" = true ]; then
    log "  [4/6] Debugging..."
    DEBUG="$PROMPT_DIR/${N}-debug.md"
    cat > "$DEBUG" <<EOF
# Debug: $FILE (File $N of 33)

## Target
\`$FULL\`

## Failures
\`\`\`
$(cat "$LOG_DIR/${N}-import.log" 2>/dev/null)
$(tail -80 "$TEST_LOG")
\`\`\`

## Steps
1. Read the target file and any failing test files.
2. Identify root cause of each failure.
3. Fix the code or tests. Only modify the target file and its tests.
4. No backwards-compatibility shims.
EOF

    if ! uv run agents --model "$HIGH" --file "$DEBUG" \
         > "$LOG_DIR/${N}-debug.log" 2>&1; then
      log "  WARN: debug step failed"
    fi

    # Re-test after debug
    uv run pytest scripts/spec_manager/tests/unit/ \
      -x -v -p no:randomly -k "$BASE" \
      --ignore=scripts/spec_manager/tests/component/ \
      > "$LOG_DIR/${N}-test2.log" 2>&1 || true
    log "  Post-debug: $(tail -1 "$LOG_DIR/${N}-test2.log")"

    # Check if NEW failures still exist after debug
    if grep -q "FAILED\|ERROR" "$LOG_DIR/${N}-test2.log"; then
      grep "^FAILED " "$LOG_DIR/${N}-test2.log" | sed 's/^FAILED //' | sort \
        > "$LOG_DIR/${N}-failed-ids2.txt"
      STILL_NEW=$(comm -23 "$LOG_DIR/${N}-failed-ids2.txt" \
        "$LOG_DIR/baseline-failed-ids.txt" 2>/dev/null | wc -l)
      if [ "$STILL_NEW" -gt 0 ]; then
        log "  WARN: $STILL_NEW NEW failure(s) persist after debug"
      fi
    fi
  else
    log "  [4/6] Skipping debug (OK)"
  fi

  # ---- STEP 5: LINT ----
  log "  [5/6] Linting..."
  uv run ruff check "$FULL" --fix > "$LOG_DIR/${N}-lint.log" 2>&1 || true

  # ---- STEP 6: COMMIT + PUSH ----
  log "  [6/6] Committing..."
  cd "$REPO_ROOT"

  # Add files modified during this iteration (after timestamp marker)
  find "$SM_ROOT" scripts/spec_manager/tests/ \
    -name "*.py" -newer "$TS" 2>/dev/null | while read -r f; do
    git add "$f"
  done
  # Always add the target file
  git add "$FULL" 2>/dev/null || true

  if git diff --cached --quiet; then
    log "  Nothing to commit"
    ((SKIPPED++))
  else
    git diff --cached --stat | tail -3
    if git commit -m "refactor($BASE): implement single-layer model"; then
      git push && log "  Pushed" || log "  Push failed"
      ((PASSED++))
      CONSECUTIVE_FAILURES=0  # reset on success
    else
      log "  Commit failed"
      ((FAILED++))
      ((CONSECUTIVE_FAILURES++))
    fi
  fi

  # ---- TEST COUNT TRACKING ----
  CURRENT_TEST_COUNT=$(uv run pytest scripts/spec_manager/tests/unit/ \
    --co -q -p no:randomly \
    --ignore=scripts/spec_manager/tests/component/ 2>/dev/null \
    | tail -1 | grep -oP '\d+(?= test)' || echo "?")
  log "  Test count: $CURRENT_TEST_COUNT (baseline: $INITIAL_TEST_COUNT)"

  rm -f "$TS"
  log "  DONE [$N/33] elapsed=$((SECONDS - START_TIME))s"
  echo ""
done

# ---- SUMMARY ----
ELAPSED=$((SECONDS - START_TIME))
log "========================================="
log "PIPELINE COMPLETE"
log "  Passed: $PASSED  Failed: $FAILED  Skipped: $SKIPPED"
log "  Total time: ${ELAPSED}s ($((ELAPSED / 60))m)"
log "  Logs: $LOG_DIR"
log "========================================="
