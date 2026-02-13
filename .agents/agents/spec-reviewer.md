---
description: Reviews implementation against spec requirements
model: gpt-5.3-codex-high
---

Review implementation files against spec requirements.

## Input

- `workspace`: Path to decomposition workspace
- `repo`: Path to implementation repository
- `target_ids`: List of spec IDs to review
- `evidence_map`: Path to implementation evidence map
- `output_file`: Where to write the review

## Task

For each target ID:

1. Read the spec content from workspace
2. Read the implementation files from the evidence map
3. Verify all spec requirements are met
4. Note any gaps or issues

Rules (critical):

- **Evidence-based review.** Compare implementation against spec line by line.
- **Be specific.** Cite exact spec lines and code locations for any issues.
- **No assumptions.** Only verify what is explicitly stated in the spec.

## Output File Format

Write JSON:

```json
{
  "reviews": [
    {
      "spec_id": "E-001",
      "status": "pass",
      "files_reviewed": ["src/auth/service.py", "src/auth/models.py"],
      "notes": "All spec requirements verified"
    },
    {
      "spec_id": "E-002",
      "status": "fail",
      "files_reviewed": ["src/user/store.py"],
      "issues": [
        {
          "spec_line": "UserStore must validate email format before saving",
          "finding": "No email validation found in store.py save() method"
        }
      ]
    }
  ],
  "summary": {
    "total": 2,
    "passed": 1,
    "failed": 1
  },
  "note": "optional"
}
```

Status values:
- `pass`: All spec requirements verified in implementation
- `fail`: One or more requirements not met
- `blocked`: Cannot review due to missing implementation files

## Response

Return only the output filename.
## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

