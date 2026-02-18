"""web-gpt: Automate ChatGPT Pro via screenshot-based browser interaction.

Uses PowerShell for screenshots and input (Windows coordinate system),
OpenCV for icon detection, and auto-calibration to find UI elements.

Prerequisites:
    Firefox with ChatGPT open on the target monitor.

Usage:
    # Auto-detect UI elements and check status
    uv run web-gpt status

    # Send a prompt from a file, wait for response, save output
    uv run web-gpt send prompt.md -o response.md

    # Send with file attachment
    uv run web-gpt send prompt.md -a context.zip -o response.md

    # Process a task queue
    uv run web-gpt queue /path/to/tasks/dir
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .detect import auto_calibrate, detect_is_idle
from .sender import (
    extract_response,
    send_prompt,
    wait_for_response,
)


def _get_config(args: argparse.Namespace) -> dict:
    """Auto-calibrate and return config."""
    monitor = getattr(args, "monitor", "1")
    print(f"Auto-detecting UI elements on monitor {monitor}...")
    config = auto_calibrate(monitor)
    print(f"  Icon at ({config['icon_center'][0]}, {config['icon_center'][1]})")
    print(f"  State: {config['current_state']}")
    return config


def cmd_status(args: argparse.Namespace) -> None:
    """Check if ChatGPT is currently idle or generating."""
    config = _get_config(args)
    idle, confidence = detect_is_idle(config)
    print(f"\nStatus: {'IDLE' if idle else 'GENERATING'}")


def cmd_send(args: argparse.Namespace) -> None:
    """Send a prompt to ChatGPT and wait for the response."""
    config = _get_config(args)

    # Read prompt
    prompt_path = Path(args.prompt)
    if not prompt_path.exists():
        print(f"Error: prompt file not found: {prompt_path}", file=sys.stderr)
        sys.exit(1)
    prompt_text = prompt_path.read_text()

    # Resolve attachment
    attachment = None
    if args.attach:
        attachment = Path(args.attach)
        if not attachment.exists():
            print(f"Error: attachment not found: {attachment}", file=sys.stderr)
            sys.exit(1)

    print(f"\nPrompt: {len(prompt_text)} chars from {prompt_path}")
    if attachment:
        print(f"Attachment: {attachment.name}")

    # Send
    send_prompt(
        config,
        prompt_text,
        attachment=attachment,
        new_chat=not args.continue_chat,
    )

    # Wait for response
    wait_for_response(config, poll_interval=args.poll)

    # Extract response
    print("Extracting response...")
    response_text = extract_response(config)

    if not response_text.strip():
        print("Warning: clipboard is empty after clicking copy.", file=sys.stderr)
        print("You may need to manually copy the response.", file=sys.stderr)
        sys.exit(1)

    # Save or print response
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(response_text)
        print(f"Response saved to: {output_path} ({len(response_text)} chars)")
    else:
        print("--- Response ---")
        print(response_text)


def cmd_queue(args: argparse.Namespace) -> None:
    """Process a task queue from a directory."""
    from .queue import process_queue

    queue_dir = Path(args.queue_dir)
    if not queue_dir.is_dir():
        print(f"Error: queue directory not found: {queue_dir}", file=sys.stderr)
        sys.exit(1)

    process_queue(queue_dir, monitor=args.monitor, poll_interval=args.poll)


def cmd_detect(args: argparse.Namespace) -> None:
    """Show detailed auto-detection results."""
    config = _get_config(args)
    print("\nDetection results:")
    print(json.dumps(config, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Automate ChatGPT Pro via screenshot-based browser interaction"
    )
    parser.add_argument("--monitor", default="1", help="Monitor number (default: 1)")
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="Check if ChatGPT is idle or generating")

    # send
    send_p = sub.add_parser("send", help="Send a prompt and wait for response")
    send_p.add_argument("prompt", help="Path to prompt file (markdown)")
    send_p.add_argument("-o", "--output", help="Path to save response")
    send_p.add_argument("-a", "--attach", help="Path to file attachment (zip, etc.)")
    send_p.add_argument(
        "--poll", type=int, default=15, help="Poll interval in seconds (default: 15)"
    )
    send_p.add_argument(
        "--continue-chat",
        action="store_true",
        help="Continue in current chat (don't start new chat)",
    )

    # queue
    queue_p = sub.add_parser("queue", help="Process a task queue from a directory")
    queue_p.add_argument("queue_dir", help="Path to task queue directory")
    queue_p.add_argument(
        "--poll", type=int, default=15, help="Poll interval in seconds (default: 15)"
    )

    # detect (debug)
    sub.add_parser("detect", help="Show detailed auto-detection results")

    args = parser.parse_args()

    commands = {
        "status": cmd_status,
        "send": cmd_send,
        "queue": cmd_queue,
        "detect": cmd_detect,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
