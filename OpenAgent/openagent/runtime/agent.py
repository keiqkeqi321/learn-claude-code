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
import sys
import uuid
from typing import Any

from openagent.collaboration.bus import MessageBus
from openagent.collaboration.protocols import RequestTracker
from openagent.config.models import AppSettings
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


class OpenAgentRuntime:
    TOOL_RESULT_PREVIEW_LINES = 20
    TOOL_PREVIEW_LINE_WIDTH = 160
    _ansi_output_enabled: bool | None = None

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
        if not sys.stdout.isatty():
            return log_entry["id"]
        border = self._tool_border(f"{'=' * 18} {category} {actor} {'=' * 18}", category)
        name_line = f"Name: {tool_name}"
        args_text = self._stringify_tool_value(tool_input)
        result_text = self._stringify_tool_value(output)
        args_preview, args_hidden = self._preview_tool_text(args_text)
        result_preview, result_hidden = self._preview_tool_text(
            result_text,
            max_chars=self.settings.runtime.max_tool_output_chars,
        )
        has_hidden_content = args_hidden or result_hidden
        print()
        print(border)
        if has_hidden_content:
            print(f"View by: /toollog {log_entry['id']}")
        print(name_line)
        print("Args:")
        print(args_preview)
        print("Result:")
        print(result_preview)
        print(self._tool_border("=" * len("================== TOOL lead =================="), category))
        print()
        return log_entry["id"]

    def _tool_border(self, text: str, category: str) -> str:
        if not self._supports_ansi_output():
            return text
        color = "\x1b[38;5;214m" if category == "MCP" else "\x1b[38;5;111m"
        return f"{color}{text}\x1b[0m"

    def _supports_ansi_output(self) -> bool:
        if self._ansi_output_enabled is not None:
            return self._ansi_output_enabled
        if not sys.stdout.isatty():
            self._ansi_output_enabled = False
            return False
        stdout_type = type(sys.stdout)
        if stdout_type.__module__ == "prompt_toolkit.patch_stdout" and stdout_type.__name__ == "StdoutProxy":
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
            return value
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except TypeError:
            return str(value)

    def _preview_tool_text(self, text: str, *, max_chars: int | None = None) -> tuple[str, bool]:
        hidden = False
        if max_chars is not None and len(text) > max_chars:
            text = text[:max_chars] + "\n... [truncated]"
            hidden = True
        raw_lines = text.splitlines() or [text]
        lines: list[str] = []
        for line in raw_lines:
            preview_line, line_hidden = self._truncate_preview_line(line)
            hidden = hidden or line_hidden
            lines.append(preview_line)
        if not lines:
            return "(no output)", hidden
        if len(lines) <= self.TOOL_RESULT_PREVIEW_LINES:
            return "\n".join(lines), hidden
        preview = "\n".join(lines[: self.TOOL_RESULT_PREVIEW_LINES])
        return preview + "\n...", True

    def _truncate_preview_line(self, line: str) -> tuple[str, bool]:
        if len(line) <= self.TOOL_PREVIEW_LINE_WIDTH:
            return line, False
        return line[: self.TOOL_PREVIEW_LINE_WIDTH - 3] + "...", True

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
        if self.settings.provider.name == "openai":
            return OpenAIProvider(self.settings.provider)
        return AnthropicProvider(self.settings.provider)

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

    def build_system_prompt(self, actor: str = "lead", role: str = "lead coding agent") -> str:
        if actor == "lead":
            return (
                f"You are '{actor}', role: {role}, operating inside workspace {self.settings.workspace_root}.\n"
                "Use tools to solve coding tasks. Prefer task_create/task_update/task_list for longer work.\n"
                "Use TodoWrite for short checklists. Use task for isolated subagent work. Use load_skill only when needed.\n"
                "When collaborating, keep teammates informed through inbox messages and respect shutdown and plan protocols.\n"
                f"Available skills:\n{self.skill_loader.descriptions()}"
            )
        return (
            f"You are '{actor}', role: {role}, operating inside workspace {self.settings.workspace_root}.\n"
            "You are a persistent teammate following the s11 work/idle loop.\n"
            "Use tools to complete current work, send messages when needed, and call idle when you have finished the current unit of work.\n"
            "While idle you may be resumed by inbox messages or unclaimed tasks.\n"
            f"Available skills:\n{self.skill_loader.descriptions()}"
        )

    def create_session(self) -> AgentSession:
        return self.session_manager.create()

    def latest_session(self) -> AgentSession:
        return self.session_manager.latest_or_create()

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
            "Keep the main context clean. Do the work, then return a concise summary."
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

    def run_turn(self, session: AgentSession, user_input: str, text_callback=None) -> str:
        session.messages.append(make_user_text_message(user_input))
        self.transcript_store.append(session.id, {"role": "user", "content": user_input})
        return self._agent_loop(session, text_callback=text_callback)

    def _agent_loop(self, session: AgentSession, text_callback=None) -> str:
        final_text = ""
        for _ in range(self.settings.runtime.max_agent_rounds):
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

            turn = self.complete(
                self.build_system_prompt(),
                session.messages,
                self.registry.schemas(),
                text_callback=text_callback,
            )
            session.latest_turn_id = uuid.uuid4().hex[:8]
            assistant_message = turn.as_message()
            session.messages.append(assistant_message)
            self.transcript_store.append(session.id, assistant_message)
            if not turn.has_tool_calls():
                final_text = "\n\n".join(turn.text_blocks).strip()
                self.session_manager.save(session)
                return final_text

            tool_results: list[dict[str, Any]] = []
            used_todo = False
            manual_compact = False
            for tool_call in turn.tool_calls:
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
        return final_text or "Stopped after max rounds."

    def doctor(self) -> str:
        lines = [
            f"workspace: {self.settings.workspace_root}",
            f"provider: {self.settings.provider.name}",
            f"model: {self.settings.provider.model}",
            f"api_key_configured: {'yes' if self.settings.provider.api_key else 'no'}",
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
