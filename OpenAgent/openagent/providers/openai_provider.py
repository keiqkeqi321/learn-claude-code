from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from openagent.config.models import ProviderSettings
from openagent.providers.base import LLMProvider, ProviderError, TextCallback
from openagent.runtime.messages import AssistantTurn, ToolCall


def _schema_to_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        content = message["content"]
        if isinstance(content, str):
            converted.append({"role": role, "content": content})
            continue
        text_parts: list[str] = []
        tool_results: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        for item in content:
            if item["type"] == "text":
                text_parts.append(str(item.get("text", "")))
            elif item["type"] == "tool_result":
                tool_results.append(item)
            elif item["type"] == "tool_call":
                tool_calls.append(
                    {
                        "id": item["id"],
                        "type": "function",
                        "function": {
                            "name": item["name"],
                            "arguments": json.dumps(item.get("input", {}), ensure_ascii=False),
                        },
                    }
                )
        if role == "assistant":
            converted.append(
                {
                    "role": "assistant",
                    "content": "\n".join(part for part in text_parts if part) or "",
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                }
            )
            continue
        if text_parts:
            converted.append({"role": role, "content": "\n".join(text_parts)})
        for tool_result in tool_results:
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_result["tool_call_id"],
                    "content": str(tool_result.get("content", "")),
                }
            )
    return converted


class OpenAIProvider(LLMProvider):
    def __init__(self, settings: ProviderSettings):
        self.settings = settings

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        text_callback: TextCallback | None = None,
    ) -> AssistantTurn:
        url = f"{self.settings.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.model,
            "messages": [{"role": "system", "content": system_prompt}] + _to_openai_messages(messages),
            "tools": [_schema_to_openai_tool(tool) for tool in tools],
            "tool_choice": "auto",
            "max_tokens": max_tokens,
            "stream": bool(text_callback),
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.organization:
            headers["OpenAI-Organization"] = self.settings.organization
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                if text_callback is None:
                    body = json.loads(response.read().decode("utf-8"))
                else:
                    body = self._read_streaming_response(response, text_callback)
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"OpenAI request failed: {exc.code} {details}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc

        choice = body["choices"][0]
        message = choice["message"]
        text_blocks: list[str] = []
        content = message.get("content")
        if isinstance(content, str) and content:
            text_blocks.append(content)
        elif isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    text_blocks.append(item.get("text", ""))
        tool_calls = [
            ToolCall(
                id=tool_call["id"],
                name=tool_call["function"]["name"],
                input=json.loads(tool_call["function"].get("arguments") or "{}"),
            )
            for tool_call in message.get("tool_calls", [])
        ]
        stop_reason = choice.get("finish_reason") or "stop"
        if stop_reason == "tool_calls":
            stop_reason = "tool_use"
        elif stop_reason == "stop":
            stop_reason = "end_turn"
        return AssistantTurn(
            stop_reason=stop_reason,
            text_blocks=text_blocks,
            tool_calls=tool_calls,
            raw_response=body,
        )

    def _read_streaming_response(self, response, text_callback: TextCallback) -> dict[str, Any]:
        aggregated_message: dict[str, Any] = {"role": "assistant", "content": "", "tool_calls": []}
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"

        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            choice = event["choices"][0]
            delta = choice.get("delta", {})
            finish_reason = choice.get("finish_reason") or finish_reason

            content = delta.get("content")
            if isinstance(content, str) and content:
                aggregated_message["content"] += content
                text_callback(content)
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        text = item.get("text", "")
                        if text:
                            aggregated_message["content"] += text
                            text_callback(text)

            for tool_delta in delta.get("tool_calls", []):
                index = int(tool_delta.get("index", 0))
                current = tool_calls_by_index.setdefault(
                    index,
                    {
                        "id": tool_delta.get("id", ""),
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if tool_delta.get("id"):
                    current["id"] = tool_delta["id"]
                function_delta = tool_delta.get("function", {})
                if function_delta.get("name"):
                    current["function"]["name"] = function_delta["name"]
                if function_delta.get("arguments"):
                    current["function"]["arguments"] += function_delta["arguments"]

        aggregated_message["tool_calls"] = [tool_calls_by_index[index] for index in sorted(tool_calls_by_index)]
        return {
            "choices": [
                {
                    "message": aggregated_message,
                    "finish_reason": finish_reason,
                }
            ]
        }
