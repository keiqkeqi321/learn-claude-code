from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from openagent.providers.base import ProviderError


@dataclass(slots=True)
class ContextWindowUsage:
    used_tokens: int
    max_tokens: int | None = None
    counter_name: str = "estimate"

    @property
    def usage_ratio(self) -> float | None:
        if not self.max_tokens:
            return None
        return self.used_tokens / self.max_tokens

    @property
    def usage_percent(self) -> float | None:
        ratio = self.usage_ratio
        if ratio is None:
            return None
        return ratio * 100.0


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return estimate_payload_tokens("", messages, [])


def estimate_payload_tokens(system_prompt: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    payload = {
        "system": system_prompt,
        "messages": messages,
        "tools": tools,
    }
    return len(json.dumps(payload, ensure_ascii=False, default=str)) // 4


def microcompact(messages: list[dict[str, Any]]) -> None:
    tool_results: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                tool_results.append(item)
    if len(tool_results) <= 3:
        return
    for item in tool_results[:-3]:
        result = item.get("content")
        if isinstance(result, str) and len(result) > 100:
            item["content"] = "[cleared]"


class CompactManager:
    def __init__(self, provider, transcript_store, model_max_tokens: int):
        self.provider = provider
        self.transcript_store = transcript_store
        self.model_max_tokens = model_max_tokens

    def auto_compact(self, session_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.transcript_store.save_snapshot(session_id, messages)
        try:
            summary_turn = self.provider.complete(
                system_prompt="Summarize the conversation for continuity. Preserve decisions, task state, and constraints.",
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(messages, ensure_ascii=False, default=str)[:80_000],
                    }
                ],
                tools=[],
                max_tokens=min(2_000, self.model_max_tokens),
            )
            summary = "\n".join(summary_turn.text_blocks).strip() or "Conversation compacted."
        except ProviderError as exc:
            summary = f"Conversation compacted without model summary due to error: {exc}"
        return [
            {"role": "user", "content": f"[Compressed. Full transcript saved for session {session_id}]\n{summary}"},
            {"role": "assistant", "content": "Understood. Continuing from compacted context."},
        ]
