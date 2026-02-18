"""Task queue system for serial ChatGPT interactions via folder-based IO.

Queue directory structure:
    queue_dir/
        task-001/
            task.yaml       # Task config (required)
            prompt.md       # Prompt text (required)
            attachment.zip  # Optional file to upload
            response.md     # Written after completion
            status.yaml     # Written/updated during processing
        task-002/
            ...

task.yaml format:
    name: "Research authentication patterns"
    model: "GPT 5.2 Pro"           # reminder only (must be pre-selected)
    extended_thinking: true         # reminder only (must be pre-selected)
    new_chat: true                  # start a new chat (default: true)
    poll_interval: 15               # seconds between idle checks
    prompt_file: "prompt.md"        # relative to task dir (default: prompt.md)
    attachment_file: "context.zip"  # relative to task dir (optional)
    output_file: "response.md"     # relative to task dir (default: response.md)

status.yaml format (written by queue processor):
    status: pending | running | completed | failed
    started_at: "2026-02-18T12:00:00"
    completed_at: "2026-02-18T12:05:00"
    elapsed_seconds: 300
    response_chars: 15234
    error: null
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .detect import auto_calibrate
from .sender import extract_response, is_idle, send_prompt, wait_for_response


def _load_task(task_dir: Path) -> dict:
    """Load and validate a task config from a directory."""
    task_file = task_dir / "task.yaml"
    if not task_file.exists():
        raise FileNotFoundError(f"No task.yaml in {task_dir}")

    with open(task_file) as f:
        task = yaml.safe_load(f) or {}

    # Defaults
    task.setdefault("name", task_dir.name)
    task.setdefault("new_chat", True)
    task.setdefault("poll_interval", 15)
    task.setdefault("prompt_file", "prompt.md")
    task.setdefault("output_file", "response.md")

    # Resolve paths relative to task dir
    prompt_path = task_dir / task["prompt_file"]
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    task["_prompt_path"] = prompt_path
    task["_prompt_text"] = prompt_path.read_text()

    attachment_file = task.get("attachment_file")
    if attachment_file:
        attachment_path = task_dir / attachment_file
        if not attachment_path.exists():
            raise FileNotFoundError(f"Attachment not found: {attachment_path}")
        task["_attachment_path"] = attachment_path
    else:
        task["_attachment_path"] = None

    task["_output_path"] = task_dir / task["output_file"]
    task["_status_path"] = task_dir / "status.yaml"
    task["_dir"] = task_dir

    return task


def _write_status(task: dict, status: str, **extra) -> None:
    """Write or update the status file for a task."""
    status_path = task["_status_path"]

    # Load existing status if present
    if status_path.exists():
        with open(status_path) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    data["status"] = status
    data.update(extra)

    with open(status_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _get_status(task_dir: Path) -> str:
    """Read the current status of a task, or 'pending' if no status file."""
    status_path = task_dir / "status.yaml"
    if not status_path.exists():
        return "pending"
    with open(status_path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("status", "pending")


def _discover_tasks(queue_dir: Path) -> list[Path]:
    """Find all task directories in the queue, sorted by name."""
    tasks = []
    for child in sorted(queue_dir.iterdir()):
        if child.is_dir() and (child / "task.yaml").exists():
            tasks.append(child)
    return tasks


def _run_task(task: dict, config: dict) -> None:
    """Execute a single task: send prompt, wait, extract response."""
    name = task["name"]
    prompt_text = task["_prompt_text"]
    attachment = task["_attachment_path"]
    new_chat = task["new_chat"]
    poll_interval = task["poll_interval"]

    print(f"\n{'=' * 60}")
    print(f"Task: {name}")
    print(f"Prompt: {len(prompt_text)} chars")
    if attachment:
        print(f"Attachment: {attachment.name}")
    print(f"{'=' * 60}")

    start_time = time.time()
    now_str = datetime.now(UTC).isoformat()
    _write_status(task, "running", started_at=now_str)

    # Send prompt
    send_prompt(
        config,
        prompt_text,
        attachment=attachment,
        new_chat=new_chat,
    )

    # Wait for response
    wait_for_response(config, poll_interval=poll_interval)

    # Extract response
    print("Extracting response...")
    response_text = extract_response(config)

    elapsed = time.time() - start_time

    if not response_text.strip():
        _write_status(
            task,
            "failed",
            completed_at=datetime.now(UTC).isoformat(),
            elapsed_seconds=round(elapsed),
            error="Empty clipboard after clicking copy button",
        )
        print(f"  FAILED: empty response for task '{name}'", file=sys.stderr)
        return

    # Save response
    output_path = task["_output_path"]
    output_path.write_text(response_text)

    _write_status(
        task,
        "completed",
        completed_at=datetime.now(UTC).isoformat(),
        elapsed_seconds=round(elapsed),
        response_chars=len(response_text),
        error=None,
    )

    print(f"  Completed in {round(elapsed)}s — {len(response_text)} chars")
    print(f"  Response saved to: {output_path}")


def process_queue(
    queue_dir: Path,
    monitor: str = "1",
    poll_interval: int = 15,
) -> None:
    """Process all pending tasks in a queue directory, one at a time."""
    print(f"Auto-detecting UI elements on monitor {monitor}...")
    config = auto_calibrate(monitor)
    print(f"  Icon at ({config['icon_center'][0]}, {config['icon_center'][1]})")
    print(f"  State: {config['current_state']}")

    # Verify ChatGPT is idle before starting
    if not is_idle(config):
        print("Warning: ChatGPT does not appear idle.", file=sys.stderr)
        print("Waiting for it to become idle before processing queue...", file=sys.stderr)
        while not is_idle(config):
            time.sleep(poll_interval)
        print("ChatGPT is now idle.")

    task_dirs = _discover_tasks(queue_dir)
    if not task_dirs:
        print(f"No tasks found in {queue_dir}")
        return

    # Filter to pending tasks only
    pending = []
    for td in task_dirs:
        status = _get_status(td)
        if status in ("pending", "failed"):
            pending.append(td)
        else:
            print(f"  Skipping {td.name} (status: {status})")

    if not pending:
        print("All tasks already completed.")
        return

    print(f"Found {len(pending)} pending task(s) in {queue_dir}")

    completed = 0
    failed = 0

    for task_dir in pending:
        try:
            task = _load_task(task_dir)
            task["poll_interval"] = poll_interval
            _run_task(task, config)
            completed += 1
        except FileNotFoundError as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            # Write failed status
            status_path = task_dir / "status.yaml"
            with open(status_path, "w") as f:
                yaml.dump(
                    {
                        "status": "failed",
                        "error": str(e),
                        "completed_at": datetime.now(UTC).isoformat(),
                    },
                    f,
                    default_flow_style=False,
                )
            failed += 1
        except Exception as e:
            print(f"  ERROR processing {task_dir.name}: {e}", file=sys.stderr)
            status_path = task_dir / "status.yaml"
            with open(status_path, "w") as f:
                yaml.dump(
                    {
                        "status": "failed",
                        "error": str(e),
                        "completed_at": datetime.now(UTC).isoformat(),
                    },
                    f,
                    default_flow_style=False,
                )
            failed += 1

    print(f"\nQueue complete: {completed} succeeded, {failed} failed out of {len(pending)}")
