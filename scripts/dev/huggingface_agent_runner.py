"""CLI to run HuggingFace sub-agents defined in .huggingface/agents/.

Parses YAML frontmatter from an agent markdown file and invokes transformers
models directly for inference.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from transformers import PreTrainedModel, PreTrainedTokenizer


# Configure logging
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed namespace with agent name and prompt.
    """
    parser = argparse.ArgumentParser(
        description="Run a HuggingFace sub-agent defined in .huggingface/agents"
    )
    parser.add_argument(
        "--agent",
        required=True,
        type=str,
        help="Name of the HuggingFace agent to run",
    )
    parser.add_argument(
        "--prompt",
        required=True,
        type=str,
        help="Prompt to pass to the agent",
    )
    return parser.parse_args()


def load_agent(agent_name: str) -> tuple[dict[str, Any], str]:
    """Load agent configuration and system prompt from markdown file.

    Args:
        agent_name: Name of the agent (without .md extension).

    Returns:
        Tuple of (frontmatter dict, system_prompt string).

    Raises:
        FileNotFoundError: If agent file not found.
        ValueError: If frontmatter is invalid YAML, not a dict, or generation_config
            is present but not a dict.
        KeyError: If required frontmatter fields are missing.
    """
    project_root = Path(__file__).resolve().parents[2]
    agent_path = project_root / ".huggingface" / "agents" / f"{agent_name}.md"

    try:
        content = agent_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - path error case
        raise FileNotFoundError(f"Agent '{agent_name}' not found in .huggingface/agents/") from exc

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Invalid frontmatter in agent file")

    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise ValueError("Invalid YAML frontmatter") from exc

    if not isinstance(frontmatter, dict):
        raise TypeError("Invalid frontmatter in agent file")

    if "model" not in frontmatter:
        raise KeyError("Missing required frontmatter field: model")

    if "generation_config" in frontmatter and not isinstance(
        frontmatter["generation_config"], dict
    ):
        raise ValueError("generation_config must be a dict")

    system_prompt = parts[2].strip()
    return frontmatter, system_prompt


def load_model(model_name: str) -> tuple[PreTrainedModel, PreTrainedTokenizer]:
    """Load HuggingFace model and tokenizer.

    Args:
        model_name: HuggingFace model name (e.g., 'mistralai/Ministral-3B-Instruct-2412').

    Returns:
        Tuple of (model, tokenizer).

    Raises:
        RuntimeError: If model loading fails.
    """
    try:
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
        )

        logger.info("Loading model: %s", model_name)
        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)  # type: ignore[no-untyped-call]
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            trust_remote_code=True,
            device_map="auto",
        )
        model.eval()  # type: ignore[no-untyped-call]
        logger.info("Model loaded successfully")
    except Exception as e:
        raise RuntimeError(f"Failed to load model '{model_name}': {e}") from e
    else:
        return model, tokenizer


def run_inference(
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
    prompt: str,
    generation_config: dict[str, Any],
) -> str:
    """Run inference with the loaded model.

    Args:
        model: The loaded HuggingFace model.
        tokenizer: The loaded tokenizer.
        prompt: The full prompt to send to the model.
        generation_config: Generation configuration from frontmatter.

    Returns:
        Generated text from the model.

    Raises:
        RuntimeError: If inference fails.
    """
    try:
        import torch

        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4096)

        # Move inputs to same device as model
        device = next(model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        # Build generation kwargs with defaults
        generation_kwargs: dict[str, Any] = {
            "max_new_tokens": generation_config.get("max_new_tokens", 2048),
            "temperature": generation_config.get("temperature", 0.1),
            "do_sample": generation_config.get("do_sample", True),
            "pad_token_id": tokenizer.eos_token_id,
        }

        # Add any additional config options
        for key, value in generation_config.items():
            if key not in generation_kwargs:
                generation_kwargs[key] = value

        with torch.no_grad():
            outputs = model.generate(**inputs, **generation_kwargs)  # type: ignore[operator]

        # Decode response
        response: str = tokenizer.decode(outputs[0], skip_special_tokens=True)

        # Extract generated portion by removing the prompt prefix if present
        if prompt in response:
            response = response[len(prompt) :].strip()
        return response
    except Exception as e:
        raise RuntimeError(f"Inference failed: {e}") from e


def build_prompt(system_prompt: str, user_prompt: str) -> str:
    """Combine system prompt and user prompt for instruction-following models.

    Args:
        system_prompt: The agent's system prompt from the markdown file.
        user_prompt: The user-provided prompt.

    Returns:
        Combined prompt string suitable for instruction-following models.
    """
    return f"{system_prompt}\n\nUser: {user_prompt}\n\nAssistant:"


def main() -> int:
    """Run the HuggingFace agent runner.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        args = parse_args()
        frontmatter, system_prompt = load_agent(args.agent)

        model_name = frontmatter["model"]
        generation_config = frontmatter.get("generation_config", {})

        logger.info("Loading agent '%s' with model '%s'", args.agent, model_name)
        model, tokenizer = load_model(model_name)

        full_prompt = build_prompt(system_prompt, args.prompt)
        logger.info("Running inference...")

        output = run_inference(model, tokenizer, full_prompt, generation_config)
        sys.stdout.write(output)
    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except KeyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except Exception as exc:  # pragma: no cover - defensive catch-all
        sys.stderr.write(f"{exc}\n")
        return 1
    else:
        return 0


if __name__ == "__main__":
    sys.exit(main())
