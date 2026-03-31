from __future__ import annotations

import subprocess
from typing import Any

from openagent.tools.process import run_command
from openagent.tools.registry import ToolDefinition

DANGEROUS_SNIPPETS = [
    "rm -rf /",
    "sudo ",
    " shutdown",
    " reboot",
    "mkfs",
    "format ",
]


def run_shell(ctx: Any, payload: dict[str, Any]) -> str:
    command = str(payload["command"])
    lowered = f" {command.lower()} "
    if any(snippet in lowered for snippet in DANGEROUS_SNIPPETS):
        return "Error: Dangerous command blocked"
    try:
        completed = run_command(
            command,
            shell=True,
            cwd=ctx.runtime.settings.workspace_root,
            timeout=int(payload.get("timeout", ctx.runtime.settings.runtime.command_timeout_seconds)),
        )
    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({ctx.runtime.settings.runtime.command_timeout_seconds}s)"
    output = completed.combined_output().strip() or "(no output)"
    return output[: ctx.runtime.settings.runtime.max_tool_output_chars]


def register_shell_tool(registry) -> None:
    registry.register(
        ToolDefinition(
            name="bash",
            description="Run a shell command inside the workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer"},
                },
                "required": ["command"],
            },
            handler=run_shell,
        )
    )
