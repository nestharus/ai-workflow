"""Workflow context index.

Re-exports ContextIndex and ContextIndexBuilder from core.context_index
for use by workflow modules.
"""

from __future__ import annotations

from spec_manager.core.context_index import ContextIndex, ContextIndexBuilder

__all__ = ["ContextIndex", "ContextIndexBuilder"]
