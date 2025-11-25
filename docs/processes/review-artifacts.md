# Review Artifact Handling

Review tool outputs are stored in a standardized format for agent retrieval and audit
purposes.

## Storage Location

All review tool outputs are stored under the `.review/` directory in the repository root.

## Naming Convention

Files use UTC timestamps in the format `<YYYYMMDDTHHMMSSZ>`:

* **CodeRabbit**: `.review/<timestamp>.review.coderabbit`
* **SonarQube**: `.review/<timestamp>.review.sonar`

## Follow-up Questions

Record any follow-up questions for humans in `.review/review-questions-<timestamp>.txt`
directly after running reviews. This ensures questions are captured alongside the review
output.

## Exclusions

Keep review artifacts excluded from:

* **Scans**: Configured in `.checkov.yaml` and other scan configurations
* **VCS**: Listed in `.gitignore` to prevent committing review outputs

## Agent Retrieval

Agents retrieve the latest review artifact using:

```bash
# Get latest CodeRabbit review
uv run latest-review --type coderabbit

# Get latest SonarQube review
uv run latest-review --type sonar
```

These commands print the path to the newest review file of the specified type.
