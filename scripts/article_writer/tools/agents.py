"""Agent runner for LLM invocation.

Extracted from run_workflow.py to provide reusable agent invocation
with context logging support.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional, Tuple

try:
    from scripts.article_writer.tools.workflow.context_logger import ContextLogger
except ImportError:
    from tools.workflow.context_logger import ContextLogger


def _format_cmd(llm_cmd: str, prompt: str, prompt_file: Path) -> Tuple[list[str], bool]:
    """Return (argv, use_stdin)."""
    parts = shlex.split(llm_cmd)
    formatted: list[str] = []
    has_placeholder = False
    for p in parts:
        if "{prompt_file}" in p or "{prompt}" in p:
            has_placeholder = True
        formatted.append(p.format(prompt_file=str(prompt_file), prompt=prompt))
    use_stdin = not has_placeholder
    return formatted, use_stdin


CODEBLOCK_RE = re.compile(r"```(\w+)?\n(.*?)\n```", re.DOTALL)


def extract_first_codeblock(text: str, lang: str) -> Optional[str]:
    """Extract first code block of given language."""
    for m in CODEBLOCK_RE.finditer(text):
        l = (m.group(1) or "").strip().lower()
        if l == lang.lower():
            return m.group(2).strip()
    return None


def extract_all_codeblocks(text: str) -> list[dict[str, str]]:
    """Extract all code blocks from text."""
    blocks = []
    for m in CODEBLOCK_RE.finditer(text):
        blocks.append(
            {
                "language": (m.group(1) or "").strip().lower(),
                "content": m.group(2).strip(),
            }
        )
    return blocks


class AgentRunner:
    """Runs LLM agents with context logging.

    Usage:
        runner = AgentRunner(llm_cmd="./glm --print", workspace=Path("./workspace"))

        # With context logging
        runner.set_context_logger(logger)

        # Run agent
        output = runner.run_agent("planner", prompt)
    """

    def __init__(
        self,
        llm_cmd: str,
        workspace: Path,
        context_logger: ContextLogger | None = None,
    ) -> None:
        """Initialize agent runner.

        Args:
            llm_cmd: LLM command (supports stdin mode and {prompt_file} placeholder)
            workspace: Workspace directory for temp files and logs
            context_logger: Optional context logger for tracking
        """
        self.llm_cmd = llm_cmd
        self.workspace = workspace
        self.context_logger = context_logger

        # Ensure directories exist
        (workspace / "tmp").mkdir(parents=True, exist_ok=True)
        (workspace / "logs").mkdir(parents=True, exist_ok=True)

    def set_context_logger(self, logger: ContextLogger) -> None:
        """Set the context logger for tracking agent activity."""
        self.context_logger = logger

    def run_agent(
        self,
        agent_name: str,
        prompt: str,
        timeout: int = 300,
    ) -> str:
        """Run an agent with the given prompt.

        Args:
            agent_name: Name of the agent (for logging)
            prompt: Prompt to send to the agent
            timeout: Timeout in seconds (default 5 minutes)

        Returns:
            Agent output (stdout)

        Raises:
            RuntimeError: If agent returns non-zero exit or empty output
        """
        tmp_dir = self.workspace / "tmp"
        logs_dir = self.workspace / "logs"

        prompt_file = tmp_dir / f"{agent_name}_prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        argv, use_stdin = _format_cmd(self.llm_cmd, prompt, prompt_file)

        proc = subprocess.run(
            argv,
            input=prompt if use_stdin else None,
            text=True,
            capture_output=True,
            timeout=timeout,
        )

        # Log raw I/O for debugging
        (logs_dir / f"{agent_name}.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
        (logs_dir / f"{agent_name}.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")

        # Log to context logger if available
        if self.context_logger:
            self.context_logger.log_agent_output(agent_name, proc.stdout or "")

        if proc.returncode != 0:
            error_msg = (
                f"Agent {agent_name} failed (exit={proc.returncode}). "
                f"See logs/{agent_name}.stderr.txt"
            )
            if self.context_logger:
                self.context_logger.log_error(error_msg, {"stderr": proc.stderr})
            raise RuntimeError(error_msg)

        out = (proc.stdout or "").strip()
        if not out:
            error_msg = f"Agent {agent_name} returned empty output."
            if self.context_logger:
                self.context_logger.log_error(error_msg)
            raise RuntimeError(error_msg)

        return out

    def run_local_tool(
        self,
        tool_name: str,
        tool_script: Path,
        args: list[str],
        check: bool = False,
    ) -> tuple[int, str, str]:
        """Run a local Python tool.

        Args:
            tool_name: Name of the tool (for logging)
            tool_script: Path to the tool script
            args: Arguments to pass
            check: Whether to raise on non-zero exit

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        python = os.fspath(shutil.which("python") or "python")
        argv = [python, os.fspath(tool_script)] + args

        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
        )

        if self.context_logger:
            self.context_logger.log_tool_invocation(
                tool_name,
                {"script": str(tool_script), "args": args},
                {"exit_code": proc.returncode},
                error=proc.stderr if proc.returncode != 0 else None,
            )

        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Tool {tool_name} failed (exit={proc.returncode}): {proc.stderr}"
            )

        return proc.returncode, proc.stdout or "", proc.stderr or ""


def build_prompt(template_path: Path, sections: dict[str, str]) -> str:
    """Build a prompt from template and sections.

    Args:
        template_path: Path to the template file
        sections: Dict of section name -> content to append

    Returns:
        Complete prompt text
    """
    base = template_path.read_text(encoding="utf-8").rstrip()
    parts = [base]
    for title, content in sections.items():
        parts.append(f"\n\n## {title}\n")
        parts.append(content)
    return "\n".join(parts).strip() + "\n"


def parse_planner_output(output: str) -> tuple[dict[str, Any], str]:
    """Parse planner output into plan JSON and outline markdown.

    Args:
        output: Raw planner output

    Returns:
        Tuple of (plan_dict, outline_markdown)

    Raises:
        RuntimeError: If required blocks not found
    """
    plan_json_str = extract_first_codeblock(output, "json")
    md_outline_str = extract_first_codeblock(output, "markdown")

    if not plan_json_str or not md_outline_str:
        raise RuntimeError("Planner output did not include required JSON and markdown code blocks.")

    plan = json.loads(plan_json_str)
    return plan, md_outline_str


def parse_researcher_output(output: str) -> dict[str, Any]:
    """Parse researcher output into sources JSON.

    Args:
        output: Raw researcher output

    Returns:
        Sources dict

    Raises:
        RuntimeError: If JSON block not found
    """
    sources_json_str = extract_first_codeblock(output, "json")
    if not sources_json_str:
        raise RuntimeError("Researcher output did not include a JSON code block.")
    return json.loads(sources_json_str)
