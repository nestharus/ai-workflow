---
description: Update implementation design from inline comments or PR feedback
argument-hint: "<ticket-id> [update prompt...]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# Update Implementation Plan

Update the design for ticket based on inline comments or PR feedback.

**Arguments**: First token is ticket ID, rest is the update prompt (optional).

Examples:
```bash
/update-plan NES-123 "Change the extractor to handle null values"
/update-plan NES-123 "Split the validator into separate input and output validators"
/update-plan NES-123   # No prompt → fetch unresolved PR comments
```

## Step 1: Parse Arguments

```bash
# First token is ticket ID
ticket_id=$(echo "$ARGUMENTS" | awk '{print $1}')

# Rest is update prompt (may be empty)
update_prompt=$(echo "$ARGUMENTS" | cut -d' ' -f2-)
```

## Step 2: Initialize

```bash
uv run planner init $ticket_id --workflow update-plan
```

If `update_prompt` is empty, fetch PR comments:
```bash
uv run pr list-unresolved-comments $ticket_id
```

The state machine:
- Loads existing design from workspace or fetches "Implementation Design" from Linear
- Parses update prompt(s) into structured comments
- Groups comments by target layer
- Starts at deepest affected layer (bottom-up processing)

## Step 3: Execute State Machine Loop

```bash
while true; do
    action=$(uv run planner next .tmp/design/$ticket_id)
    action_type=$(echo "$action" | jq -r '.action')

    case "$action_type" in
        "complete") break ;;
        "error") echo "Error: $(echo "$action" | jq -r '.message')"; exit 1 ;;

        "call_comment_applier")
            Task(subagent_type="comment-applier", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "call_layer_reviewer")
            Task(subagent_type="layer-reviewer", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "call_design_refactorer")
            Task(subagent_type="design-refactorer", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "generate_docs")
            Task(subagent_type="diagram-generator", prompt="workspace: .tmp/design/$ticket_id")
            Task(subagent_type="design-formatter", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "post_to_linear")
            uv run linear upsert-comment $ticket_id --title "Architecture Design" --body-file .tmp/design/$ticket_id/architecture.md
            uv run linear upsert-comment $ticket_id --title "Implementation Design" --body-file .tmp/design/$ticket_id/implementation.md
            ;;
    esac

    uv run planner process .tmp/design/$ticket_id
done
```

## Step 4: Output

```bash
uv run planner status .tmp/design/$ticket_id
```

Print:
```
================================================================================
PLAN UPDATE COMPLETE - REVIEW REQUESTED
================================================================================
Ticket: $ticket_id - <TITLE>
Linear: <LINEAR_TICKET_URL>

Update Source:
  <INLINE_PROMPT or "PR comments (N unresolved)">

Changes Applied:
  Units modified: <count>
  Units added: <count>
  Units removed: <count>
  Pattern changes: <count>

Layers Affected:
  Layer 3: <count> changes
  Layer 2: <count> changes
  Layer 1: <count> changes

================================================================================
LINEAR COMMENTS UPDATED
================================================================================

The following comments on the Linear ticket were updated:

1. "Architecture Design"
   - PURPOSE: Human-readable overview with Mermaid diagrams
   - STATUS: Updated to reflect changes from this update
   - FETCH: uv run linear get-comment $ticket_id --title "Architecture Design"

2. "Implementation Design"
   - PURPOSE: Machine-readable unit tree with detailed plans
   - STATUS: Updated with applied changes
   - FETCH: uv run linear get-comment $ticket_id --title "Implementation Design"

================================================================================
REVIEW INSTRUCTIONS
================================================================================

Fetch and review the updated design:
  uv run linear get-comment $ticket_id --title "Architecture Design"
  uv run linear get-comment $ticket_id --title "Implementation Design"

VERIFY THE UPDATE WAS APPLIED CORRECTLY:
1. The update prompt was addressed:
   "$update_prompt"

2. Check affected units have appropriate changes
3. Pattern changes (if any) are justified
4. Bubble-up effects handled (child changes → parent updates)

BUBBLE-UP REVIEW:
- Changes at Layer N may affect Layer N-1, N-2, etc.
- Verify parent units updated when children changed
- Check that composition wiring still makes sense

YOU ARE REVIEWING THE UPDATED DESIGN.
Verify the update prompt was incorporated correctly.

Next: /execute-plan $ticket_id
State: .tmp/design/$ticket_id/
================================================================================
```

## Bottom-Up Processing

When an update affects a specific unit, changes may bubble up:

```
Update: "extract_user should handle None"
Target: root.services.user.extract (Layer 3)

Layer 3: Apply update → patch plan adds null check
Layer 2: Review → parent may need updated description
Layer 1: Review → composition may need null handling
Layer 0: Review → root description may update
```

The state machine processes from the deepest affected layer upward, so each parent sees the finalized state of its children before being reviewed.

## Notes

- Inline prompt: directly applied to design
- No prompt: fetches unresolved PR comments
- Bottom-up: deepest affected layer first
- Each layer reviewed after changes applied
