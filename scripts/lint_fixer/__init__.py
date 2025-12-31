"""Lint fixer orchestration module.

This module provides CLI tooling for running linters and invoking the lint-fixer
agent to fix errors iteratively.
"""

from scripts.lint_fixer.orchestrator import orchestrate

__all__ = ["orchestrate"]
