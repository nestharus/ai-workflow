#!/usr/bin/env python3
"""Poll multiple agent processes and return when any produces output or completes.

This script manages long-running agent commands for Claude Code. It:
1. Spawns commands as subprocesses (or monitors existing PIDs)
2. Polls all processes for output
3. Returns immediately when ANY process produces output or completes
4. Can be re-run with remaining process info to continue polling

Usage:
    # Start new commands and poll them
    python poll_agents.py --spawn "uv run agent.tasks --agent planner ..." "uv run agent.tasks --agent reviewer ..."

    # Resume polling existing processes (pass state file from previous run)
    python poll_agents.py --resume .tmp/poll_state.json

    # Poll with custom timeout (default 600s = 10 minutes)
    python poll_agents.py --timeout 300 --spawn "command1" "command2"

Output (JSON):
    {
        "status": "output" | "complete" | "timeout" | "empty",
        "process_index": 0,           # Which process had activity (if status=output/complete)
        "command": "the command",     # The command that had activity
        "stdout": "...",              # Captured stdout
        "stderr": "...",              # Captured stderr
        "exit_code": 0,               # Exit code (if complete)
        "state_file": ".tmp/poll_state_xxx.json",  # State file for --resume
        "remaining": 2                # Number of processes still running
    }
"""

from __future__ import annotations

import argparse
import json
import os
import select
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass
class ProcessInfo:
    """Information about a managed subprocess."""

    command: str
    pid: int
    stdout_fd: int
    stderr_fd: int
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    exit_code: int | None = None

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "command": self.command,
            "pid": self.pid,
            "stdout_fd": self.stdout_fd,
            "stderr_fd": self.stderr_fd,
            "stdout_buffer": self.stdout_buffer,
            "stderr_buffer": self.stderr_buffer,
            "exit_code": self.exit_code,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProcessInfo:
        """Deserialize from dictionary."""
        return cls(
            command=data["command"],
            pid=data["pid"],
            stdout_fd=data["stdout_fd"],
            stderr_fd=data["stderr_fd"],
            stdout_buffer=data.get("stdout_buffer", ""),
            stderr_buffer=data.get("stderr_buffer", ""),
            exit_code=data.get("exit_code"),
        )


class AgentPoller:
    """Polls multiple agent processes for output."""

    def __init__(self, timeout: int = 600, poll_interval: float = 0.5):
        """Initialize the poller.

        Args:
            timeout: Maximum time to poll in seconds (default 10 minutes)
            poll_interval: How often to check processes in seconds
        """
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.processes: list[tuple[ProcessInfo, subprocess.Popen]] = []
        self.state_file: Path | None = None

    def spawn_commands(self, commands: list[str]) -> None:
        """Spawn commands as subprocesses.

        Args:
            commands: List of shell commands to run
        """
        for cmd in commands:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )
            info = ProcessInfo(
                command=cmd,
                pid=proc.pid,
                stdout_fd=proc.stdout.fileno() if proc.stdout else -1,
                stderr_fd=proc.stderr.fileno() if proc.stderr else -1,
            )
            self.processes.append((info, proc))

            # Set non-blocking mode on stdout/stderr
            if proc.stdout:
                os.set_blocking(proc.stdout.fileno(), False)
            if proc.stderr:
                os.set_blocking(proc.stderr.fileno(), False)

    def _read_available(self, stream: TextIO | None) -> str:
        """Read all available data from a stream without blocking."""
        if stream is None:
            return ""
        try:
            data = stream.read()
            return data if data else ""
        except (BlockingIOError, TypeError):
            return ""

    def _check_process(self, info: ProcessInfo, proc: subprocess.Popen) -> bool:
        """Check a process for output or completion.

        Returns:
            True if there's new output or process completed
        """
        # Read any available output
        new_stdout = self._read_available(proc.stdout)
        new_stderr = self._read_available(proc.stderr)

        if new_stdout:
            info.stdout_buffer += new_stdout
        if new_stderr:
            info.stderr_buffer += new_stderr

        # Check if process completed
        poll_result = proc.poll()
        if poll_result is not None:
            info.exit_code = poll_result
            # Read any remaining output
            if proc.stdout:
                remaining = proc.stdout.read()
                if remaining:
                    info.stdout_buffer += remaining
            if proc.stderr:
                remaining = proc.stderr.read()
                if remaining:
                    info.stderr_buffer += remaining
            return True

        # Return True if we got meaningful output
        return bool(new_stdout or new_stderr)

    def save_state(self) -> Path:
        """Save current state to a file for resumption.

        Returns:
            Path to the state file
        """
        # Create .tmp directory if needed
        tmp_dir = Path(".tmp")
        tmp_dir.mkdir(exist_ok=True)

        # Generate unique state file name
        timestamp = int(time.time() * 1000)
        state_file = tmp_dir / f"poll_state_{timestamp}.json"

        state = {
            "processes": [info.to_dict() for info, _ in self.processes],
            "timestamp": timestamp,
        }

        state_file.write_text(json.dumps(state, indent=2))
        self.state_file = state_file
        return state_file

    def poll(self) -> dict:
        """Poll all processes until one has output or timeout.

        Returns:
            Dictionary with status and details
        """
        if not self.processes:
            return {"status": "empty", "remaining": 0}

        start_time = time.time()

        while True:
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed >= self.timeout:
                state_file = self.save_state()
                return {
                    "status": "timeout",
                    "elapsed_seconds": int(elapsed),
                    "state_file": str(state_file),
                    "remaining": len(self.processes),
                }

            # Check each process
            completed_indices = []
            for i, (info, proc) in enumerate(self.processes):
                has_activity = self._check_process(info, proc)

                if info.exit_code is not None:
                    # Process completed
                    completed_indices.append(i)
                    state_file = self.save_state()
                    return {
                        "status": "complete",
                        "process_index": i,
                        "command": info.command,
                        "stdout": info.stdout_buffer,
                        "stderr": info.stderr_buffer,
                        "exit_code": info.exit_code,
                        "state_file": str(state_file),
                        "remaining": len(self.processes) - 1,
                    }

                if has_activity and (info.stdout_buffer or info.stderr_buffer):
                    # Process has output - return it but keep process running
                    # Only return if there's substantial output (not just whitespace)
                    stdout_stripped = info.stdout_buffer.strip()
                    stderr_stripped = info.stderr_buffer.strip()
                    if stdout_stripped or stderr_stripped:
                        state_file = self.save_state()
                        # Clear buffers after reporting
                        output = {
                            "status": "output",
                            "process_index": i,
                            "command": info.command,
                            "stdout": info.stdout_buffer,
                            "stderr": info.stderr_buffer,
                            "state_file": str(state_file),
                            "remaining": len(self.processes),
                        }
                        info.stdout_buffer = ""
                        info.stderr_buffer = ""
                        return output

            # Small sleep to avoid busy waiting
            time.sleep(self.poll_interval)

    def cleanup(self) -> None:
        """Terminate all running processes."""
        for _, proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Poll multiple agent processes for output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Timeout in seconds (default: 600 = 10 minutes)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Poll interval in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--spawn",
        nargs="+",
        metavar="COMMAND",
        help="Commands to spawn and poll",
    )
    parser.add_argument(
        "--resume",
        type=str,
        metavar="STATE_FILE",
        help="Resume from a previous state file (not yet implemented)",
    )

    args = parser.parse_args()

    if not args.spawn and not args.resume:
        parser.error("Must specify --spawn with commands or --resume with state file")

    if args.resume:
        print(
            json.dumps(
                {"status": "error", "message": "Resume not yet implemented"}
            ),
            file=sys.stderr,
        )
        return 1

    poller = AgentPoller(timeout=args.timeout, poll_interval=args.poll_interval)

    try:
        if args.spawn:
            poller.spawn_commands(args.spawn)

        result = poller.poll()
        print(json.dumps(result, indent=2))

        # Return appropriate exit code
        if result["status"] == "complete":
            return result.get("exit_code", 0)
        elif result["status"] == "timeout":
            return 124  # Standard timeout exit code
        elif result["status"] == "empty":
            return 0
        else:
            return 0

    except KeyboardInterrupt:
        poller.cleanup()
        return 130

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
