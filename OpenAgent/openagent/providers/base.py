from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from openagent.runtime.messages import AssistantTurn, NormalizedMessage


class ProviderError(RuntimeError):
    """Raised when a provider request fails."""


class LLMProvider(ABC):
    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        messages: list[NormalizedMessage],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> AssistantTurn:
        raise NotImplementedError


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
