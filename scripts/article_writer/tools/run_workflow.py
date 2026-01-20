#!/usr/bin/env python3
"""One-command multi-agent writing workflow.

This runner is designed to:

- create a workspace (temp by default)
- plan + outline
- optionally research
- draft
- run local analysis (lint, skeleton/borders, tempo, readability)
- run reviewer agents
- edit
- iterate until hard-ban lint passes (bounded)
- export final markdown

AGENT EXECUTION:
- Agents are defined in `.agents/agents/article-writer-*.md` with YAML frontmatter
- Execution uses `uv run python -m scripts.agents` with model routing
- Default model: glm-flash (configurable via .agents/models/)
- SQLite-backed state machine for persistence and resume capability

OPTIONAL LLM OVERRIDE:
- LLM invocation can be overridden via `--llm-cmd` for custom LLM backends
- stdin mode (default): reads prompt from stdin, prints completion to stdout
- placeholder mode: supports `{prompt_file}` and/or `{prompt}` placeholders

FEATURES:
- SQLite-backed state persistence
- Resume support: --resume <workflow_id> continues a paused workflow
- Context logging: Captures all agent activity for summarization
- Pause/resume: Workflow can be paused and resumed with full context

Example:
  # Default agent-based mode (recommended)
  python run_workflow.py --input notes.md --output final.md

  # With custom LLM command (overrides agent system)
  python run_workflow.py --input notes.md --output final.md --llm-cmd "claude --print"

  # Resume a paused workflow
  python run_workflow.py --resume abc123
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Required imports for state machine
try:
    from scripts.article_writer.tools.workflow.database import Database
    from scripts.article_writer.tools.workflow.state_machine import StateMachine, create_workflow, load_workflow, Phase, Status
    from scripts.article_writer.tools.workflow.context_logger import ContextLogger
    from scripts.article_writer.tools.workflow.session import SessionManager
    from scripts.article_writer.tools.agents import AgentRunner
    STATE_MACHINE_AVAILABLE = True
except ImportError:
    try:
        # Fallback for running from within the package
        from tools.workflow.database import Database
        from tools.workflow.state_machine import StateMachine, create_workflow, load_workflow, Phase, Status
        from tools.workflow.context_logger import ContextLogger
        from tools.workflow.session import SessionManager
        from tools.agents import AgentRunner
        STATE_MACHINE_AVAILABLE = True
    except ImportError:
        STATE_MACHINE_AVAILABLE = False

# Optional imports for invariant enforcement
try:
    from scripts.article_writer.tools.invariants import (
        DynamicInvariantSystem,
        extract_invariants_from_brief,
        check_all_invariants,
        apply_fixes,
        InvariantSet,
    )
    INVARIANTS_AVAILABLE = True
except ImportError:
    try:
        from tools.invariants import (
            DynamicInvariantSystem,
            extract_invariants_from_brief,
            check_all_invariants,
            apply_fixes,
            InvariantSet,
        )
        INVARIANTS_AVAILABLE = True
    except ImportError:
        INVARIANTS_AVAILABLE = False


def _now_id() -> str:
    return time.strftime("%Y-%m-%d-%H%M%S")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(_read_text(path))


def _dump_json(path: Path, obj: Any) -> None:
    _write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


_CODEBLOCK_RE = re.compile(r"```(\w+)?\n(.*?)\n```", re.DOTALL)

# Patterns that indicate LLM meta-commentary (not article content)
_META_PATTERNS = [
    r"^(let me|i'll|i will|i now|here is|here's|the lint|looking at|this is|based on)",
    r"^(the draft|the article|the output|the response|the revised)",
    r"^(revised article|revised draft|clean version|final version)",
    r"^(no preface|no analysis|markdown only)",
]
_META_RE = re.compile("|".join(_META_PATTERNS), re.IGNORECASE | re.MULTILINE)


def _clean_article_output(text: str) -> str:
    """Strip LLM meta-commentary from article output.

    Detects patterns like "Let me return the revised article..." and strips them,
    returning only the actual article content.
    """
    text = text.strip()

    # If entire output is wrapped in a markdown code block, extract content
    # Handle variations: ```markdown\n...\n``` or ```\n...\n```
    if text.startswith("```"):
        # Find closing backticks
        lines = text.split("\n")
        if lines[-1].strip() == "```" or text.rstrip().endswith("```"):
            # Find the end of the first line (lang specifier)
            first_newline = text.find("\n")
            if first_newline != -1:
                inner = text[first_newline + 1 :]
                # Remove closing backticks
                inner = inner.rstrip()
                if inner.endswith("```"):
                    inner = inner[:-3].rstrip()
                text = inner

    lines = text.strip().split("\n")

    # Find first non-meta paragraph
    cleaned_lines = []
    in_article = False
    blank_count = 0

    for line in lines:
        stripped = line.strip()

        if not stripped:
            blank_count += 1
            if in_article:
                cleaned_lines.append(line)
            continue

        # Check if this line looks like meta-commentary
        if not in_article:
            if _META_RE.search(stripped):
                # Skip meta lines
                blank_count = 0
                continue
            # Check if we've seen blank lines indicating paragraph break
            if blank_count > 0 or not cleaned_lines:
                # This could be the start of actual content
                # Heuristic: actual article paragraphs usually start with capital letter
                # and don't contain certain meta-words
                first_word = stripped.split()[0] if stripped.split() else ""
                if first_word and first_word[0].isupper():
                    in_article = True

        if in_article or not _META_RE.search(stripped):
            in_article = True
            cleaned_lines.append(line)

        blank_count = 0

    result = "\n".join(cleaned_lines).strip()

    # If cleaning removed everything, return original
    if not result:
        return text.strip()

    return result


def _extract_first_codeblock(text: str, lang: str) -> Optional[str]:
    for m in _CODEBLOCK_RE.finditer(text):
        l = (m.group(1) or "").strip().lower()
        if l == lang.lower():
            return m.group(2).strip()
    return None


def _extract_nth_codeblock(text: str, n: int) -> Optional[Tuple[str, str]]:
    blocks = list(_CODEBLOCK_RE.finditer(text))
    if len(blocks) <= n:
        return None
    m = blocks[n]
    lang = (m.group(1) or "").strip().lower()
    body = m.group(2).strip()
    return lang, body


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


# Map internal agent names to their .agents/agents/ filenames
_AGENT_NAME_MAP = {
    "planner": "article-writer-planner",
    "researcher": "article-writer-researcher",
    "writer": "article-writer-writer",
    "alignment_reviewer": "article-writer-alignment-reviewer",
    "value_reviewer": "article-writer-value-reviewer",
    "flow_reviewer": "article-writer-flow-reviewer",
    "ai_tells_reviewer": "article-writer-ai-tells-reviewer",
    "robustness_reviewer": "article-writer-robustness-reviewer",
    "editor": "article-writer-editor",
    # Multi-pass fixer agents (replace monolithic editor in REVISE phase)
    "alignment_fixer": "article-writer-alignment-fixer",
    "ai_tells_fixer": "article-writer-ai-tells-fixer",
    "flow_fixer": "article-writer-flow-fixer",
    "value_fixer": "article-writer-value-fixer",
    "robustness_fixer": "article-writer-robustness-fixer",
    "finalizer": "article-writer-finalizer",
    "invariant_extractor": "article-writer-invariant-extractor",
    "invariant_reviewer": "article-writer-invariant-reviewer",
    "condenser": "article-writer-condenser",
    "cutter": "article-writer-cutter",
    # Drift detection agent (optional, runs after REVISE when enabled)
    "drift_detector": "article-writer-drift-detector",
}


def run_agent(
    *,
    agent_name: str,
    prompt: str,
    workspace: Path,
    project_root: Path | None = None,
    max_retries: int = 3,
) -> str:
    """Run an agent via the scripts.agents module.

    Uses `uv run python -m scripts.agents <agent_name> --file <prompt_file>`
    to invoke the agent with proper routing. Retries on empty output.
    """
    # Map internal name to .agents/agents/ filename
    agent_id = _AGENT_NAME_MAP.get(agent_name, f"article-writer-{agent_name}")

    tmp_dir = workspace / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Write prompt to file (agent prompts can be very long)
    prompt_file = tmp_dir / f"{agent_name}_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    # Determine project root for agent execution
    if project_root is None:
        # Default to the repo root (grandparent of this file's parent directory)
        project_root = Path(__file__).resolve().parents[3]

    # Run via scripts.agents module
    argv = [
        "uv", "run", "python", "-m", "scripts.agents",
        agent_id,
        "--file", str(prompt_file),
        "--project", str(project_root),
    ]

    logs_dir = workspace / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    last_error = None
    for attempt in range(max_retries):
        proc = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            cwd=project_root,
        )

        # Always log raw I/O for debugging.
        (logs_dir / f"{agent_name}.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
        (logs_dir / f"{agent_name}.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")

        if proc.returncode != 0:
            last_error = RuntimeError(
                f"Agent failed (agent={agent_id}, exit={proc.returncode}). See logs/{agent_name}.stderr.txt"
            )
            time.sleep(2 ** attempt)  # Exponential backoff
            continue

        out = (proc.stdout or "").strip()
        if out:
            return out

        # Empty output - retry
        last_error = RuntimeError(f"Agent returned empty output (agent={agent_id}).")
        time.sleep(2 ** attempt)  # Exponential backoff

    raise last_error or RuntimeError(f"Agent failed after {max_retries} retries (agent={agent_id}).")


def run_llm(*, llm_cmd: str, prompt: str, workspace: Path, label: str) -> str:
    """Legacy LLM runner for backwards compatibility.

    Used when --llm-cmd is provided explicitly (legacy mode).
    For agent-based execution, use run_agent() instead.
    """
    tmp_dir = workspace / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    prompt_file = tmp_dir / f"{label}_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    argv, use_stdin = _format_cmd(llm_cmd, prompt, prompt_file)

    proc = subprocess.run(
        argv,
        input=prompt if use_stdin else None,
        text=True,
        capture_output=True,
    )

    # Always log raw I/O for debugging.
    logs_dir = workspace / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / f"{label}.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (logs_dir / f"{label}.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(
            f"LLM command failed (label={label}, exit={proc.returncode}). See logs/{label}.stderr.txt"
        )

    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError(f"LLM returned empty output (label={label}).")

    return out


def load_global_constraints(package_root: Path) -> str:
    # For prompt size, include only the non-negotiables + rubric headings.
    master = _read_text(package_root / "WRITING_SKILL_MASTER.md")
    # Extract from "## Non negotiables" to end of "## Rubrics" section headers.
    # Keep it simple: include the whole master if parsing fails.
    m = re.search(r"## Non negotiables.*", master, re.DOTALL)
    return m.group(0).strip() if m else master


def ensure_brief(*, brief_path: Optional[Path], notes: str, workspace: Path) -> Dict[str, Any]:
    if brief_path:
        brief = json.loads(_read_text(brief_path))
    else:
        # Minimal inferred brief.
        first_line = ""
        for line in notes.splitlines():
            if line.strip():
                first_line = line.strip()
                break
        brief = {
            "topic": first_line[:140] if first_line else "",
            "objective": "",
            "venue": "",
            "reach_goal": "",
            "audience": {"primary": "", "topic_knowledge": "", "backgrounds": []},
            "piece_type": "",
            "constraints": {"target_word_count": None, "include_citations": False},
        }

    # Normalize global ban-sensitive defaults.
    brief.setdefault("constraints", {})
    brief["constraints"].setdefault("include_citations", False)

    _dump_json(workspace / "brief.json", brief)
    return brief


def enforce_invariants(
    text: str,
    brief: Dict[str, Any],
    workspace: Path,
) -> Tuple[str, list[Dict[str, Any]]]:
    """Enforce invariants on final text.

    Returns:
        Tuple of (fixed_text, violations_list)
    """
    if not INVARIANTS_AVAILABLE:
        return text, []

    # Extract invariants from brief
    inv_set = extract_invariants_from_brief(brief)

    # Check for violations
    violations = check_all_invariants(text, inv_set)

    if not violations:
        return text, []

    # Apply automatic fixes
    fixed_text = apply_fixes(text, violations)

    # Re-check after fixes
    remaining_violations = check_all_invariants(fixed_text, inv_set)

    # Log violations
    violation_dicts = []
    for v in remaining_violations:
        violation_dicts.append({
            "invariant": v.invariant.name,
            "description": v.invariant.description,
            "message": v.message,
            "location": v.location,
            "fixable": v.fixable,
        })

    # Save invariant report
    report = {
        "invariants": [
            {"name": i.name, "description": i.description, "source": i.source}
            for i in inv_set.invariants
        ],
        "platform": inv_set.platform,
        "max_characters": inv_set.max_characters,
        "violations_before_fix": len(violations),
        "violations_after_fix": len(remaining_violations),
        "remaining_violations": violation_dicts,
    }
    _dump_json(workspace / "analysis" / "invariants.json", report)

    if remaining_violations:
        # Write human-readable report
        lines = ["# Invariant Violations", ""]
        lines.append(f"Platform: {inv_set.platform or 'unknown'}")
        lines.append(f"Violations fixed: {len(violations) - len(remaining_violations)}")
        lines.append(f"Violations remaining: {len(remaining_violations)}")
        lines.append("")
        for v in remaining_violations:
            lines.append(f"- **{v.invariant.name}**: {v.message}")
        _write_text(workspace / "analysis" / "invariants.md", "\n".join(lines))

    return fixed_text, violation_dicts


def run_local_tools(*, package_root: Path, draft_path: Path, analysis_dir: Path) -> Dict[str, Any]:
    tools_dir = package_root / "tools"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # Lint (md + json)
    lint_md = analysis_dir / "lint.md"
    lint_json = analysis_dir / "lint.json"

    subprocess.run(
        [
            os.fspath(shutil.which("python") or "python"),
            os.fspath(tools_dir / "lint_ai_tells.py"),
            os.fspath(draft_path),
            "--output",
            os.fspath(lint_md),
        ],
        check=False,
    )
    subprocess.run(
        [
            os.fspath(shutil.which("python") or "python"),
            os.fspath(tools_dir / "lint_ai_tells.py"),
            os.fspath(draft_path),
            "--format",
            "json",
            "--output",
            os.fspath(lint_json),
        ],
        check=False,
    )

    # Tempo
    subprocess.run(
        [
            os.fspath(shutil.which("python") or "python"),
            os.fspath(tools_dir / "tempo_report.py"),
            os.fspath(draft_path),
            "--output",
            os.fspath(analysis_dir / "tempo.md"),
        ],
        check=False,
    )

    # Readability
    subprocess.run(
        [
            os.fspath(shutil.which("python") or "python"),
            os.fspath(tools_dir / "readability_report.py"),
            os.fspath(draft_path),
            "--output",
            os.fspath(analysis_dir / "readability.md"),
        ],
        check=False,
    )

    # Skeleton + borders
    subprocess.run(
        [
            os.fspath(shutil.which("python") or "python"),
            os.fspath(tools_dir / "extract_skeleton.py"),
            os.fspath(draft_path),
            "--outdir",
            os.fspath(analysis_dir),
        ],
        check=False,
    )

    lint_obj: Dict[str, Any] = {}
    if lint_json.exists():
        try:
            lint_obj = _load_json(lint_json)
        except Exception:
            lint_obj = {}

    return {"lint": lint_obj}


def lint_fail_count(lint_obj: Dict[str, Any]) -> int:
    findings = lint_obj.get("findings", []) if isinstance(lint_obj, dict) else []
    return sum(1 for f in findings if f.get("severity") == "fail")


def build_prompt(template_path: Path, sections: Dict[str, str]) -> str:
    base = _read_text(template_path).rstrip()
    parts = [base]
    for title, content in sections.items():
        parts.append(f"\n\n## {title}\n")
        parts.append(content)
    return "\n".join(parts).strip() + "\n"


# ============================================================================
# State Machine Mode Functions
# ============================================================================

def run_state_machine_workflow(args: argparse.Namespace) -> int:
    """Run workflow with state machine tracking.

    This mode enables:
    - SQLite-backed state persistence
    - Context logging for all agent activity
    - Pause/resume capability
    - Better error recovery
    """
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    output_path = Path(args.output).expanduser().resolve()
    package_root = Path(__file__).resolve().parents[1]

    # Initialize database
    db = Database(args.db)
    db.init()

    # Create workflow config
    config = {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "llm_cmd": args.llm_cmd,
        "no_research": args.no_research,
        "max_loops": args.max_loops,
        "package_root": str(package_root),
    }
    if args.brief:
        config["brief_path"] = str(Path(args.brief).expanduser().resolve())
    if args.style:
        config["style_path"] = str(Path(args.style).expanduser().resolve())
    if args.workspace:
        config["workspace"] = str(Path(args.workspace).expanduser().resolve())
    if args.pause_after:
        config["pause_after"] = args.pause_after
    if args.enable_drift_detection:
        config["enable_drift_detection"] = True

    # Create workflow
    sm = create_workflow(db, "article-writer", config)
    print(f"Created workflow: {sm.workflow_id}")

    # Run the workflow loop
    return _run_workflow_loop(sm, args)


def run_resume_workflow(args: argparse.Namespace) -> int:
    """Resume a paused workflow."""
    db = Database(args.db)

    try:
        sm = load_workflow(db, args.resume)
    except ValueError as e:
        raise SystemExit(f"Failed to load workflow: {e}")

    if sm.current_status == Status.COMPLETED:
        print(f"Workflow {args.resume} is already completed.")
        return 0

    if sm.current_status == Status.ERROR:
        print(f"Workflow {args.resume} is in error state. Cannot resume.")
        return 1

    # Check for pending input request (e.g., cut selection)
    if sm.current_status == Status.WAITING_INPUT:
        pending = sm._get_pending_input_request()
        if pending:
            # Get user response from args or prompt
            if args.response:
                response = args.response
            else:
                print(f"Pending input: {pending.prompt}")
                if pending.options:
                    print("Options:")
                    for opt in pending.options:
                        print(f"  - {opt}")
                response = input("Your response (e.g., 'A,B' for multiple cuts): ").strip()

            # Parse response to extract cut IDs
            selected_cuts = _parse_cut_selection(response)
            print(f"Selected cuts: {selected_cuts}")

            # Provide the response
            sm.provide_input(pending.id, response)

            # Store selected cuts in workflow config for cutter agent
            config = sm.workflow.config or {}
            config["selected_cuts"] = selected_cuts
            sm._update_workflow(config=config)

    # Resume if paused
    resume_context = ""
    if sm.current_status == Status.PAUSED:
        resume_context = sm.resume()
        print(f"Resumed workflow from phase: {sm.current_phase.value}")
        if resume_context:
            print("Resume context available - will be injected into next agent prompt")

    # Override llm_cmd if provided
    if args.llm_cmd:
        config = sm.workflow.config or {}
        config["llm_cmd"] = args.llm_cmd
        sm._update_workflow(config=config)

    return _run_workflow_loop(sm, args, resume_context)


def _parse_cut_selection(response: str) -> list[str]:
    """Parse user's cut selection response into list of cut IDs.

    Accepts formats like:
    - "A" -> ["A"]
    - "A, B" -> ["A", "B"]
    - "A,C" -> ["A", "C"]
    - "B [RECOMMENDED]" -> ["B"]
    """
    # Remove [RECOMMENDED] markers and other noise
    response = response.replace("[RECOMMENDED]", "").replace("[recommended]", "")

    # Split by comma, semicolon, or space
    parts = re.split(r'[,;\s]+', response)

    # Extract single-letter IDs (A, B, C, etc.)
    cuts = []
    for part in parts:
        part = part.strip().upper()
        if part and len(part) == 1 and part.isalpha():
            cuts.append(part)
        elif part.endswith(":"):
            # Handle "A:" format
            cuts.append(part[0])

    return cuts


def _run_workflow_loop(
    sm: "StateMachine",
    args: argparse.Namespace,
    resume_context: str = "",
) -> int:
    """Main workflow execution loop for state machine mode.

    Orchestrates the workflow by repeatedly getting the next action
    from the state machine and executing it.
    """
    config = sm.workflow.config or {}
    package_root = Path(config.get("package_root", Path(__file__).resolve().parents[1]))
    llm_cmd = config.get("llm_cmd", args.llm_cmd)
    pause_after = config.get("pause_after")

    # Setup workspace
    workspace = _setup_workspace(config)

    # Create session manager and context logger
    session_manager = SessionManager(sm.db)
    # Try to get existing active session (for resume case)
    current_session = session_manager.get_active_session(sm.workflow_id)
    if not current_session:
        current_session = session_manager.create_session(sm.workflow_id, "workflow")
    context_logger = ContextLogger(sm.db, current_session.id)

    # Track state for the workflow
    workflow_state: Dict[str, Any] = {
        "notes": "",
        "brief": {},
        "plan": {},
        "style": {},
        "sources": {},
        "outline": "",
        "draft": "",
        "reviews": {},
        "resume_context": resume_context,
        "extracted_invariants": [],
        "length_violations": [],
        "condenser_analysis": {},
        "selected_cuts": [],
        "user_feedback": [],
        "invariant_feedback": [],
    }

    # Load persisted state from workflow config
    if config:
        workflow_state["length_violations"] = config.get("length_violations", [])
        workflow_state["selected_cuts"] = config.get("selected_cuts", [])
        workflow_state["user_feedback"] = config.get("user_feedback", [])
        workflow_state["invariant_feedback"] = config.get("invariant_feedback", [])
        if config.get("condenser_analysis"):
            workflow_state["condenser_analysis"] = config.get("condenser_analysis", {})

        # Clear pending feedback flag after loading
        if config.get("has_pending_feedback"):
            config["has_pending_feedback"] = False
            sm._update_workflow(config=config)

    # Load existing draft from workspace (for resume)
    draft_files = ["draft_invariant_fixed.md", "draft_cut.md", "final.md", "draft_01.md", "draft_00.md"]
    for draft_file in draft_files:
        draft_path = workspace / "drafts" / draft_file
        if draft_path.exists():
            workflow_state["draft"] = _read_text(draft_path)
            break

    # Load extracted invariants if they exist
    inv_path = workspace / "analysis" / "extracted_invariants.json"
    if inv_path.exists():
        try:
            workflow_state["extracted_invariants"] = _load_json(inv_path)
        except Exception:
            pass

    # Load condenser analysis if it exists
    cond_path = workspace / "analysis" / "condenser_analysis.json"
    if cond_path.exists():
        try:
            workflow_state["condenser_analysis"] = _load_json(cond_path)
        except Exception:
            pass

    # Load plan if exists
    plan_path = workspace / "plan.json"
    if plan_path.exists():
        try:
            workflow_state["plan"] = _load_json(plan_path)
            workflow_state["style"] = workflow_state["plan"].get("style", {})
        except Exception:
            pass

    # Load outline if exists
    outline_path = workspace / "outline.md"
    if outline_path.exists():
        try:
            workflow_state["outline"] = _read_text(outline_path)
        except Exception:
            pass

    # Load sources if exists
    sources_path = workspace / "sources.json"
    if sources_path.exists():
        try:
            workflow_state["sources"] = _load_json(sources_path)
        except Exception:
            pass

    # Load reviews if exist
    reviews_dir = workspace / "reviews"
    if reviews_dir.exists():
        for review_file in reviews_dir.glob("*.md"):
            try:
                workflow_state.setdefault("reviews", {})[review_file.stem + ".md"] = _read_text(review_file)
            except Exception:
                pass

    # Load analysis outputs for agents that need them
    analysis_dir = workspace / "analysis"
    if analysis_dir.exists():
        for name in ["lint.md", "skeleton.md", "borders.md", "tempo.md", "readability.md"]:
            file_path = analysis_dir / name
            if file_path.exists():
                try:
                    # Store with underscore key for state dict (lint.md -> lint_md)
                    key = name.replace(".", "_")
                    workflow_state[key] = _read_text(file_path)
                except Exception:
                    pass

    # Load input
    input_path = Path(config.get("input_path", ""))
    if input_path.exists():
        workflow_state["notes"] = _read_text(input_path)

    # Load brief if provided
    brief_path = config.get("brief_path")
    if brief_path and Path(brief_path).exists():
        workflow_state["brief"] = _load_json(Path(brief_path))
    else:
        workflow_state["brief"] = ensure_brief(
            brief_path=None,
            notes=workflow_state["notes"],
            workspace=workspace,
        )

    # Load constraints
    constraints = load_global_constraints(package_root)

    print(f"Running workflow in state machine mode...")
    print(f"Workflow ID: {sm.workflow_id}")
    print(f"Database: {args.db}")

    try:
        while True:
            action = sm.get_next_action()

            if action.action.value == "complete":
                print("Workflow completed!")
                break

            if action.action.value == "error":
                print(f"Workflow error: {action.error}")
                return 1

            if action.action.value == "user_input":
                print(f"User input required: {action.prompt}")
                if action.options:
                    print(f"Options: {action.options}")
                # Workflow is already in WAITING_INPUT status (set by request_input)
                # Don't call pause() as that would change status to PAUSED
                print(f"Workflow waiting for input. Resume with: --resume {sm.workflow_id}")
                return 0

            # Execute the action
            if action.action.value == "call_agent":
                # Use agent system by default, fallback to llm_cmd if explicitly provided
                use_agent_system = not bool(llm_cmd) or config.get("use_agent_system", True)
                result = _execute_agent_action(
                    action,
                    sm,
                    workflow_state,
                    workspace,
                    package_root,
                    llm_cmd or "",
                    constraints,
                    context_logger,
                    use_agent_system=use_agent_system,
                )

                # Check if agent requires user input (e.g., condenser asking for cut selection)
                if result.get("user_input_required"):
                    # Create input request
                    request_id = sm.request_input(
                        prompt=result.get("user_prompt", "User input required"),
                        request_type="cut_selection",
                        options=result.get("user_options", []),
                    )
                    print(f"\nUser input required: {result.get('user_prompt')}")
                    if result.get("user_options"):
                        print("Options:")
                        for opt in result.get("user_options", []):
                            print(f"  - {opt}")
                    print(f"\nWorkflow paused. Provide response to continue.")
                    print(f"Resume with: --resume {sm.workflow_id}")

                    # Store condenser result for cutter - persist in workflow config
                    workflow_state["condenser_analysis"] = result.get("condenser_result", {})
                    sm_config = sm.workflow.config or {}
                    sm_config["condenser_analysis"] = result.get("condenser_result", {})
                    sm._update_workflow(config=sm_config)

                    # Advance phase from CONDENSE to APPLY_CUT before returning
                    # This ensures when resumed with user input, the cutter runs instead of condenser
                    sm.process_result(result, context_logger)
                    return 0

                # Capture phase before processing result
                prev_phase = sm.current_phase.value
                sm.process_result(result, context_logger)
                # Log phase transition (from previous to current)
                new_phase = sm.current_phase.value
                if prev_phase != new_phase:
                    context_logger.log_phase_transition(prev_phase, new_phase)

                # Run drift detection after REVISE phase completes (if enabled)
                if prev_phase == "revise" and sm._should_run_drift_detection():
                    print("Running drift detection...")
                    drift_result = _run_drift_detection(
                        sm=sm,
                        state=workflow_state,
                        workspace=workspace,
                        package_root=package_root,
                        llm_cmd=llm_cmd or "",
                        constraints=constraints,
                        context_logger=context_logger,
                        use_agent_system=use_agent_system,
                    )
                    # Process drift result (stores in config, logs warning if significant)
                    sm.process_result(drift_result, context_logger)

            elif action.action.value == "run_tool":
                # Capture phase before processing result
                prev_phase = sm.current_phase.value
                result = _execute_tool_action(
                    action,
                    sm,
                    workflow_state,
                    workspace,
                    package_root,
                    context_logger,
                )
                sm.process_result(result, context_logger)
                # Log phase transition (from previous to current)
                new_phase = sm.current_phase.value
                if prev_phase != new_phase:
                    context_logger.log_phase_transition(prev_phase, new_phase)

            # Check if we should pause after this phase
            if pause_after and sm.current_phase.value == pause_after:
                sm.pause(f"Paused after {pause_after} phase (--pause-after)")
                print(f"Workflow paused after {pause_after}. Resume with: --resume {sm.workflow_id}")
                return 0

    except KeyboardInterrupt:
        print("\nInterrupted - pausing workflow...")
        sm.pause("User interrupted")
        print(f"Workflow paused. Resume with: --resume {sm.workflow_id}")
        return 0
    except Exception as e:
        sm.set_error(str(e))
        context_logger.log_error(str(e))
        raise

    # Export final result
    final_draft = workflow_state.get("draft", "")
    output_path = Path(config.get("output_path", ""))
    if output_path and final_draft:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(final_draft + "\n", encoding="utf-8")
        print(f"Output written to: {output_path}")

    return 0


def _setup_workspace(config: Dict[str, Any]) -> Path:
    """Setup workspace directory."""
    workspace_path = config.get("workspace")
    if workspace_path:
        workspace = Path(workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)
    else:
        workspace = Path(tempfile.mkdtemp(prefix="writing-skill-" + _now_id() + "-"))

    # Create subdirs
    for d in ["drafts", "analysis", "reviews", "logs", "tmp"]:
        (workspace / d).mkdir(parents=True, exist_ok=True)

    return workspace


def _execute_agent_action(
    action: "NextAction",
    sm: "StateMachine",
    state: Dict[str, Any],
    workspace: Path,
    package_root: Path,
    llm_cmd: str,
    constraints: str,
    context_logger: "ContextLogger",
    use_agent_system: bool = True,
) -> Dict[str, Any]:
    """Execute an agent action.

    Args:
        use_agent_system: If True, use scripts.agents module for execution.
                         If False, use legacy llm_cmd mode.
    """
    agent_name = action.agent
    print(f"Running agent: {agent_name}")

    # Build prompt based on agent - use .agents/agents/ files
    project_root = Path(__file__).resolve().parents[3]
    agent_id = _AGENT_NAME_MAP.get(agent_name, f"article-writer-{agent_name}")
    template_path = project_root / ".agents" / "agents" / f"{agent_id}.md"
    if not template_path.exists():
        raise RuntimeError(f"Agent template not found: {template_path}")

    prompt = _build_agent_prompt(agent_name, template_path, state, constraints)

    # Inject resume context if available
    if state.get("resume_context"):
        prompt = state["resume_context"] + "\n\n" + prompt
        state["resume_context"] = ""  # Clear after use

    # Run the agent - use scripts.agents system or legacy llm_cmd
    if use_agent_system:
        # Use the scripts.agents module with routing
        # Project root is the repo root (3 levels up from this file)
        project_root = Path(__file__).resolve().parents[3]
        output = run_agent(
            agent_name=agent_name,
            prompt=prompt,
            workspace=workspace,
            project_root=project_root,
        )
    else:
        # Legacy mode using custom llm_cmd
        output = run_llm(llm_cmd=llm_cmd, prompt=prompt, workspace=workspace, label=agent_name)

    # Parse and store output
    result = _parse_agent_output(agent_name, output, state, workspace)
    result["agent"] = agent_name
    result["output"] = output
    result["inputs"] = action.inputs  # Pass through inputs for multi-agent tracking

    return result


def _execute_tool_action(
    action: "NextAction",
    sm: "StateMachine",
    state: Dict[str, Any],
    workspace: Path,
    package_root: Path,
    context_logger: "ContextLogger",
) -> Dict[str, Any]:
    """Execute a local tool action."""
    tools = action.inputs.get("all_tools", [action.tool])
    print(f"Running tools: {tools}")

    draft_path = workspace / "drafts" / "draft_00.md"
    if state.get("draft"):
        _write_text(draft_path, state["draft"])

    analysis_dir = workspace / "analysis"
    lint_state = run_local_tools(
        package_root=package_root,
        draft_path=draft_path,
        analysis_dir=analysis_dir,
    )

    # Load tool outputs into workflow state for agents
    for name in ["lint.md", "skeleton.md", "borders.md", "tempo.md", "readability.md"]:
        file_path = analysis_dir / name
        if file_path.exists():
            try:
                key = name.replace(".", "_")  # lint.md -> lint_md
                state[key] = _read_text(file_path)
            except Exception:
                pass

    return {
        "tool": "analysis",
        "completed_tools": tools,
        "inputs": action.inputs,
        "lint": lint_state.get("lint", {}),
    }


def _run_drift_detection(
    *,
    sm: "StateMachine",
    state: Dict[str, Any],
    workspace: Path,
    package_root: Path,
    llm_cmd: str,
    constraints: str,
    context_logger: "ContextLogger",
    use_agent_system: bool = True,
) -> Dict[str, Any]:
    """Run drift detection after REVISE phase completes.

    This is an optional check that compares the revised draft against
    the original plan/outline to detect significant drift.

    Returns:
        Result dict containing drift_result for state machine processing
    """
    agent_name = "drift_detector"

    # Build prompt for drift detector
    project_root = Path(__file__).resolve().parents[3]
    agent_id = _AGENT_NAME_MAP.get(agent_name, f"article-writer-{agent_name}")
    template_path = project_root / ".agents" / "agents" / f"{agent_id}.md"

    if not template_path.exists():
        # Agent template not found - skip drift detection silently
        return {
            "agent": agent_name,
            "content": "",
            "drift_result": {"drift_level": "none", "recommendation": "continue"},
        }

    prompt = _build_agent_prompt(agent_name, template_path, state, constraints)

    # Run the drift detector agent
    try:
        if use_agent_system:
            output = run_agent(
                agent_name=agent_name,
                prompt=prompt,
                workspace=workspace,
                project_root=project_root,
            )
        else:
            output = run_llm(llm_cmd=llm_cmd, prompt=prompt, workspace=workspace, label=agent_name)

        # Parse output
        result = _parse_agent_output(agent_name, output, state, workspace)
        result["agent"] = agent_name
        result["output"] = output

        return result

    except Exception as e:
        # Drift detection failure should not block the workflow
        print(f"Warning: Drift detection failed: {e}")
        return {
            "agent": agent_name,
            "content": "",
            "drift_result": {"drift_level": "none", "recommendation": "continue", "error": str(e)},
        }


def _agent_filename(agent_name: str) -> str:
    """Map agent name to template filename."""
    mapping = {
        "planner": "00_planner",
        "researcher": "01_researcher",
        "writer": "02_writer",
        "alignment_reviewer": "02b_alignment_reviewer",
        "value_reviewer": "03_value_reviewer",
        "flow_reviewer": "04_flow_reviewer",
        "ai_tells_reviewer": "05_ai_tells_reviewer",
        "robustness_reviewer": "06_robustness_reviewer",
        "editor": "07_editor",
        "finalizer": "08_finalizer",
        "invariant_reviewer": "09_invariant_reviewer",
        "invariant_extractor": "10_invariant_extractor",
        "condenser": "11_condenser",
        "cutter": "12_cutter",
    }
    return mapping.get(agent_name, agent_name)


def _compute_text_counts(text: str) -> Dict[str, Any]:
    """Compute character and word counts for text.

    This is done by CODE, not LLM - LLMs cannot count accurately.
    """
    char_count = len(text)
    word_count = len(text.split())
    line_count = len(text.splitlines())

    return {
        "characters": char_count,
        "words": word_count,
        "lines": line_count,
    }


def _build_agent_prompt(
    agent_name: str,
    template_path: Path,
    state: Dict[str, Any],
    constraints: str,
) -> str:
    """Build prompt for a specific agent."""
    sections: Dict[str, str] = {}

    if agent_name == "planner":
        sections = {
            "GLOBAL CONSTRAINTS": constraints,
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
            "NOTES": "```markdown\n" + state.get("notes", "") + "\n```",
            "STYLE OVERRIDE": "(none)",
        }
    elif agent_name == "researcher":
        sections = {
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
            "PLAN": "```json\n" + json.dumps(state.get("plan", {}), indent=2, ensure_ascii=False) + "\n```",
            "OUTLINE": "```markdown\n" + state.get("outline", "") + "\n```",
        }
    elif agent_name == "writer":
        sections = {
            "GLOBAL CONSTRAINTS": constraints,
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
            "PLAN": "```json\n" + json.dumps(state.get("plan", {}), indent=2, ensure_ascii=False) + "\n```",
            "OUTLINE": "```markdown\n" + state.get("outline", "") + "\n```",
            "SOURCES": "```json\n" + json.dumps(state.get("sources", {}), indent=2, ensure_ascii=False) + "\n```",
            "NOTES": "```markdown\n" + state.get("notes", "") + "\n```",
            "STYLE OVERRIDE": "(none)",
        }
    elif agent_name == "alignment_reviewer":
        sections = {
            "INPUT_NOTES": "```markdown\n" + state.get("notes", "") + "\n```",
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
        }
    elif agent_name in ("value_reviewer", "robustness_reviewer"):
        sections = {
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
            "PLAN": "```json\n" + json.dumps(state.get("plan", {}), indent=2, ensure_ascii=False) + "\n```",
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
        }
    elif agent_name == "flow_reviewer":
        sections = {
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
            "SKELETON": "```markdown\n" + state.get("skeleton", "") + "\n```",
            "BORDERS": "```markdown\n" + state.get("borders", "") + "\n```",
        }
    elif agent_name == "ai_tells_reviewer":
        sections = {
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
            "LINT REPORT": "```markdown\n" + state.get("lint_md", "") + "\n```",
        }
    elif agent_name == "editor":
        sections = {
            "GLOBAL CONSTRAINTS": constraints,
            "STYLE": "```json\n" + json.dumps(state.get("style", {}), indent=2, ensure_ascii=False) + "\n```",
            "SOURCES": "```json\n" + json.dumps(state.get("sources", {}), indent=2, ensure_ascii=False) + "\n```",
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
        }
        # Add user feedback (HIGHEST PRIORITY)
        user_feedback = state.get("user_feedback", [])
        if user_feedback:
            feedback_text = "\n\n".join([f"- {f['feedback']}" for f in user_feedback])
            sections["USER_FEEDBACK"] = f"**PRIORITY - Address these first:**\n\n{feedback_text}"

        # Add invariant feedback if any
        invariant_feedback = state.get("invariant_feedback", [])
        if invariant_feedback:
            inv_text = "\n".join([f"- {v.get('invariant', 'unknown')}: {v.get('reason', '')}" for v in invariant_feedback])
            sections["INVARIANT_FEEDBACK"] = f"```\n{inv_text}\n```"

        for name, content in state.get("reviews", {}).items():
            sections[f"REVIEW {name}"] = "```markdown\n" + content + "\n```"
    # Multi-pass fixer agents - each gets the draft and their corresponding review
    elif agent_name == "alignment_fixer":
        sections = {
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
            "ALIGNMENT_REVIEW": "```markdown\n" + state.get("reviews", {}).get("alignment.md", "") + "\n```",
            "INPUT_NOTES": "```markdown\n" + state.get("notes", "") + "\n```",
        }
    elif agent_name == "ai_tells_fixer":
        sections = {
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
            "AI_TELLS_REVIEW": "```markdown\n" + state.get("reviews", {}).get("ai_tells.md", "") + "\n```",
            "LINT": "```markdown\n" + state.get("lint_md", "") + "\n```",
        }
    elif agent_name == "flow_fixer":
        sections = {
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
            "FLOW_REVIEW": "```markdown\n" + state.get("reviews", {}).get("flow.md", "") + "\n```",
        }
    elif agent_name == "value_fixer":
        sections = {
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
            "VALUE_REVIEW": "```markdown\n" + state.get("reviews", {}).get("value.md", "") + "\n```",
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
        }
    elif agent_name == "robustness_fixer":
        sections = {
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
            "ROBUSTNESS_REVIEW": "```markdown\n" + state.get("reviews", {}).get("robustness.md", "") + "\n```",
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
        }
    elif agent_name == "finalizer":
        sections = {
            "GLOBAL CONSTRAINTS": constraints,
            "LINT REPORT": "```markdown\n" + state.get("lint_md", "") + "\n```",
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
        }
    elif agent_name == "invariant_extractor":
        sections = {
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
            "PLATFORM": state.get("brief", {}).get("venue", "unknown"),
            "DISCOVERED_REQUIREMENTS": "(none)",  # Could be populated from workflow
        }
    elif agent_name == "invariant_reviewer":
        sections = {
            "DRAFT": state.get("draft", ""),
            "INVARIANTS": "```json\n" + json.dumps(state.get("extracted_invariants", []), indent=2) + "\n```",
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
        }
    elif agent_name == "condenser":
        # Compute counts using CODE (LLMs cannot count accurately)
        draft = state.get("draft", "")
        counts = _compute_text_counts(draft)

        # Get the constraint being violated from workflow state
        length_violations = state.get("length_violations", [])
        constraint = "unknown"
        limit = 0
        unit = "characters"

        if length_violations:
            first_violation = length_violations[0]
            constraint = first_violation.get("invariant", "max_characters")
            # Try to extract the limit from the violation reason
            reason = first_violation.get("reason", "")
            # Parse numbers from reason like "3320 characters exceeds 3000 limit"
            import re
            numbers = re.findall(r'\d+', reason)
            if len(numbers) >= 2:
                limit = int(numbers[1])  # Second number is usually the limit
            elif "max_characters" in constraint.lower():
                # Default LinkedIn limit
                limit = 3000

        # Compute excess
        current = counts["characters"]
        excess = max(0, current - limit) if limit > 0 else 0

        sections = {
            "DRAFT": draft,
            "COUNTS": f"```json\n{json.dumps(counts, indent=2)}\n```",
            "CONSTRAINT": f"{constraint} (limit: {limit} {unit})",
            "EXCESS": f"{excess} {unit} over the limit (current: {current}, limit: {limit})",
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
        }
    elif agent_name == "cutter":
        sections = {
            "DRAFT": state.get("draft", ""),
            "SELECTED_CUTS": "```json\n" + json.dumps(state.get("selected_cuts", []), indent=2) + "\n```",
            "CONDENSER_ANALYSIS": "```json\n" + json.dumps(state.get("condenser_analysis", {}), indent=2) + "\n```",
            "BRIEF": "```json\n" + json.dumps(state.get("brief", {}), indent=2, ensure_ascii=False) + "\n```",
        }
    elif agent_name == "drift_detector":
        sections = {
            "PLAN": "```json\n" + json.dumps(state.get("plan", {}), indent=2, ensure_ascii=False) + "\n```",
            "OUTLINE": "```markdown\n" + state.get("outline", "") + "\n```",
            "DRAFT": "```markdown\n" + state.get("draft", "") + "\n```",
        }

    return build_prompt(template_path, sections)


def _parse_agent_output(
    agent_name: str,
    output: str,
    state: Dict[str, Any],
    workspace: Path,
) -> Dict[str, Any]:
    """Parse agent output and update state."""
    result: Dict[str, Any] = {"type": agent_name}

    if agent_name == "planner":
        plan_json_str = _extract_first_codeblock(output, "json")
        md_outline_str = _extract_first_codeblock(output, "markdown")
        if plan_json_str and md_outline_str:
            state["plan"] = json.loads(plan_json_str)
            state["outline"] = md_outline_str
            state["style"] = state["plan"].get("style", {})
            _dump_json(workspace / "plan.json", state["plan"])
            _write_text(workspace / "outline.md", md_outline_str)
            result["content"] = plan_json_str

    elif agent_name == "researcher":
        sources_json_str = _extract_first_codeblock(output, "json")
        if sources_json_str:
            state["sources"] = json.loads(sources_json_str)
            _dump_json(workspace / "sources.json", state["sources"])
            result["content"] = sources_json_str

    elif agent_name == "writer":
        state["draft"] = output
        _write_text(workspace / "drafts" / "draft_00.md", output)
        result["content"] = output

    elif agent_name.endswith("_reviewer"):
        review_name = agent_name.replace("_reviewer", "") + ".md"
        state.setdefault("reviews", {})[review_name] = output
        _write_text(workspace / "reviews" / review_name, output)
        result["content"] = output

    elif agent_name == "editor":
        cleaned = _clean_article_output(output)
        state["draft"] = cleaned
        _write_text(workspace / "drafts" / "draft_01.md", cleaned)
        result["content"] = cleaned

    # Multi-pass fixer agents - each updates the draft for the next fixer
    elif agent_name.endswith("_fixer"):
        cleaned = _clean_article_output(output)
        state["draft"] = cleaned
        # Save with fixer name suffix so we can track each pass
        fixer_name = agent_name.replace("_fixer", "")
        _write_text(workspace / "drafts" / f"draft_fixed_{fixer_name}.md", cleaned)
        result["content"] = cleaned

    elif agent_name == "finalizer":
        cleaned = _clean_article_output(output)
        state["draft"] = cleaned
        _write_text(workspace / "drafts" / "final.md", cleaned)
        result["content"] = cleaned

    elif agent_name == "invariant_extractor":
        # Parse extracted invariants
        inv_json_str = _extract_first_codeblock(output, "json")
        if inv_json_str:
            try:
                inv_data = json.loads(inv_json_str)
                invariants = inv_data.get("invariants", [])
                state["extracted_invariants"] = invariants
                _dump_json(workspace / "analysis" / "extracted_invariants.json", invariants)
                result["content"] = inv_json_str
                result["extracted_invariants"] = invariants
            except json.JSONDecodeError:
                state["extracted_invariants"] = []
                result["content"] = output

    if agent_name == "invariant_reviewer":
        # Parse invariant review results
        inv_json_str = _extract_first_codeblock(output, "json")
        if inv_json_str:
            try:
                inv_result = json.loads(inv_json_str)
                # Get revised draft if provided
                revised_draft = inv_result.get("revised_draft", "")
                if revised_draft:
                    state["draft"] = revised_draft
                    _write_text(workspace / "drafts" / "draft_invariant_fixed.md", revised_draft)
                # Store result for feedback loop
                result["invariant_result"] = {
                    "checks": inv_result.get("checks", []),
                    "summary": inv_result.get("summary", {}),
                    "unfixable_violations": inv_result.get("unfixable_violations", []),
                }
                _dump_json(workspace / "analysis" / "invariant_review.json", inv_result)
                result["content"] = inv_json_str
            except json.JSONDecodeError:
                result["content"] = output
                result["invariant_result"] = {"unfixable_violations": []}

    if agent_name == "condenser":
        # Parse condenser output for cut candidates
        cond_json_str = _extract_first_codeblock(output, "json")
        if cond_json_str:
            try:
                cond_result = json.loads(cond_json_str)
                state["condenser_analysis"] = cond_result
                _dump_json(workspace / "analysis" / "condenser_analysis.json", cond_result)

                # Build user prompt from condenser question and candidates
                candidates = cond_result.get("candidates", [])
                question = cond_result.get("question", "Which cuts should be applied?")
                recommendation = cond_result.get("recommendation", {})

                # Format options for user
                options = []
                for c in candidates:
                    rec_marker = " [RECOMMENDED]" if c["id"] in recommendation.get("suggested_cuts", []) else ""
                    options.append(f"{c['id']}: {c['description']} (saves ~{c.get('savings', '?')} chars){rec_marker}")

                result["content"] = cond_json_str
                result["user_input_required"] = True
                result["user_prompt"] = question
                result["user_options"] = options
                result["condenser_result"] = cond_result
            except json.JSONDecodeError:
                result["content"] = output
                result["condenser_result"] = {}

    if agent_name == "cutter":
        # Cutter outputs the revised draft directly (no JSON)
        cleaned = _clean_article_output(output)
        state["draft"] = cleaned
        _write_text(workspace / "drafts" / "draft_cut.md", cleaned)
        result["content"] = cleaned

    if agent_name == "drift_detector":
        # Parse drift detection results (JSON output)
        drift_json_str = _extract_first_codeblock(output, "json")
        if drift_json_str:
            try:
                drift_result = json.loads(drift_json_str)
                state["drift_result"] = drift_result
                _dump_json(workspace / "analysis" / "drift_detection.json", drift_result)
                result["content"] = drift_json_str
                result["drift_result"] = drift_result

                # Log drift level for visibility
                drift_level = drift_result.get("drift_level", "none")
                recommendation = drift_result.get("recommendation", "continue")
                if drift_level in ("minor", "significant"):
                    print(f"[Drift Detection] Level: {drift_level}, Recommendation: {recommendation}")
            except json.JSONDecodeError:
                result["content"] = output
                result["drift_result"] = {"drift_level": "none", "recommendation": "continue"}
        else:
            result["content"] = output
            result["drift_result"] = {"drift_level": "none", "recommendation": "continue"}

    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Multi-agent writing workflow with SQLite-backed state tracking."
    )
    ap.add_argument("--input", help="Path to raw notes or a rough draft (markdown).")
    ap.add_argument("--output", help="Path to write the final markdown.")
    ap.add_argument("--brief", default="", help="Optional JSON brief file.")
    ap.add_argument("--style", default="", help="Optional style JSON file (overrides planner style).")
    ap.add_argument("--llm-cmd", help="Optional external LLM command (overrides agent system when provided).")
    ap.add_argument("--no-research", action="store_true", help="Skip the research phase.")
    ap.add_argument("--workspace", default="", help="Workspace directory (for reuse/resume).")
    ap.add_argument("--max-loops", type=int, default=2, help="Max finalizer loops to clear lint failures.")
    ap.add_argument("--resume", metavar="WORKFLOW_ID", help="Resume a paused workflow by ID.")
    ap.add_argument("--db", default="workflow.db", help="SQLite database path.")
    ap.add_argument("--pause-after", metavar="PHASE", help="Pause after specified phase (for testing).")
    ap.add_argument("--response", metavar="TEXT", help="Provide response to pending input request (e.g., 'A,B' for cut selection).")
    ap.add_argument("--enable-drift-detection", action="store_true", help="Enable drift detection after REVISE phase (optional, lightweight check).")
    args = ap.parse_args()

    # Check state machine availability
    if not STATE_MACHINE_AVAILABLE:
        raise SystemExit("State machine dependencies not available. Install: sqlalchemy, pyyaml")

    # Handle resume mode
    if args.resume:
        return run_resume_workflow(args)

    # Validate required args for normal mode
    if not args.input:
        raise SystemExit("--input is required (unless using --resume)")
    if not args.output:
        raise SystemExit("--output is required (unless using --resume)")

    # Run the state machine workflow (default mode)
    return run_state_machine_workflow(args)


if __name__ == "__main__":
    raise SystemExit(main())
