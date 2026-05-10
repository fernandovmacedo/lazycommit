"""OpenRouter client helpers and token-usage accounting."""

from __future__ import annotations

from typing import Any

import instructor
import litellm
from pydantic import BaseModel

litellm.suppress_debug_info = True  # Silence the LiteLLM startup banner.


class UsageStats:
    """Mutable container for usage and cost data from model calls."""

    def __init__(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float | None = None,
        cached_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.cost = cost
        self.cached_tokens = cached_tokens
        self.reasoning_tokens = reasoning_tokens

    def _fmt_int(self, value: int) -> str:
        return f"{value:,}"

    def format_cost(self) -> str | None:
        if self.cost is None:
            return None
        return f"${self.cost:.5f}"

    def format_tokens(self) -> str:
        return (
            "total="
            f"{self._fmt_int(self.total_tokens)} "
            f"input={self._fmt_int(self.prompt_tokens)} "
            f"(+ {self._fmt_int(self.cached_tokens)} cached) "
            f"output={self._fmt_int(self.completion_tokens)} "
            f"(reasoning {self._fmt_int(self.reasoning_tokens)})"
        )

    def add(self, other: UsageStats | None) -> None:
        if other is None:
            return
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens = self.prompt_tokens + self.completion_tokens
        self.cached_tokens += other.cached_tokens
        self.reasoning_tokens += other.reasoning_tokens
        if self.cost is not None or other.cost is not None:
            self.cost = (self.cost or 0.0) + (other.cost or 0.0)


def _get_detail(obj: object, key: str) -> int:
    """Read a usage detail from either an object or a dict payload."""
    val = obj.get(key, 0) if isinstance(obj, dict) else getattr(obj, key, 0)
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _extract_usage_stats(response: Any) -> UsageStats | None:
    """Extract usage statistics from a LiteLLM completion response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None

    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0

    # LiteLLM stores cost in _hidden_params rather than in usage.
    hidden = getattr(response, "_hidden_params", {})
    cost: float | None = hidden.get("response_cost") if hidden else None

    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)

    cached_tokens = 0
    if prompt_details is not None:
        cached_tokens = _get_detail(prompt_details, "cached_tokens")

    reasoning_tokens = 0
    if completion_details is not None:
        reasoning_tokens = _get_detail(completion_details, "reasoning_tokens")

    return UsageStats(
        prompt_tokens,
        completion_tokens,
        cost,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def generate_commit_json(
    api_key: str,
    model: str,
    reasoning_effort: str,
    system_prompt: str,
    response_model: type[BaseModel],
    user_context: str,
    timeout: float,
) -> tuple[BaseModel, UsageStats | None]:
    """Generate structured commit data through OpenRouter."""
    client = instructor.from_litellm(
        litellm.completion,
        mode=instructor.Mode.OPENROUTER_STRUCTURED_OUTPUTS,
    )
    commit_msg, completion = client.chat.completions.create_with_completion(
        model=f"openrouter/{model}",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_context},
        ],
        response_model=response_model,
        temperature=0.2,
        timeout=timeout,
        max_retries=1,
        api_key=api_key,
        api_base="https://openrouter.ai/api/v1",
        extra_body={
            "plugins": [{"id": "web", "enabled": False}],
            "reasoning": {"effort": reasoning_effort},
        },
    )
    return commit_msg, _extract_usage_stats(completion)
