"""Model-specific agent wrappers for optimized spec refinement.

This module provides wrappers for different LLM models that optimize
prompts and handle outputs according to each model's strengths and weaknesses.

Model characteristics:
- GLM 4.7: Small tasks, poor instructions, good summarization
- Opus: Good intent, sloppy details - use for library synthesis, architecture
- GPT: Good synthesis, poor intent - use for audits, reviews, spec synthesis
"""

from spec_manager.refinement.wrappers.glm_wrapper import (
    GLMWrapper,
    GLM_TASK_SIZE_LIMITS,
    simplify_prompt_for_glm,
)
from spec_manager.refinement.wrappers.gpt_wrapper import (
    GPTWrapper,
    GPT_STRICT_OUTPUT_FORMATS,
)
from spec_manager.refinement.wrappers.opus_wrapper import (
    OpusWrapper,
    OPUS_PREFERRED_TASKS,
)
from spec_manager.refinement.wrappers.token_manager import (
    TokenManager,
    TokenBudget,
    estimate_tokens,
)

__all__ = [
    "GLMWrapper",
    "GLM_TASK_SIZE_LIMITS",
    "GPTWrapper",
    "GPT_STRICT_OUTPUT_FORMATS",
    "OpusWrapper",
    "OPUS_PREFERRED_TASKS",
    "TokenBudget",
    "TokenManager",
    "estimate_tokens",
    "simplify_prompt_for_glm",
]
