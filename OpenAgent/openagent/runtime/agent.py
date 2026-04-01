"""Agent 运行时模块.

提供 OpenAgent 的核心运行时功能，包括：
- LLM 提供者管理
- 工具注册和执行
- 会话管理
- 子代理运行
- 后台任务管理
"""

from __future__ import annotations

import difflib
import json
import platform
import sys
import uuid
from pathlib import Path
from typing import Any

from openagent.collaboration.bus import MessageBus
from openagent.collaboration.protocols import RequestTracker
from openagent.config.models import AppSettings, ProviderProfileSettings, ProviderSettings
from openagent.config.settings import persist_provider_selection
from openagent.mcp.registry import MCPRegistry
from openagent.providers.anthropic_provider import AnthropicProvider
from openagent.providers.base import LLMProvider
from openagent.providers.openai_provider import OpenAIProvider
from openagent.runtime.compact import CompactManager, estimate_tokens, microcompact
from openagent.runtime.execution_mode import (
    AUTHORIZATION_TOOL_NAME,
    DEFAULT_EXECUTION_MODE,
    MODE_SWITCH_TOOL_NAME,
    NON_YOLO_EXECUTION_MODES,
    normalize_execution_mode,
    execution_mode_spec,
    tool_block_message,
)
from openagent.runtime.events import ToolExecutionContext
from openagent.runtime.messages import make_tool_result_message, make_user_text_message
from openagent.runtime.session import AgentSession, SessionManager
from openagent.runtime.teammate import TeammateRuntimeManager
from openagent.skills.loader import SkillLoader
from openagent.storage.inbox import InboxStore
from openagent.storage.jobs import JobStore
from openagent.storage.sessions import SessionStore
from openagent.storage.common import atomic_write_text, read_json, write_json
from openagent.storage.tasks import TaskStore
from openagent.storage.team import TeamStore
from openagent.storage.tool_logs import ToolLogStore
from openagent.storage.transcripts import TranscriptStore
from openagent.tools.background import BackgroundManager, register_background_tools
from openagent.tools.filesystem import edit_file, read_file, register_filesystem_tools, write_file
from openagent.tools.mcp import register_mcp_tools
from openagent.tools.registry import ToolDefinition, ToolRegistry
from openagent.tools.shell import register_shell_tool
from openagent.tools.subagent import register_subagent_tool
from openagent.tools.tasks import register_task_tools
from openagent.tools.team import register_team_tools
from openagent.tools.todo import TodoManager, register_todo_tool


class TurnInterrupted(RuntimeError):
    pass


class OpenAgentRuntime:
    TOOL_VALUE_PREVIEW_CHARS = 90
    TOOL_RESULT_PREVIEW_CHARS = 60
    SILENT_TOOL_NAMES = {"TodoWrite"}
    MAX_UNDO_TURNS = 10
    TURN_BOUNDARY_TOOL_NAMES = {AUTHORIZATION_TOOL_NAME, MODE_SWITCH_TOOL_NAME}
    WORKSPACE_PERMISSIONS_FILE = "permissions.json"
    _ansi_output_enabled: bool | None = None
    DEFAULT_SYSTEM_PROMPT_TEMPLATE = (
        "You are {name}, a top-rated AI assistant.\n"
        "You are exceptionally strong at coding tasks, software design, debugging, implementation, and complex reasoning.\n"
        "You solve problems with clear, defensible thinking, strong technical judgment, and careful tool use.\n"
        "Be precise, pragmatic, and direct. Prefer concrete actions over vague advice.\n"
        "When needed, inspect the workspace and use tools to verify assumptions before acting."
    )

    """OpenAgent 运行时类.

    管理代理的完整运行时环境，包括工具、会话、任务等。

    Attributes:
        settings: 应用配置。
        provider: LLM 提供者。
        transcript_store: 转录存储。
        session_manager: 会话管理器。
        task_store: 任务存储。
        job_store: 后台任务存储。
        inbox_store: 收件箱存储。
        bus: 消息总线。
        team_store: 团队存储。
        request_tracker: 请求跟踪器。
        skill_loader: 技能加载器。
        todo_manager: 待办事项管理器。
        background_manager: 后台任务管理器。
        compact_manager: 压缩管理器。
        mcp_registry: MCP 注册表。
        team_manager: 团队管理器。
        registry: 主工具注册表。
        worker_registry: 工作器工具注册表。
    """

    def __init__(self, settings: AppSettings) -> None:
        """初始化 OpenAgent 运行时.

        Args:
            settings: 应用配置对象。
        """
        self.settings = settings
        self.execution_mode = DEFAULT_EXECUTION_MODE
        self.authorization_request_handler = None
        self.mode_switch_request_handler = None
        self._workspace_authorized_tools = self._load_workspace_authorizations()
        self._once_authorized_tools: dict[str, int] = {}
        self.provider = self._make_provider()
        self.transcript_store = TranscriptStore(settings.storage.transcripts_dir)
        self.session_manager = SessionManager(SessionStore(settings.storage.sessions_dir), self.transcript_store)
        self.task_store = TaskStore(settings.storage.tasks_dir)
        self.job_store = JobStore(settings.storage.jobs_dir)
        self.tool_log_store = ToolLogStore(settings.storage.logs_dir)
        self.inbox_store = InboxStore(settings.storage.inbox_dir)
        self.bus = MessageBus(self.inbox_store)
        self.team_store = TeamStore(settings.storage.team_dir)
        self.request_tracker = RequestTracker(settings.storage.requests_dir)
        self.skill_loader = SkillLoader(settings.workspace_root / "skills")
        self.todo_manager = TodoManager()
        self.background_manager = BackgroundManager(
            self.job_store,
            settings.workspace_root,
            settings.runtime.command_timeout_seconds,
            settings.runtime.max_tool_output_chars,
        )
        self.compact_manager = CompactManager(self.provider, self.transcript_store, settings.provider.max_tokens)
        self.mcp_registry = MCPRegistry(settings.mcp_servers)
        self.team_manager = TeammateRuntimeManager(
            runtime=self,
            team_store=self.team_store,
            bus=self.bus,
            task_store=self.task_store,
            request_tracker=self.request_tracker,
        )
        self.registry = ToolRegistry()
        self.worker_registry = ToolRegistry()
        self._register_core_tools(self.registry)
        self.register_worker_tools(self.worker_registry)

    def print_tool_event(self, actor: str, tool_name: str, tool_input: dict[str, Any], output: Any) -> str:
        category = "MCP" if tool_name.startswith("mcp__") else "TOOL"
        log_entry = self.tool_log_store.write(
            actor=actor,
            tool_name=tool_name,
            tool_input=tool_input,
            output=output,
            category=category,
        )
        if tool_name in self.SILENT_TOOL_NAMES:
            return log_entry["id"]
        if not sys.stdout.isatty():
            return log_entry["id"]
        print()
        for line in self.render_tool_event_lines(tool_name, tool_input, output, log_id=log_entry["id"]):
            print(line)
        print()
        return log_entry["id"]

    def render_tool_event_lines(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        output: Any,
        *,
        log_id: str | None = None,
    ) -> list[str]:
        if self._is_file_change_event(tool_name, output):
            return self._render_file_change_event_lines(tool_name, tool_input, output, log_id=log_id)
        lines = [self._format_tool_heading(tool_name, tool_input, output)]
        lines.extend(self._format_tool_result_lines(tool_name, tool_input, output, log_id))
        return lines

    def _format_tool_heading(self, tool_name: str, tool_input: dict[str, Any], output: Any) -> str:
        return f"{self._tool_bullet(output)} {self._tool_title(tool_name, tool_input, output)}"

    def _tool_bullet(self, output: Any) -> str:
        failed = self._tool_event_failed(output)
        bullet = "\u25cf"
        if self._supports_ansi_output():
            color = "\x1b[31m" if failed else "\x1b[32m"
            bullet = f"{color}{bullet}\x1b[0m"
        return bullet

    def _tool_title(self, tool_name: str, tool_input: dict[str, Any], output: Any) -> str:
        if tool_name == "bash":
            command = self._compact_preview(str(tool_input.get("command", "")).strip(), limit=140)
            return f"Bash({command or '(no command)'})"
        if tool_name == "read_file":
            path = str(tool_input.get("path", "")).strip() or "(unknown path)"
            return f"Read({path})"
        if tool_name == AUTHORIZATION_TOOL_NAME:
            target = str(tool_input.get("tool_name", "")).strip() or "tool"
            return f"Authorize({target})"
        if tool_name == MODE_SWITCH_TOOL_NAME:
            target_mode = str(tool_input.get("target_mode", "")).strip() or "mode"
            return f"SwitchMode({target_mode})"
        if tool_name.startswith("mcp__"):
            return self._format_mcp_title(tool_name, tool_input)
        name = self._prettify_tool_name(tool_name)
        args_preview = self._format_tool_args_preview(tool_input)
        if args_preview:
            return f"{name}({args_preview})"
        return name

    def _format_mcp_title(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        parts = tool_name.split("__")
        if len(parts) >= 3:
            server = parts[1]
            tool = parts[2]
            args_preview = self._format_tool_args_preview(tool_input, limit=70)
            if args_preview:
                return f"{server}.{tool}({args_preview})"
            return f"{server}.{tool}"
        return tool_name

    def _prettify_tool_name(self, tool_name: str) -> str:
        words = [part for part in str(tool_name).replace("__", "_").split("_") if part]
        if not words:
            return tool_name
        return "".join(word.capitalize() for word in words)

    def _format_tool_args_preview(self, tool_input: dict[str, Any], *, limit: int = 96) -> str:
        if not isinstance(tool_input, dict) or not tool_input:
            return ""
        parts: list[str] = []
        for key, value in tool_input.items():
            if key in {"content", "old_text", "new_text"}:
                continue
            rendered = self._compact_preview(self._stringify_tool_value(value), limit=40)
            parts.append(f"{key}={rendered}")
        preview = ", ".join(parts)
        return self._compact_preview(preview, limit=limit)

    def _format_tool_result_lines(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        output: Any,
        log_id: str | None,
    ) -> list[str]:
        summary = self._tool_result_summary(tool_name, tool_input, output)
        lines = self._prefixed_result_block(summary)
        if log_id and self._tool_result_needs_log_hint(tool_name, tool_input, output):
            lines.append(f"     Log: {self._format_tool_log_path(log_id)}")
        return lines

    def _tool_result_summary(self, tool_name: str, tool_input: dict[str, Any], output: Any) -> str:
        limit = self.TOOL_RESULT_PREVIEW_CHARS
        if tool_name == "bash":
            return self._compact_preview(self._stringify_tool_value(output), limit=limit) or "(no output)"
        if isinstance(output, dict):
            if "message" in output and str(output.get("message", "")).strip():
                return self._compact_preview(str(output.get("message", "")).strip(), limit=limit) or "(no output)"
            if "reason" in output and str(output.get("reason", "")).strip():
                return self._compact_preview(str(output.get("reason", "")).strip(), limit=limit) or "(no output)"
            status = str(output.get("status", "")).strip()
            if status and status not in {"ok", "success", "approved"}:
                return self._compact_preview(self._stringify_tool_value(output), limit=limit) or "(no output)"
        return self._compact_preview(self._stringify_tool_value(output), limit=limit) or "(no output)"

    def _tool_result_needs_log_hint(self, tool_name: str, tool_input: dict[str, Any], output: Any) -> bool:
        args_text = self._stringify_tool_value(tool_input)
        result_text = self._stringify_tool_value(output)
        _, args_hidden = self._preview_tool_text(args_text, limit=160)
        _, result_hidden = self._preview_tool_text(result_text, limit=self.TOOL_RESULT_PREVIEW_CHARS)
        return args_hidden or result_hidden

    def _prefixed_result_block(self, text: str) -> list[str]:
        lines = (text or "(no output)").splitlines() or ["(no output)"]
        formatted: list[str] = []
        for index, line in enumerate(lines):
            prefix = "  \u23bf  " if index == 0 else "     "
            formatted.append(prefix + line)
        return formatted

    def _tool_event_failed(self, output: Any) -> bool:
        if isinstance(output, str):
            lowered = output.strip().lower()
            if lowered.startswith("error:") or lowered.startswith("unknown tool:") or lowered.startswith("blocked in "):
                return True
            return False
        if not isinstance(output, dict):
            return False
        status = str(output.get("status", "")).strip().lower()
        if status in {"error", "failed", "denied"}:
            return True
        if status in {"ok", "success", "approved"}:
            return False
        if "success" in output:
            return not bool(output.get("success"))
        error_value = output.get("error")
        return isinstance(error_value, str) and bool(error_value.strip())

    def _is_file_change_event(self, tool_name: str, output: Any) -> bool:
        return tool_name in {"write_file", "edit_file"} and isinstance(output, dict) and "path" in output

    def _render_file_change_event_lines(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        output: dict[str, Any],
        *,
        log_id: str | None = None,
    ) -> list[str]:
        path = str(output.get("path", "(unknown path)"))
        added = int(output.get("added_lines", 0))
        removed = int(output.get("removed_lines", 0))
        lines = [self._format_file_change_heading(tool_name, path, output)]
        summary = self._summarize_file_change(added, removed)
        if summary:
            lines.append(f"  \u23bf  {summary}")
        lines.extend(self._render_file_change_diff(tool_name, tool_input))
        if log_id and self._file_change_needs_log_hint(tool_name, tool_input):
            lines.append(f"     Log: {self._format_tool_log_path(log_id)}")
        return lines

    def _format_file_change_heading(self, tool_name: str, path: str, output: dict[str, Any]) -> str:
        action = "Update"
        if tool_name == "write_file":
            action = "Create" if not bool(output.get("existed_before")) else "Write"
        return f"{self._tool_bullet(output)} {action}({path})"

    def _summarize_file_change(self, added: int, removed: int) -> str:
        if added and removed:
            return f"Added {added} lines, removed {removed} lines"
        if added:
            return f"Added {added} lines"
        if removed:
            return f"Removed {removed} lines"
        return "Updated file"

    def _render_file_change_diff(self, tool_name: str, tool_input: dict[str, Any], *, limit: int = 8) -> list[str]:
        if tool_name == "edit_file":
            before = str(tool_input.get("old_text", ""))
            after = str(tool_input.get("new_text", ""))
        else:
            before = ""
            after = str(tool_input.get("content", ""))
        if not after and not before:
            return []
        diff_lines = list(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=1))
        visible = [line for line in diff_lines[2:] if line.strip()]
        if not visible:
            return []
        truncated = False
        if len(visible) > limit:
            visible = visible[:limit]
            truncated = True
        rendered: list[str] = []
        for line in visible:
            rendered.append(self._format_diff_preview_line(line))
        if truncated:
            rendered.append("      ...")
        return rendered

    def _format_diff_preview_line(self, line: str) -> str:
        if self._supports_ansi_output():
            if line.startswith("+") and not line.startswith("+++"):
                return f"      \x1b[32m{line}\x1b[0m"
            if line.startswith("-") and not line.startswith("---"):
                return f"      \x1b[31m{line}\x1b[0m"
            if line.startswith("@@"):
                return f"      \x1b[38;5;244m{line}\x1b[0m"
        return f"      {line}"

    def _file_change_needs_log_hint(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        key = "new_text" if tool_name == "edit_file" else "content"
        text = str(tool_input.get(key, ""))
        return len(text.splitlines()) > 8 or len(text) > 240

    def _format_clickable_file_label(self, label: str, absolute_path: str) -> str:
        if not absolute_path or not self._supports_ansi_output():
            return label
        try:
            file_uri = Path(absolute_path).resolve().as_uri()
        except Exception:
            return label
        blue_label = f"\x1b[38;5;39m{label}\x1b[0m"
        return f"\x1b]8;;{file_uri}\x1b\\{blue_label}\x1b]8;;\x1b\\"

    def _format_tool_log_path(self, log_id: str) -> str:
        if not self._supports_ansi_output():
            return f"/toollog {log_id}"
        root = getattr(self.tool_log_store, "root", None)
        if not isinstance(root, Path):
            return f"/toollog {log_id}"
        path = root / f"{log_id}.json"
        try:
            relative = path.relative_to(self.settings.workspace_root)
            label = relative.as_posix()
        except Exception:
            label = str(path)
        return self._format_clickable_file_label(label, str(path))

    def _summarize_file_changes(self, file_changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summary_by_path: dict[str, dict[str, Any]] = {}
        for item in file_changes:
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            current = summary_by_path.setdefault(
                path,
                {
                    "path": path,
                    "absolute_path": str(item.get("absolute_path", "")).strip(),
                    "added_lines": 0,
                    "removed_lines": 0,
                },
            )
            current["added_lines"] += int(item.get("added_lines", 0))
            current["removed_lines"] += int(item.get("removed_lines", 0))
            if not current["absolute_path"]:
                current["absolute_path"] = str(item.get("absolute_path", "")).strip()
        return list(summary_by_path.values())

    def _capture_turn_file_changes(self, session: AgentSession) -> None:
        pending = list(getattr(session, "pending_file_changes", []) or [])
        session.pending_file_changes = []
        if not pending:
            session.last_turn_file_changes = []
            return
        session.last_turn_file_changes = self._summarize_file_changes(pending)
        session.undo_stack.append(
            {
                "turn_id": session.latest_turn_id,
                "files": pending,
            }
        )
        if len(session.undo_stack) > self.MAX_UNDO_TURNS:
            session.undo_stack = session.undo_stack[-self.MAX_UNDO_TURNS :]

    def print_last_turn_file_summary(self, session: AgentSession) -> bool:
        changes = list(getattr(session, "last_turn_file_changes", []) or [])
        if not changes:
            return False
        print()
        print("Changed files")
        print("Undo by: /undo")
        for item in changes:
            path = str(item.get("path", "(unknown path)"))
            absolute_path = str(item.get("absolute_path", "")).strip()
            plus_text = f"+{int(item.get('added_lines', 0))}"
            minus_text = f"-{int(item.get('removed_lines', 0))}"
            path_text = self._format_clickable_file_label(path, absolute_path)
            if self._supports_ansi_output():
                plus_text = f"\x1b[32m{plus_text}\x1b[0m"
                minus_text = f"\x1b[31m{minus_text}\x1b[0m"
            print(f"{path_text} {plus_text} {minus_text}")
        print()
        return True

    def undo_last_turn(self, session: AgentSession) -> str:
        undo_stack = list(getattr(session, "undo_stack", []) or [])
        if not undo_stack:
            return "Nothing to undo."
        entry = undo_stack.pop()
        for item in reversed(entry.get("files", [])):
            relative_path = str(item.get("path", "")).strip()
            if not relative_path:
                continue
            path = (self.settings.workspace_root / relative_path).resolve()
            if not path.is_relative_to(self.settings.workspace_root):
                raise ValueError(f"Undo path escapes workspace: {relative_path}")
            existed_before = bool(item.get("existed_before"))
            previous_content = str(item.get("previous_content", ""))
            if existed_before:
                atomic_write_text(path, previous_content)
            elif path.exists():
                path.unlink()
        session.undo_stack = undo_stack
        session.last_turn_file_changes = []
        session.pending_file_changes = []
        self.session_manager.save(session)
        file_count = len(entry.get("files", []))
        return f"Undid {file_count} file change(s) from the most recent change set."

    def _stdout_is_prompt_toolkit_proxy(self) -> bool:
        stdout_type = type(sys.stdout)
        return stdout_type.__module__ == "prompt_toolkit.patch_stdout" and stdout_type.__name__ == "StdoutProxy"

    def _supports_ansi_output(self) -> bool:
        if self._ansi_output_enabled is not None:
            return self._ansi_output_enabled
        if not sys.stdout.isatty():
            self._ansi_output_enabled = False
            return False
        if sys.platform != "win32":
            self._ansi_output_enabled = True
            return True
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            if handle in (0, -1):
                self._ansi_output_enabled = False
                return False
            mode = ctypes.c_uint()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
                self._ansi_output_enabled = False
                return False
            enable_vt = 0x0004
            if mode.value & enable_vt:
                self._ansi_output_enabled = True
                return True
            self._ansi_output_enabled = kernel32.SetConsoleMode(handle, mode.value | enable_vt) != 0
            return self._ansi_output_enabled
        except Exception:
            self._ansi_output_enabled = False
            return False

    def _stringify_tool_value(self, value: Any) -> str:
        if isinstance(value, str):
            return " ".join(value.split())
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except TypeError:
            return " ".join(str(value).split())

    def _compact_preview(self, text: str, *, limit: int) -> str:
        compact = " ".join(str(text).split())
        if not compact:
            return ""
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3] + "..."

    def _preview_tool_text(self, text: str, *, limit: int | None = None) -> tuple[str, bool]:
        preview_limit = self.TOOL_VALUE_PREVIEW_CHARS if limit is None else limit
        compact = self._compact_preview(text, limit=preview_limit)
        if not compact:
            return "(no output)", False
        return compact, len(" ".join(str(text).split())) > preview_limit

    def recent_tool_logs(self, limit: int = 10) -> str:
        entries = self.tool_log_store.list_recent(limit=limit)
        if not entries:
            return "No tool logs yet."
        lines: list[str] = []
        for entry in entries:
            lines.append(f"- {entry['id']} [{entry['category']}] {entry['actor']} -> {entry['tool_name']}")
        return "\n".join(lines)

    def render_tool_log(self, log_id: str) -> str:
        entry = self.tool_log_store.get(log_id)
        if entry is None:
            return f"Tool log '{log_id}' not found."
        args_text = json.dumps(entry["tool_input"], ensure_ascii=False, indent=2)
        return "\n".join(
            [
                f"[tool log {entry['id']}]",
                f"Category: {entry['category']}",
                f"Actor: {entry['actor']}",
                f"Tool: {entry['tool_name']}",
                "Args:",
                args_text,
                "Result:",
                str(entry["output"]),
            ]
        )

    def _make_provider(self) -> LLMProvider:
        return self._instantiate_provider(self.settings.provider)

    def _instantiate_provider(self, provider_settings: ProviderSettings) -> LLMProvider:
        if provider_settings.provider_type == "openai":
            return OpenAIProvider(provider_settings)
        return AnthropicProvider(provider_settings)

    def configured_provider_profiles(self) -> dict[str, ProviderProfileSettings]:
        return dict(self.settings.provider_profiles)

    def _workspace_authorizations_path(self) -> Path | None:
        settings = getattr(self, "settings", None)
        storage = getattr(settings, "storage", None)
        data_dir = getattr(storage, "data_dir", None)
        if not isinstance(data_dir, Path):
            return None
        return data_dir / self.WORKSPACE_PERMISSIONS_FILE

    def _load_workspace_authorizations(self) -> set[str]:
        path = self._workspace_authorizations_path()
        if path is None:
            return set()
        try:
            payload = read_json(path, {"authorized_tools": []})
        except Exception:
            return set()
        if not isinstance(payload, dict):
            return set()
        raw_tools = payload.get("authorized_tools", [])
        if not isinstance(raw_tools, list):
            return set()
        authorized: set[str] = set()
        for item in raw_tools:
            tool_name = str(item).strip()
            if tool_name:
                authorized.add(tool_name)
        return authorized

    def _persist_workspace_authorizations(self) -> None:
        path = self._workspace_authorizations_path()
        if path is None:
            return
        write_json(path, {"authorized_tools": sorted(self._workspace_authorized_tools)})

    def authorize_tool_call(self, tool_name: str, payload: dict[str, Any], *, ctx=None) -> str | None:
        if tool_name in {AUTHORIZATION_TOOL_NAME, MODE_SWITCH_TOOL_NAME}:
            return None
        if tool_name in self._workspace_authorized_tools:
            return None
        remaining = self._once_authorized_tools.get(tool_name, 0)
        if remaining > 0:
            if remaining == 1:
                self._once_authorized_tools.pop(tool_name, None)
            else:
                self._once_authorized_tools[tool_name] = remaining - 1
            return None
        return tool_block_message(getattr(self, "execution_mode", DEFAULT_EXECUTION_MODE), tool_name)

    def request_authorization(self, tool_name: str, reason: str, argument_summary: str = "") -> str:
        normalized_tool = str(tool_name).strip()
        if not normalized_tool:
            return "Authorization request failed: tool_name is required."
        if normalized_tool == AUTHORIZATION_TOOL_NAME:
            return "Authorization not required for request_authorization."
        if normalized_tool in self._workspace_authorized_tools:
            return json.dumps(
                {"status": "approved", "scope": "workspace", "tool_name": normalized_tool, "cached": True},
                ensure_ascii=False,
            )
        handler = self.authorization_request_handler
        if not callable(handler):
            return "Authorization request failed: interactive approvals are unavailable in this session."
        result = handler(
            tool_name=normalized_tool,
            reason=str(reason).strip(),
            argument_summary=str(argument_summary).strip(),
            execution_mode=getattr(self, "execution_mode", DEFAULT_EXECUTION_MODE),
        )
        if not isinstance(result, dict):
            return "Authorization request failed: invalid approval response."
        status = str(result.get("status", "denied")).strip().lower()
        scope = str(result.get("scope", "deny")).strip().lower()
        if status == "approved":
            if scope == "workspace":
                self._workspace_authorized_tools.add(normalized_tool)
                self._persist_workspace_authorizations()
            elif scope == "once":
                self._once_authorized_tools[normalized_tool] = self._once_authorized_tools.get(normalized_tool, 0) + 1
        payload = {
            "status": "approved" if status == "approved" else "denied",
            "scope": scope,
            "tool_name": normalized_tool,
            "reason": str(result.get("reason", "")).strip(),
        }
        return json.dumps(payload, ensure_ascii=False)

    def request_mode_switch(self, target_mode: str, reason: str = "") -> str:
        normalized_target = normalize_execution_mode(target_mode)
        if normalized_target == "yolo" or normalized_target not in NON_YOLO_EXECUTION_MODES:
            return (
                "Mode switch request failed: target_mode must be one of "
                "'shortcuts', 'plan', or 'accept_edits'."
            )
        current_mode = normalize_execution_mode(getattr(self, "execution_mode", DEFAULT_EXECUTION_MODE))
        if normalized_target == current_mode:
            return json.dumps(
                {
                    "status": "unchanged",
                    "current_mode": current_mode,
                    "target_mode": normalized_target,
                    "reason": "Already in requested mode.",
                },
                ensure_ascii=False,
            )
        handler = self.mode_switch_request_handler
        if not callable(handler):
            return "Mode switch request failed: interactive mode switching is unavailable in this session."
        result = handler(target_mode=normalized_target, reason=str(reason).strip(), current_mode=current_mode)
        if not isinstance(result, dict):
            return "Mode switch request failed: invalid mode switch response."
        approved = bool(result.get("approved"))
        active_mode = normalize_execution_mode(result.get("active_mode", current_mode))
        self.execution_mode = active_mode
        payload = {
            "status": "approved" if approved else "denied",
            "current_mode": active_mode,
            "target_mode": normalized_target,
            "reason": str(result.get("reason", "")).strip(),
        }
        return json.dumps(payload, ensure_ascii=False)

    def switch_provider_model(self, provider_name: str, model: str) -> str:
        normalized_provider = provider_name.strip().lower()
        normalized_model = model.strip()
        if normalized_provider not in self.settings.provider_profiles:
            raise ValueError(f"Provider '{normalized_provider}' is not configured.")
        profile = self.settings.provider_profiles[normalized_provider]
        if normalized_model not in profile.models:
            raise ValueError(f"Model '{normalized_model}' is not configured for provider '{normalized_provider}'.")
        self.settings.provider = ProviderSettings(
            name=profile.name,
            provider_type=profile.provider_type,
            model=normalized_model,
            api_key=profile.api_key,
            base_url=profile.base_url,
            organization=profile.organization,
            max_tokens=profile.max_tokens,
            timeout_seconds=profile.timeout_seconds,
        )
        self.settings.provider_profiles[normalized_provider].default_model = normalized_model
        self.provider = self._instantiate_provider(self.settings.provider)
        self.compact_manager.provider = self.provider
        self.compact_manager.model_max_tokens = self.settings.provider.max_tokens
        persist_provider_selection(self.settings, normalized_provider, normalized_model)
        return (
            f"Switched to provider '{self.settings.provider.name}' with model "
            f"'{self.settings.provider.model}' and saved it to openagent.toml."
        )

    def _register_core_tools(self, registry: ToolRegistry) -> None:
        register_shell_tool(registry)
        register_filesystem_tools(registry)
        register_todo_tool(registry, self.todo_manager)
        register_task_tools(registry, self.task_store)
        register_subagent_tool(registry)
        register_background_tools(registry, self.background_manager)
        register_team_tools(registry, self.team_manager, self.bus, self.request_tracker)
        self._register_local_tools(registry)
        register_mcp_tools(registry, self.mcp_registry)

    def register_worker_tools(self, registry: ToolRegistry) -> None:
        register_shell_tool(registry)
        register_filesystem_tools(registry)
        register_task_tools(registry, self.task_store)
        self._register_worker_local_tools(registry)

    def _register_local_tools(self, registry: ToolRegistry) -> None:
        registry.register(
            ToolDefinition(
                name="load_skill",
                description="Load specialized knowledge by skill name.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                handler=lambda ctx, payload: self.skill_loader.load(payload["name"]),
            )
        )
        registry.register(
            ToolDefinition(
                name=AUTHORIZATION_TOOL_NAME,
                description=(
                    "Request user approval for a blocked tool call. "
                    "Use this before edits in read-only modes or before broader tools in accept-edits mode."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "reason": {"type": "string"},
                        "argument_summary": {"type": "string"},
                    },
                    "required": ["tool_name", "reason"],
                },
                handler=lambda ctx, payload: self.request_authorization(
                    payload["tool_name"],
                    payload["reason"],
                    payload.get("argument_summary", ""),
                ),
            )
        )
        registry.register(
            ToolDefinition(
                name=MODE_SWITCH_TOOL_NAME,
                description=(
                    "Request that the user switch execution mode to shortcuts, plan, or accept_edits only."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "target_mode": {"type": "string", "enum": list(NON_YOLO_EXECUTION_MODES)},
                        "reason": {"type": "string"},
                    },
                    "required": ["target_mode"],
                },
                handler=lambda ctx, payload: self.request_mode_switch(payload["target_mode"], payload.get("reason", "")),
            )
        )
        registry.register(
            ToolDefinition(
                name="compress",
                description="Manually compact the current conversation context.",
                input_schema={"type": "object", "properties": {}},
                handler=lambda ctx, payload: "Compressing...",
            )
        )

    def _register_worker_local_tools(self, registry: ToolRegistry) -> None:
        registry.register(
            ToolDefinition(
                name="send_message",
                description="Send a message to another teammate or lead.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["to", "content"],
                },
                handler=lambda ctx, payload: self.bus.send(ctx.actor, payload["to"], payload["content"]),
            )
        )
        registry.register(
            ToolDefinition(
                name="idle",
                description="Enter idle state.",
                input_schema={"type": "object", "properties": {}},
                handler=lambda ctx, payload: "Entering idle phase.",
            )
        )
        registry.register(
            ToolDefinition(
                name="submit_plan",
                description="Submit a plan for lead approval.",
                input_schema={
                    "type": "object",
                    "properties": {"plan": {"type": "string"}},
                    "required": ["plan"],
                },
                handler=lambda ctx, payload: self._submit_plan(ctx.actor, payload["plan"]),
            )
        )

    def _submit_plan(self, actor: str, plan: str) -> str:
        request = self.request_tracker.create_plan_request(actor, plan)
        self.bus.send(actor, "lead", plan, "plan_request", {"request_id": request["request_id"]})
        return f"Submitted plan request {request['request_id']}"

    def _environment_guidance(self) -> str:
        os_name = platform.system() or sys.platform
        shell_line = "PowerShell-compatible command runner" if sys.platform == "win32" else "system shell command runner"
        bash_hint = (
            "When using the `bash` tool on Windows, prefer PowerShell commands such as "
            "`Get-ChildItem`, `Get-Content`, `Select-String`, and `Select-Object`. "
            "Do not assume Unix commands like `ls`, `find -name`, `head`, `grep`, or `/dev/null` are available."
            if sys.platform == "win32"
            else "When using the `bash` tool on Unix-like systems, standard shell commands are available."
        )
        return (
            "Execution environment:\n"
            f"- OS: {os_name}\n"
            f"- Shell: {shell_line}\n"
            f"- Workspace: {self.settings.workspace_root}\n"
            f"- Active provider: {self.settings.provider.name}\n"
            f"- Active model: {self.settings.provider.model}\n"
            "Tool behavior:\n"
            f"- {bash_hint}"
        )

    def build_system_prompt(self, actor: str = "lead", role: str = "lead coding agent") -> str:
        base_prompt = self._base_system_prompt()
        environment_guidance = self._environment_guidance()
        mode_guidance = execution_mode_spec(getattr(self, "execution_mode", DEFAULT_EXECUTION_MODE)).guidance
        identity_guidance = (
            "Identity rules:\n"
            f"- Your configured runtime provider is '{self.settings.provider.name}'.\n"
            f"- Your configured runtime model is '{self.settings.provider.model}'.\n"
            "- If the user asks which model or provider you are using, answer with these configured values.\n"
            "- Do not claim to be Claude, ChatGPT, GPT, Gemini, or any other model/vendor unless that exactly matches the configured runtime values above."
        )
        if actor == "lead":
            return (
                f"{base_prompt}\n\n"
                f"You are '{actor}', role: {role}, operating inside workspace {self.settings.workspace_root}.\n"
                "Use tools to solve coding tasks. Prefer task_create/task_update/task_list for longer work.\n"
                "Use TodoWrite for short checklists. Use subagent for isolated subagent work. Use load_skill only when needed.\n"
                "When collaborating, keep teammates informed through inbox messages and respect shutdown and plan protocols.\n"
                f"{identity_guidance}\n"
                f"{mode_guidance}\n"
                f"{environment_guidance}\n"
                f"Available skills:\n{self.skill_loader.descriptions()}"
            )
        return (
            f"{base_prompt}\n\n"
            f"You are '{actor}', role: {role}, operating inside workspace {self.settings.workspace_root}.\n"
            "You are a persistent teammate following the s11 work/idle loop.\n"
            "Use tools to complete current work, send messages when needed, and call idle when you have finished the current unit of work.\n"
            "While idle you may be resumed by inbox messages or unclaimed tasks.\n"
            f"{identity_guidance}\n"
            f"{mode_guidance}\n"
            f"{environment_guidance}\n"
            f"Available skills:\n{self.skill_loader.descriptions()}"
        )

    def _base_system_prompt(self) -> str:
        configured_prompt = self.settings.agent.system_prompt
        if configured_prompt:
            return configured_prompt
        return self.DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(name=self.settings.agent.name)

    def create_session(self) -> AgentSession:
        return self.session_manager.create()

    def latest_session(self) -> AgentSession:
        return self.session_manager.latest_or_create()

    def load_session(self, session_id: str) -> AgentSession:
        return self.session_manager.load(session_id)

    def list_sessions(self) -> list[AgentSession]:
        return self.session_manager.list_all()

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        text_callback=None,
    ):
        last_error: Exception | None = None
        for _ in range(3):
            try:
                return self.provider.complete(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools,
                    max_tokens=self.settings.provider.max_tokens,
                    text_callback=text_callback,
                )
            except TurnInterrupted:
                raise
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Provider call failed after retries: {last_error}")

    def run_subagent(self, prompt: str, agent_type: str = "Explore") -> str:
        registry = ToolRegistry()
        register_shell_tool(registry)
        registry.register(
            ToolDefinition(
                name="read_file",
                description="Read file contents.",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                handler=read_file,
            )
        )
        if agent_type != "Explore":
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
        registry.register(
            ToolDefinition(
                name="load_skill",
                description="Load specialized knowledge by skill name.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                handler=lambda ctx, payload: self.skill_loader.load(payload["name"]),
            )
        )
        messages = [make_user_text_message(prompt)]
        system_prompt = (
            f"You are an isolated subagent working in {self.settings.workspace_root}. "
            "Keep the main context clean. Do the work, then return a concise summary.\n\n"
            f"{self._environment_guidance()}"
        )
        final_text = "(subagent failed)"
        for _ in range(self.settings.runtime.max_subagent_rounds):
            turn = self.complete(system_prompt, messages, registry.schemas())
            messages.append(turn.as_message())
            if not turn.has_tool_calls():
                text = "\n".join(turn.text_blocks).strip()
                return text or "(no summary)"
            results: list[dict[str, Any]] = []
            ctx = ToolExecutionContext(runtime=self, session=None, actor="subagent", trace_id=f"subagent-{uuid.uuid4().hex[:8]}")
            for tool_call in turn.tool_calls:
                try:
                    output = registry.execute(ctx, tool_call.name, tool_call.input)
                except Exception as exc:
                    output = f"Error: {exc}"
                results.append(
                    {
                        "type": "tool_result",
                        "tool_call_id": tool_call.id,
                        "content": str(output),
                    }
                )
            messages.append(make_tool_result_message(results))
            final_text = "\n".join(turn.text_blocks).strip() or final_text
        return final_text

    def compact_session(self, session: AgentSession) -> None:
        session.messages = self.compact_manager.auto_compact(session.id, session.messages)
        self.session_manager.save(session)

    def _raise_if_interrupted(self, should_interrupt) -> None:
        if should_interrupt is not None and should_interrupt():
            raise TurnInterrupted("Interrupted by user.")

    def run_turn(self, session: AgentSession, user_input: str, text_callback=None, should_interrupt=None) -> str:
        session.pending_file_changes = []
        session.last_turn_file_changes = []
        session.messages.append(make_user_text_message(user_input))
        self.transcript_store.append(session.id, {"role": "user", "content": user_input})
        return self._agent_loop(session, text_callback=text_callback, should_interrupt=should_interrupt)

    def _agent_loop(self, session: AgentSession, text_callback=None, should_interrupt=None) -> str:
        final_text = ""
        try:
            for _ in range(self.settings.runtime.max_agent_rounds):
                self._raise_if_interrupted(should_interrupt)
                microcompact(session.messages)
                if estimate_tokens(session.messages) > self.settings.runtime.token_threshold:
                    session.messages = self.compact_manager.auto_compact(session.id, session.messages)
                background_notifications = self.background_manager.drain()
                if background_notifications:
                    text = "\n".join(
                        f"[bg:{item['task_id']}] {item['status']}: {item['result']}" for item in background_notifications
                    )
                    session.messages.append(make_user_text_message(f"<background-results>\n{text}\n</background-results>"))
                inbox = self.bus.read_inbox("lead")
                if inbox:
                    session.messages.append(make_user_text_message(f"<inbox>{json.dumps(inbox, ensure_ascii=False, indent=2)}</inbox>"))

                callback = text_callback
                if text_callback is not None or should_interrupt is not None:
                    def interruptible_callback(text: str) -> None:
                        self._raise_if_interrupted(should_interrupt)
                        if text_callback is not None:
                            text_callback(text)
                        self._raise_if_interrupted(should_interrupt)
                    callback = interruptible_callback

                turn = self.complete(
                    self.build_system_prompt(),
                    session.messages,
                    self.registry.schemas(),
                    text_callback=callback,
                )
                self._raise_if_interrupted(should_interrupt)
                session.latest_turn_id = uuid.uuid4().hex[:8]
                if not turn.has_tool_calls():
                    assistant_message = turn.as_message()
                    session.messages.append(assistant_message)
                    self.transcript_store.append(session.id, assistant_message)
                    final_text = "\n\n".join(turn.text_blocks).strip()
                    self._capture_turn_file_changes(session)
                    self.session_manager.save(session)
                    return final_text

                tool_results: list[dict[str, Any]] = []
                executed_tool_calls = []
                used_todo = False
                manual_compact = False
                end_turn_after_tool = False
                for tool_call in turn.tool_calls:
                    self._raise_if_interrupted(should_interrupt)
                    ctx = ToolExecutionContext(
                        runtime=self,
                        session=session,
                        actor="lead",
                        trace_id=f"{session.id}-{session.latest_turn_id}",
                    )
                    if tool_call.name == "compress":
                        manual_compact = True
                    try:
                        output = self.registry.execute(ctx, tool_call.name, tool_call.input)
                    except Exception as exc:
                        output = f"Error: {exc}"
                    log_id = self.print_tool_event("lead", tool_call.name, tool_call.input, output)
                    executed_tool_calls.append(tool_call)
                    result = {
                        "type": "tool_result",
                        "tool_call_id": tool_call.id,
                        "content": str(output)[: self.settings.runtime.max_tool_output_chars],
                        "raw_output": output,
                        "log_id": log_id,
                    }
                    tool_results.append(result)
                    self.transcript_store.append(
                        session.id,
                        {
                            "role": "tool",
                            "name": tool_call.name,
                            "input": tool_call.input,
                            "output": result["content"],
                        },
                    )
                    if tool_call.name == "TodoWrite":
                        used_todo = True
                    if tool_call.name in self.TURN_BOUNDARY_TOOL_NAMES:
                        end_turn_after_tool = True
                        break

                assistant_message = turn.as_message(executed_tool_calls)
                session.messages.append(assistant_message)
                self.transcript_store.append(session.id, assistant_message)
                session.rounds_without_todo = 0 if used_todo else session.rounds_without_todo + 1
                if self.todo_manager.has_open_items(session) and session.rounds_without_todo >= 3:
                    tool_results.insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})
                session.messages.append(make_tool_result_message(tool_results))
                if manual_compact:
                    session.messages = self.compact_manager.auto_compact(session.id, session.messages)
                self.session_manager.save(session)
                if end_turn_after_tool:
                    continue
            self._capture_turn_file_changes(session)
            self.session_manager.save(session)
            return final_text or "Stopped after max rounds."
        except TurnInterrupted:
            session.pending_file_changes = []
            session.last_turn_file_changes = []
            self.session_manager.save(session)
            raise

    def doctor(self) -> str:
        lines = [
            f"workspace: {self.settings.workspace_root}",
            f"provider: {self.settings.provider.name}",
            f"model: {self.settings.provider.model}",
            f"api_key_configured: {'yes' if self.settings.provider.api_key else 'no'}",
            f"configured_providers: {', '.join(sorted(self.settings.provider_profiles))}",
            f"skills_dir: {'present' if (self.settings.workspace_root / 'skills').exists() else 'missing'}",
            f"data_dir: {self.settings.storage.data_dir}",
        ]
        if self.settings.mcp_servers:
            lines.append("mcp:")
            lines.extend(f"  {line}" for line in self.mcp_registry.status_lines())
        else:
            lines.append("mcp: none configured")
        return "\n".join(lines)

    def mcp_status(self) -> str:
        return self.mcp_registry.describe_servers()

    def close(self) -> None:
        self.mcp_registry.close()
