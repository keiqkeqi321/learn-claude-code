"""文件系统工具模块.

提供文件读写、编辑等操作的工具函数。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openagent.tools.registry import ToolDefinition


def safe_path(workspace_root: Path, relative_path: str) -> Path:
    """解析并验证路径安全性.

    Args:
        workspace_root: 工作空间根目录。
        relative_path: 相对路径。

    Returns:
        解析后的绝对路径。

    Raises:
        ValueError: 如果路径尝试逃逸工作空间。
    """
    path = (workspace_root / relative_path).resolve()
    if not path.is_relative_to(workspace_root):
        raise ValueError(f"Path escapes workspace: {relative_path}")
    return path


def read_file(ctx: Any, payload: dict[str, Any]) -> str:
    """读取文件内容.

    Args:
        ctx: 运行时上下文对象。
        payload: 包含 "path" 和可选 "limit" 的参数字典。

    Returns:
        文件内容字符串。
    """
    path = safe_path(ctx.runtime.settings.workspace_root, payload["path"])
    limit = payload.get("limit")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if limit and limit < len(lines):
        lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
    return "\n".join(lines)[: ctx.runtime.settings.runtime.max_tool_output_chars]


def write_file(ctx: Any, payload: dict[str, Any]) -> str:
    path = safe_path(ctx.runtime.settings.workspace_root, payload["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = str(payload["content"])
    path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} bytes to {payload['path']}"


def edit_file(ctx: Any, payload: dict[str, Any]) -> str:
    path = safe_path(ctx.runtime.settings.workspace_root, payload["path"])
    old_text = str(payload["old_text"])
    new_text = str(payload["new_text"])
    content = path.read_text(encoding="utf-8")
    if old_text not in content:
        return f"Error: Text not found in {payload['path']}"
    path.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
    return f"Edited {payload['path']}"


def register_filesystem_tools(registry) -> None:
    registry.register(
        ToolDefinition(
            name="read_file",
            description="Read file contents.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
            handler=read_file,
        )
    )
    registry.register(
        ToolDefinition(
            name="write_file",
            description="Write content to a file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=write_file,
        )
    )
    registry.register(
        ToolDefinition(
            name="edit_file",
            description="Replace exact text in a file once.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            handler=edit_file,
        )
    )
