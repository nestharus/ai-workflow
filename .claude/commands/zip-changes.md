# Zip Changed Files

> **Metadata:** Description: Create a zip archive of all changed repository files. Allowed tools: Bash

Create a zip archive containing all newly created or modified files (staged, unstaged, and untracked) that could go into a commit. The zip file is stored in `.tmp/` with a unique filename and maintains the proper folder structure.

## Arguments

* `--root <path>`: Root path for git operations and relative file paths (default: current directory)
* `--output-dir <path>`: Output directory for the zip file (default: .tmp/)

## Workflow

### Step 1: Run the repo zip-changes command

```bash
uv run repo zip-changes [--root <path>] [--output-dir <path>]
```

### Step 2: Report the result

The command outputs the full path to the created zip file. Inform the user of:

1. The full path to the zip file
2. The number of files included in the archive
3. Any errors that occurred (exit code 1 means no files found or git error)

## Example

```bash
uv run repo zip-changes
```

Output example:
```
/tmp/ai-workflow/.tmp/changes_20250125_143052_a3f7b2c8.zip
```

## Notes

* The zip file is created with a unique name using timestamp and random suffix
* Deleted files are automatically excluded from the archive
* The `.tmp/` directory is created automatically if it doesn't exist
