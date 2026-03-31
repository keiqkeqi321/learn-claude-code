from __future__ import annotations

from typing import Any

from openagent.tools.registry import ToolDefinition

TODO_STATUS_MARKERS = {
    "pending": "☐",
    "in_progress": "⏳",
    "completed": "✅",
}


class TodoManager:
    def update(self, session, items: list[dict[str, Any]]) -> str:
        validated: list[dict[str, str]] = []
        in_progress = 0
        for index, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active_form = str(item.get("activeForm", "")).strip()
            if not content:
                raise ValueError(f"Item {index}: content required")
            if status not in {"pending", "in_progress", "completed"}:
                raise ValueError(f"Item {index}: invalid status '{status}'")
            if not active_form:
                raise ValueError(f"Item {index}: activeForm required")
            if status == "in_progress":
                in_progress += 1
            validated.append(
                {
                    "content": content,
                    "status": status,
                    "activeForm": active_form,
                }
            )
        if len(validated) > 20:
            raise ValueError("Max 20 todos")
        if in_progress > 1:
            raise ValueError("Only one in_progress allowed")
        session.todo_items = validated
        return self.render(session)

    def render(self, session) -> str:
        if not session.todo_items:
            return "No todos."
        lines: list[str] = []
        done = 0
        for item in session.todo_items:
            marker = TODO_STATUS_MARKERS.get(item["status"], "•")
            if item["status"] == "completed":
                done += 1
            suffix = f" <- {item['activeForm']}" if item["status"] == "in_progress" else ""
            lines.append(f"{marker} {item['content']}{suffix}")
        lines.append(f"\n({done}/{len(session.todo_items)} completed)")
        return "\n".join(lines)

    def has_open_items(self, session) -> bool:
        return any(item.get("status") != "completed" for item in session.todo_items)


def register_todo_tool(registry, todo_manager: TodoManager) -> None:
    def handler(ctx: Any, payload: dict[str, Any]) -> str:
        return todo_manager.update(ctx.session, payload["items"])

    registry.register(
        ToolDefinition(
            name="TodoWrite",
            description="Update the short-lived todo checklist for the current session.",
            input_schema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                                "activeForm": {"type": "string"},
                            },
                            "required": ["content", "status", "activeForm"],
                        },
                    }
                },
                "required": ["items"],
            },
            handler=handler,
        )
    )
