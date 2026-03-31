"""Agent 运行时模块.

提供 OpenAgent 的核心运行时功能，包括：
- LLM 提供者管理
- 工具注册和执行
- 会话管理
- 子代理运行
- 后台任务管理
"""

from __future__ import annotations

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
from openagent.runtime.events import ToolExecutionContext
from openagent.runtime.messages import make_tool_result_message, make_user_text_message
from openagent.runtime.session import AgentSession, SessionManager
from openagent.runtime.teammate import TeammateRuntimeManager
from openagent.skills.loader import SkillLoader
from openagent.storage.inbox import InboxStore
from openagent.storage.jobs import JobStore
from openagent.storage.sessions import SessionStore
from openagent.storage.common import atomic_write_text
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
    SILENT_TOOL_NAMES = {"TodoWrite"}
    MAX_UNDO_TURNS = 10
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
        if self._is_file_change_event(tool_name, output):
            self._print_file_change_event(tool_name, log_entry["id"], output)
            return log_entry["id"]
        border = f"{'=' * 18} {category} {actor} {'=' * 18}"
        name_line = f"Name: {tool_name}"
        args_text = self._stringify_tool_value(tool_input)
        result_text = self._stringify_tool_value(output)
        args_preview, args_hidden = self._preview_tool_text(args_text)
        result_preview, result_hidden = self._preview_tool_text(result_text)
        has_hidden_content = args_hidden or result_hidden
        print()
        self._print_tool_border(border, category)
        if has_hidden_content:
            print(f"View by: /toollog {log_entry['id']}")
        print(name_line)
        print("Args:")
        print(args_preview)
        print("Result:")
        print(result_preview)
        self._print_tool_border("=" * len("================== TOOL lead =================="), category)
        print()
        return log_entry["id"]

    def _print_tool_border(self, text: str, category: str) -> None:
        if self._supports_ansi_output():
            color = "\x1b[38;5;214m" if category == "MCP" else "\x1b[38;5;111m"
            print(f"{color}{text}\x1b[0m")
            return
        print(text)

    def _is_file_change_event(self, tool_name: str, output: Any) -> bool:
        return tool_name in {"write_file", "edit_file"} and isinstance(output, dict) and "path" in output

    def _print_file_change_event(self, tool_name: str, log_id: str, output: dict[str, Any]) -> None:
        path = str(output.get("path", "(unknown path)"))
        absolute_path = str(output.get("absolute_path", "")).strip()
        added = int(output.get("added_lines", 0))
        removed = int(output.get("removed_lines", 0))
        plus_text = f"+{added}"
        minus_text = f"-{removed}"
        path_text = self._format_clickable_file_label(path, absolute_path)
        print()
        if self._supports_ansi_output():
            plus_text = f"\x1b[32m{plus_text}\x1b[0m"
            minus_text = f"\x1b[31m{minus_text}\x1b[0m"
        print(tool_name)
        print(f"View by: /toollog {log_id}")
        print(f"{path_text} {plus_text} {minus_text}")
        print()

    def _format_clickable_file_label(self, label: str, absolute_path: str) -> str:
        if not absolute_path or not self._supports_ansi_output():
            return label
        try:
            file_uri = Path(absolute_path).resolve().as_uri()
        except Exception:
            return label
        blue_label = f"\x1b[38;5;39m{label}\x1b[0m"
        return f"\x1b]8;;{file_uri}\x1b\\{blue_label}\x1b]8;;\x1b\\"

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

    def _preview_tool_text(self, text: str) -> tuple[str, bool]:
        compact = " ".join(text.split())
        if not compact:
            return "(no output)", False
        if len(compact) <= self.TOOL_VALUE_PREVIEW_CHARS:
            return compact, False
        return compact[: self.TOOL_VALUE_PREVIEW_CHARS - 3] + "...", True

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
        if provider_settings.name == "openai":
            return OpenAIProvider(provider_settings)
        return AnthropicProvider(provider_settings)

    def configured_provider_profiles(self) -> dict[str, ProviderProfileSettings]:
        return dict(self.settings.provider_profiles)

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
                "Use TodoWrite for short checklists. Use task for isolated subagent work. Use load_skill only when needed.\n"
                "When collaborating, keep teammates informed through inbox messages and respect shutdown and plan protocols.\n"
                f"{identity_guidance}\n"
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
                assistant_message = turn.as_message()
                session.messages.append(assistant_message)
                self.transcript_store.append(session.id, assistant_message)
                if not turn.has_tool_calls():
                    final_text = "\n\n".join(turn.text_blocks).strip()
                    self._capture_turn_file_changes(session)
                    self.session_manager.save(session)
                    return final_text

                tool_results: list[dict[str, Any]] = []
                used_todo = False
                manual_compact = False
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
                    self.print_tool_event("lead", tool_call.name, tool_call.input, output)
                    result = {
                        "type": "tool_result",
                        "tool_call_id": tool_call.id,
                        "content": str(output)[: self.settings.runtime.max_tool_output_chars],
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

                session.rounds_without_todo = 0 if used_todo else session.rounds_without_todo + 1
                if self.todo_manager.has_open_items(session) and session.rounds_without_todo >= 3:
                    tool_results.insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})
                session.messages.append(make_tool_result_message(tool_results))
                if manual_compact:
                    session.messages = self.compact_manager.auto_compact(session.id, session.messages)
                self.session_manager.save(session)
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
