from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


NormalizedMessage = dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(slots=True)
class AssistantTurn:
    stop_reason: str
    text_blocks: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_response: Any = None

    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def as_message(self) -> NormalizedMessage:
        if not self.tool_calls and len(self.text_blocks) == 1:
            return {"role": "assistant", "content": self.text_blocks[0]}
        blocks: list[dict[str, Any]] = []
        for text in self.text_blocks:
            blocks.append({"type": "text", "text": text})
        for tool_call in self.tool_calls:
            blocks.append(
                {
                    "type": "tool_call",
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.input,
                }
            )
        return {"role": "assistant", "content": blocks}


def make_user_text_message(text: str) -> NormalizedMessage:
    return {"role": "user", "content": text}


def make_tool_result_message(results: list[dict[str, Any]]) -> NormalizedMessage:
    return {"role": "user", "content": results}


def render_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "tool_result":
                    parts.append(str(item.get("content", "")))
        return "\n".join(part for part in parts if part).strip()
    return str(content)
