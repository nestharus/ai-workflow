"""Structured output agent runner using direct SDK calls."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from scripts.agents.config import load_agents

_MODEL_MAP: dict[str, dict[str, str]] = {
    "glm": {"provider": "openai", "model": "cerebras/llama3.1-8b"},
    "gpt-5.2-xhigh": {"provider": "openai", "model": "gpt-4o"},
    "claude-opus": {"provider": "anthropic", "model": "claude-opus-4-20250514"},
}

_CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"


def run_structured_agent(
    agent_name: str,
    prompt: str,
    schema: type[BaseModel],
    workspace: Path,
) -> BaseModel:
    """Run an agent with structured output enforcement."""
    agents = load_agents(workspace / ".agents/agents")
    agent = agents.get(agent_name)
    if agent is None:
        raise RuntimeError(f"Structured agent not found: {agent_name}")
    if not agent.model:
        raise RuntimeError(f"Structured agent missing model: {agent_name}")

    model_config = _MODEL_MAP.get(agent.model)
    if model_config is None:
        raise RuntimeError(f"Structured model mapping missing for: {agent.model}")

    full_prompt = f"{agent.instructions}\n\n{prompt}".strip()
    provider = model_config["provider"]
    model = model_config["model"]

    if provider == "openai":
        return _run_openai_structured(model, full_prompt, schema)
    if provider == "anthropic":
        return _run_anthropic_structured(model, full_prompt, schema)

    raise RuntimeError(f"Unsupported structured provider: {provider}")


def _get_api_credentials() -> dict[str, str]:
    """Load API credentials from the environment."""
    return {
        "openai": os.getenv("OPENAI_API_KEY", "").strip(),
        "anthropic": os.getenv("ANTHROPIC_API_KEY", "").strip(),
        "cerebras": os.getenv("CEREBRAS_API_KEY", "").strip(),
    }


def _run_openai_structured(
    model: str,
    prompt: str,
    schema: type[BaseModel],
) -> BaseModel:
    """Run OpenAI-compatible structured output generation."""
    from openai import OpenAI

    schema_payload = {
        "name": schema.__name__,
        "schema": schema.model_json_schema(),
    }

    credentials = _get_api_credentials()
    if model.startswith("cerebras/"):
        api_key = credentials.get("cerebras") or credentials.get("openai")
        base_url = _CEREBRAS_BASE_URL
        provider_label = "cerebras"
    else:
        api_key = credentials.get("openai")
        base_url = None
        provider_label = "openai"

    if not api_key:
        raise RuntimeError(f"Missing {provider_label} API key for structured output.")

    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    for attempt in range(3):
        try:
            response = client.responses.create(
                model=model,
                input=[{"role": "user", "content": prompt}],
                response_format={"type": "json_schema", "json_schema": schema_payload},
            )
            payload = _extract_openai_text(response)
            return schema.model_validate_json(payload)
        except (ValidationError, ValueError) as exc:
            raise ValueError(f"Schema validation failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive retry handling
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(
                f"OpenAI structured output failed (provider={provider_label}): {exc}"
            ) from exc

    raise RuntimeError(f"OpenAI structured output failed (provider={provider_label}).")


def _extract_openai_text(response: Any) -> str:
    if getattr(response, "output_text", None):
        return response.output_text

    chunks: list[str] = []
    for output in getattr(response, "output", []) or []:
        for content in getattr(output, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(text)
    return "".join(chunks).strip()


def _run_anthropic_structured(
    model: str,
    prompt: str,
    schema: type[BaseModel],
) -> BaseModel:
    """Run Anthropic structured output generation via tool use."""
    from anthropic import Anthropic

    credentials = _get_api_credentials()
    api_key = credentials.get("anthropic")
    if not api_key:
        raise RuntimeError("Missing anthropic API key for structured output.")

    client = Anthropic(api_key=api_key)
    tool_name = "structured_output"

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                tools=[
                    {
                        "name": tool_name,
                        "description": "Return structured output.",
                        "input_schema": schema.model_json_schema(),
                    }
                ],
                tool_choice={"type": "tool", "name": tool_name},
            )
            tool_payload = _extract_anthropic_tool_payload(response, tool_name)
            return schema.model_validate(tool_payload)
        except (ValidationError, ValueError) as exc:
            raise ValueError(f"Schema validation failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive retry handling
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Anthropic structured output failed: {exc}") from exc

    raise RuntimeError("Anthropic structured output failed.")


def _extract_anthropic_tool_payload(response: Any, tool_name: str) -> dict[str, Any]:
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) != "tool_use":
            continue
        if getattr(block, "name", None) != tool_name:
            continue
        payload = getattr(block, "input", None)
        if isinstance(payload, dict):
            return payload
    raise RuntimeError("Anthropic response missing tool payload.")
