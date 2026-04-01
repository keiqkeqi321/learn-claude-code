from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import json
import random
import sys
import time
from queue import Empty, Queue
from threading import Event, Lock, Thread

from openagent.cli.commands import ConsoleStreamer, _assistant_prefix, _prefix_first_line, print_user_message
from openagent.cli.prompting import (
    COMMAND_SPECS,
    PROMPT_BORDER,
    PROMPT_TEXT,
    choose_authorization_interactively,
    choose_item_interactively,
    choose_mode_switch_interactively,
    create_prompt_session,
    fallback_prompt_message,
    styled_prompt_message,
)
from openagent.runtime.agent import TurnInterrupted
from openagent.runtime.execution_mode import (
    DEFAULT_EXECUTION_MODE,
    execution_mode_spec,
    execution_mode_status_text,
    next_execution_mode,
    normalize_execution_mode,
)
from openagent.runtime.messages import render_markdown_text, render_message_content, render_text_content
from openagent.tools.todo import TODO_CLOSED_STATUSES, TODO_STATUS_MARKERS, TODO_VISIBLE_STATUSES

try:
    from prompt_toolkit.patch_stdout import patch_stdout
except Exception:  # pragma: no cover - prompt_toolkit may be unavailable in fallback mode
    patch_stdout = None


READ_ONLY_COMMAND_PREFIXES = (
    "/tasks",
    "/team",
    "/inbox",
    "/mcp",
    "/toollog",
    "/bg",
    "/help",
)
AUTHORIZATION_PROMPT_SENTINEL = "__openagent_authorization__"


def _print_resumed_history(session) -> None:
    visible_messages: list[tuple[str, str]] = []
    for message in session.messages:
        role = message.get("role")
        content = message.get("content")
        if role == "user":
            if not isinstance(content, str):
                continue
            if content.startswith("<background-results>") or content.startswith("<inbox>"):
                continue
            visible_messages.append(("user", content))
            continue
        if role == "assistant":
            text = render_message_content(content, ansi=sys.stdout.isatty()).strip()
            if not text:
                continue
            visible_messages.append(("assistant", text))
    if not visible_messages:
        print("[resumed session has no visible chat history]")
        return
    print("[resumed history]")
    for role, text in visible_messages:
        if role == "user":
            print_user_message(text)
            continue
        print()
        print(_prefix_first_line(text, _assistant_prefix(ansi=sys.stdout.isatty())))
        print()


@dataclass(slots=True)
class AuthorizationRequest:
    tool_name: str
    reason: str
    argument_summary: str
    execution_mode: str
    completed: Event
    response: dict[str, str] | None = None


@dataclass(slots=True)
class ModeSwitchRequest:
    target_mode: str
    current_mode: str
    reason: str
    completed: Event
    response: dict[str, str] | None = None


class TurnQueueRunner:
    THINKING_PHRASES = (
        "AI is cooking",
        "Processing vibes",
        "Doing robot thoughts",
        "Consulting the void",
        "Loading genius",
    )
    DONE_TEXT = "done"
    THINKING_FRAME_SECONDS = 0.25

    def __init__(self, runtime, session, *, stable_prompt: bool = False) -> None:
        self.runtime = runtime
        self.session = session
        self.stable_prompt = stable_prompt
        self._execution_mode = normalize_execution_mode(getattr(runtime, "execution_mode", DEFAULT_EXECUTION_MODE))
        setattr(self.runtime, "execution_mode", self._execution_mode)
        self._queue: Queue[tuple[int, str, bool] | None] = Queue()
        self._lock = Lock()
        self._worker = Thread(target=self._worker_loop, name="openagent-chat-worker", daemon=True)
        self._active = False
        self._queued = 0
        self._status = ""
        self._status_changed_at = time.monotonic()
        self._ui_invalidator = None
        self._prompt_interrupter = None
        self._thinking_phrase = self.THINKING_PHRASES[0]
        self._next_query_id = 1
        self._queued_previews: list[tuple[int, str]] = []
        self._interrupt_requested = False
        self._authorization_requests: list[AuthorizationRequest] = []
        self._mode_switch_requests: list[ModeSwitchRequest] = []

    def start(self) -> None:
        self._worker.start()

    def stats(self) -> tuple[bool, int]:
        with self._lock:
            return self._active, self._queued

    def set_ui_invalidator(self, invalidator) -> None:
        self._ui_invalidator = invalidator

    def set_prompt_interrupter(self, interrupter) -> None:
        self._prompt_interrupter = interrupter

    def enqueue(self, query: str) -> tuple[bool, int]:
        with self._lock:
            was_active = self._active
            queued_before = self._queued
            query_id = self._next_query_id
            self._next_query_id += 1
            self._queued += 1
            show_queue_preview = was_active or queued_before > 0
            if show_queue_preview:
                self._queued_previews.append((query_id, self._summarize_query(query)))
        self._queue.put((query_id, query, show_queue_preview))
        self._invalidate_ui()
        return was_active, queued_before

    def has_inflight_work(self) -> bool:
        active, queued = self.stats()
        return active or queued > 0

    def request_authorization(
        self,
        *,
        tool_name: str,
        reason: str,
        argument_summary: str = "",
        execution_mode: str = DEFAULT_EXECUTION_MODE,
    ) -> dict[str, str]:
        request = AuthorizationRequest(
            tool_name=tool_name,
            reason=reason,
            argument_summary=argument_summary,
            execution_mode=execution_mode,
            completed=Event(),
        )
        with self._lock:
            self._authorization_requests.append(request)
        self._invalidate_ui()
        if self._prompt_interrupter is not None:
            try:
                self._prompt_interrupter()
            except Exception:
                pass
        if not request.completed.wait(timeout=300):
            return {"status": "denied", "scope": "deny", "reason": "Authorization request timed out."}
        return request.response or {"status": "denied", "scope": "deny", "reason": "Authorization denied."}

    def drain_authorization_requests(self) -> list[AuthorizationRequest]:
        with self._lock:
            pending = list(self._authorization_requests)
            self._authorization_requests = []
        return pending

    def request_mode_switch(self, *, target_mode: str, reason: str = "", current_mode: str = DEFAULT_EXECUTION_MODE) -> dict[str, str]:
        request = ModeSwitchRequest(
            target_mode=target_mode,
            current_mode=current_mode,
            reason=reason,
            completed=Event(),
        )
        with self._lock:
            self._mode_switch_requests.append(request)
        self._invalidate_ui()
        if self._prompt_interrupter is not None:
            try:
                self._prompt_interrupter()
            except Exception:
                pass
        if not request.completed.wait(timeout=300):
            return {
                "approved": False,
                "active_mode": self._execution_mode,
                "reason": "Mode switch request timed out.",
            }
        return request.response or {"approved": False, "active_mode": self._execution_mode, "reason": "Mode switch denied."}

    def drain_mode_switch_requests(self) -> list[ModeSwitchRequest]:
        with self._lock:
            pending = list(self._mode_switch_requests)
            self._mode_switch_requests = []
        return pending

    def close(self, *, drain: bool) -> int:
        dropped = 0
        if not drain:
            dropped = self._clear_pending()
        self._queue.put(None)
        self._worker.join()
        return dropped

    def request_interrupt(self) -> bool:
        with self._lock:
            if not self._active or self._interrupt_requested:
                return False
            self._interrupt_requested = True
        self._set_status("interrupting")
        return True

    def should_interrupt(self) -> bool:
        with self._lock:
            return self._interrupt_requested

    def _clear_pending(self) -> int:
        dropped = 0
        dropped_ids: set[int] = set()
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                break
            if item is None:
                self._queue.put(None)
                break
            query_id, _, _ = item
            dropped_ids.add(query_id)
            dropped += 1
            self._queue.task_done()
        if dropped:
            with self._lock:
                self._queued = max(0, self._queued - dropped)
                self._queued_previews = [
                    (preview_id, preview)
                    for preview_id, preview in self._queued_previews
                    if preview_id not in dropped_ids
                ]
            self._invalidate_ui()
        return dropped

    def _worker_loop(self) -> None:
        while True:
            query = self._queue.get()
            if query is None:
                self._queue.task_done()
                return
            query_id, query_text, echo_on_start = query
            with self._lock:
                self._queued = max(0, self._queued - 1)
                self._active = True
                self._thinking_phrase = random.choice(self.THINKING_PHRASES)
                self._queued_previews = [
                    (preview_id, preview)
                    for preview_id, preview in self._queued_previews
                    if preview_id != query_id
                ]
            self._set_status("thinking")
            if echo_on_start:
                print_user_message(query_text)
            streamer = ConsoleStreamer(
                start_on_new_line=True,
                line_buffered=self.stable_prompt,
                on_first_output=None,
            )
            try:
                with self._lock:
                    self._interrupt_requested = False
                response = self.runtime.run_turn(
                    self.session,
                    query_text,
                    text_callback=streamer,
                    should_interrupt=self.should_interrupt,
                )
                if streamer.has_output:
                    streamer.finish()
                    print()
                elif response:
                    print()
                    print(
                        _prefix_first_line(
                            render_markdown_text(response, ansi=sys.stdout.isatty()),
                            _assistant_prefix(ansi=sys.stdout.isatty()),
                        )
                    )
                    print()
                self.runtime.print_last_turn_file_summary(self.session)
            except TurnInterrupted:
                print()
                print("[interrupted]")
                print()
            except Exception as exc:
                print(f"[turn failed] {exc}")
                print()
            finally:
                with self._lock:
                    self._active = False
                    self._interrupt_requested = False
                self._set_status("done")
                self._queue.task_done()

    def _set_status(self, status: str) -> None:
        with self._lock:
            self._status = status
            self._status_changed_at = time.monotonic()
        self._invalidate_ui()

    def prompt_message(self):
        prompt_line = list(styled_prompt_message())
        mode_line = self._execution_mode_fragments()
        status_line = self._status_line()
        todo_lines = self._todo_lines()
        queue_lines = self._queue_preview_lines()
        fragments = []
        panel_prefix = ("fg:#64748b", "│ ")
        if self.stable_prompt and status_line:
            style = "fg:#9fb8ab" if status_line == self.DONE_TEXT else "fg:#eab308"
            fragments.extend([panel_prefix, (style, status_line), ("", "\n")])
        if self.stable_prompt:
            for style, line in todo_lines:
                fragments.extend([panel_prefix, (style, line), ("", "\n")])
            for index, queue_line in enumerate(queue_lines, start=1):
                fragments.extend([panel_prefix, ("fg:#94a3b8", f"queued {index}: {queue_line}"), ("", "\n")])
        fragments.append(panel_prefix)
        fragments.extend([*mode_line, ("", "\n")])
        fragments.extend([("fg:#64748b", PROMPT_BORDER), ("", "\n")])
        fragments.extend(prompt_line)
        return fragments

    def current_model_label(self) -> str:
        settings = getattr(self.runtime, "settings", None)
        provider = getattr(settings, "provider", None)
        if provider is None:
            return "model: unknown"
        provider_name = getattr(provider, "name", "unknown")
        model_name = getattr(provider, "model", "unknown")
        return f"model: {provider_name} / {model_name}"

    def bottom_toolbar(self):
        return [("fg:#94a3b8", self.current_model_label())]

    def current_execution_mode(self):
        return execution_mode_spec(self._execution_mode)

    def execution_mode_label(self) -> str:
        return execution_mode_status_text(self._execution_mode)

    def execution_mode_ansi_label(self) -> str:
        spec = self.current_execution_mode()
        return f"{spec.ansi_color}{self.execution_mode_label()}\x1b[0m"

    def cycle_execution_mode(self):
        self._execution_mode = next_execution_mode(self._execution_mode)
        setattr(self.runtime, "execution_mode", self._execution_mode)
        self._invalidate_ui()
        return self.current_execution_mode()

    def set_execution_mode(self, mode: str):
        self._execution_mode = normalize_execution_mode(mode)
        setattr(self.runtime, "execution_mode", self._execution_mode)
        self._invalidate_ui()
        return self.current_execution_mode()

    def _status_line(self) -> str:
        with self._lock:
            status = self._status
            changed_at = self._status_changed_at
            thinking_phrase = self._thinking_phrase
        if status == "thinking":
            dots = int((time.monotonic() - changed_at) / self.THINKING_FRAME_SECONDS) % 4
            return thinking_phrase + ("." * dots)
        if status == "interrupting":
            return "interrupting"
        if status == "done":
            return self.DONE_TEXT
        return ""

    def _queue_preview_lines(self) -> list[str]:
        with self._lock:
            return [preview for _, preview in self._queued_previews]

    def _execution_mode_fragments(self):
        spec = self.current_execution_mode()
        return [
            (spec.color, spec.title),
            ("fg:#64748b", "  (Shift+Tab to cycle)"),
        ]

    def _todo_lines(self) -> list[tuple[str, str]]:
        todo_items = [
            item
            for item in list(getattr(self.session, "todo_items", []) or [])
            if str(item.get("status", "pending")).lower() in TODO_VISIBLE_STATUSES
        ]
        if not todo_items:
            return []
        if not any(str(item.get("status", "pending")).lower() not in TODO_CLOSED_STATUSES for item in todo_items):
            return []

        completed = sum(1 for item in todo_items if item.get("status") == "completed")
        lines: list[tuple[str, str]] = [("fg:#5eead4", f"todo ({completed}/{len(todo_items)} completed)")]
        styles = {
            "pending": "fg:#cbd5e1",
            "in_progress": "fg:#fbbf24",
            "completed": "fg:#64748b",
            "cancelled": "fg:#64748b",
        }
        for item in todo_items:
            status = str(item.get("status", "pending")).lower()
            marker = TODO_STATUS_MARKERS.get(status, "•")
            style = styles.get(status, "fg:#cbd5e1")
            text = str(item.get("content", "")).strip()
            if not text:
                continue
            if status == "in_progress":
                active_form = str(item.get("activeForm", "")).strip()
                suffix = f" <- {active_form}" if active_form else ""
            else:
                suffix = ""
            lines.append((style, f"{marker} {text}{suffix}"))
        return lines

    def _summarize_query(self, query: str) -> str:
        single_line = " ".join(query.split())
        if len(single_line) <= 48:
            return single_line
        return single_line[:45] + "..."

    def _invalidate_ui(self) -> None:
        if self._ui_invalidator is not None:
            try:
                self._ui_invalidator()
            except Exception:
                pass


def _is_read_only_command(command: str) -> bool:
    return any(command == prefix or command.startswith(f"{prefix} ") for prefix in READ_ONLY_COMMAND_PREFIXES)


def _handle_model_command(runtime) -> None:
    profiles = runtime.configured_provider_profiles()
    if not profiles:
        print("[no configured providers]")
        return
    provider_items = [
        (
            name,
            f"{name} | default={profile.default_model} | models={len(profile.models)}",
        )
        for name, profile in sorted(profiles.items())
    ]
    selected_provider = choose_item_interactively("Choose Provider", "Select the provider to use for subsequent turns.", provider_items)
    if not selected_provider:
        print("[model selection cancelled]")
        return
    profile = profiles[selected_provider]
    model_items = [
        (
            model,
            f"{model}{' (default)' if model == profile.default_model else ''}",
        )
        for model in profile.models
    ]
    selected_model = choose_item_interactively(
        "Choose Model",
        f"Select a configured model under provider '{selected_provider}'.",
        model_items,
    )
    if not selected_model:
        print("[model selection cancelled]")
        return
    print(runtime.switch_provider_model(selected_provider, selected_model))


def _handle_undo_command(runtime, session) -> None:
    undo_stack = list(getattr(session, "undo_stack", []) or [])
    if not undo_stack:
        print("Nothing to undo.")
        return
    selection = choose_item_interactively(
        "Confirm Undo",
        "Undo the most recent file change set?",
        [
            ("cancel", "Cancel (default)"),
            ("confirm", "Confirm undo"),
        ],
    )
    if selection != "confirm":
        return
    print(runtime.undo_last_turn(session))


def _resolve_authorization_requests(runner: TurnQueueRunner) -> bool:
    pending = runner.drain_authorization_requests()
    if not pending:
        return False
    for request in pending:
        selection = choose_authorization_interactively(
            request.tool_name,
            request.reason,
            argument_summary=request.argument_summary,
            mode_label=execution_mode_spec(request.execution_mode).title,
        )
        if selection == "workspace":
            request.response = {"status": "approved", "scope": "workspace", "reason": "Allowed in this workspace."}
        elif selection == "once":
            request.response = {"status": "approved", "scope": "once", "reason": "Allowed once."}
        else:
            request.response = {"status": "denied", "scope": "deny", "reason": "Not allowed."}
        request.completed.set()
    return True


def _resolve_mode_switch_requests(runner: TurnQueueRunner) -> bool:
    pending = runner.drain_mode_switch_requests()
    if not pending:
        return False
    for request in pending:
        selection = choose_mode_switch_interactively(
            execution_mode_spec(request.target_mode).title,
            execution_mode_spec(request.current_mode).title,
            request.reason,
        )
        if selection == "switch":
            active_mode = runner.set_execution_mode(request.target_mode).key
            request.response = {
                "approved": True,
                "active_mode": active_mode,
                "reason": f"Switched to {execution_mode_spec(active_mode).title}.",
            }
        else:
            request.response = {
                "approved": False,
                "active_mode": runner.current_execution_mode().key,
                "reason": "Stayed in the current mode.",
            }
        request.completed.set()
    return True


def run_repl(runtime, session, resumed: bool = False) -> int:
    runner = TurnQueueRunner(runtime, session, stable_prompt=False)
    runtime.authorization_request_handler = runner.request_authorization
    runtime.mode_switch_request_handler = runner.request_mode_switch
    prompt_session = None
    try:
        prompt_session = create_prompt_session(
            runtime.settings.workspace_root,
            on_interrupt=runner.request_interrupt,
            is_busy=runner.has_inflight_work,
            on_cycle_mode=runner.cycle_execution_mode,
        )
    except Exception:
        prompt_session = None
    runner.stable_prompt = prompt_session is not None and patch_stdout is not None
    if prompt_session is not None:
        runner.set_ui_invalidator(lambda: prompt_session.app.invalidate() if prompt_session.app else None)
        runner.set_prompt_interrupter(
            lambda: prompt_session.app.exit(result=AUTHORIZATION_PROMPT_SENTINEL) if prompt_session.app else None
        )
    runner.start()
    print(f"[session {session.id}]")
    if resumed:
        _print_resumed_history(session)
    prompt_context = patch_stdout(raw=True) if prompt_session is not None and patch_stdout is not None else nullcontext()
    try:
        with prompt_context:
            while True:
                if _resolve_mode_switch_requests(runner):
                    continue
                if _resolve_authorization_requests(runner):
                    continue
                try:
                    if prompt_session is not None:
                        query = prompt_session.prompt(
                            runner.prompt_message,
                            refresh_interval=0.1,
                            bottom_toolbar=runner.bottom_toolbar,
                        )
                    else:
                        if sys.stdout.isatty():
                            query = input(
                                f"{runner.execution_mode_ansi_label()}\n"
                                f"{runner.current_model_label()}\n"
                                f"{fallback_prompt_message()}"
                            )
                        else:
                            query = input(
                                f"{runner.execution_mode_label()}\n{runner.current_model_label()}\n{PROMPT_TEXT}"
                            )
                except (EOFError, KeyboardInterrupt):
                    print()
                    active, queued = runner.stats()
                    if active:
                        if runner.request_interrupt():
                            print("[interrupt requested]")
                        continue
                    if queued:
                        print(f"[waiting for {queued} queued item(s) before exit]")
                        runner.close(drain=True)
                        break
                    runner.close(drain=True)
                    break
                if query == AUTHORIZATION_PROMPT_SENTINEL:
                    _resolve_mode_switch_requests(runner)
                    _resolve_authorization_requests(runner)
                    continue
                stripped = query.strip()
                if not stripped or stripped in {"q", "exit", "/exit"}:
                    active, queued = runner.stats()
                    if queued:
                        dropped = runner.close(drain=False)
                        if active:
                            print(f"[exiting after current response; dropped {dropped} queued prompt(s)]")
                        elif dropped:
                            print(f"[dropped {dropped} queued prompt(s)]")
                    else:
                        if active:
                            print("[waiting for current response before exit]")
                        runner.close(drain=True)
                    break
                if stripped == "/compact":
                    if runner.has_inflight_work():
                        print("[busy; wait for queued responses before /compact]")
                        continue
                    runtime.compact_session(session)
                    print("[manual compact complete]")
                    continue
                if stripped == "/undo":
                    if runner.has_inflight_work():
                        print("[busy; wait for queued responses before /undo]")
                        continue
                    _handle_undo_command(runtime, session)
                    continue
                if stripped == "/model":
                    if runner.has_inflight_work():
                        print("[busy; wait for queued responses before /model]")
                        continue
                    _handle_model_command(runtime)
                    continue
                if stripped == "/tasks":
                    tasks = runtime.task_store.list_all()
                    if not tasks:
                        print("No tasks.")
                    else:
                        for task in tasks:
                            print(json.dumps(task, ensure_ascii=False, indent=2))
                    continue
                if stripped == "/team":
                    print(runtime.team_manager.list_all())
                    continue
                if stripped == "/inbox":
                    print(json.dumps(runtime.bus.read_inbox("lead"), indent=2, ensure_ascii=False))
                    continue
                if stripped == "/mcp":
                    print(runtime.mcp_status())
                    continue
                if stripped == "/toollog":
                    print(runtime.recent_tool_logs())
                    continue
                if stripped.startswith("/toollog "):
                    log_id = stripped.split(maxsplit=1)[1].strip()
                    print(runtime.render_tool_log(log_id))
                    continue
                if stripped == "/bg":
                    print(runtime.background_manager.check())
                    continue
                if stripped == "/help":
                    print("\n".join(f"{command} - {description}" for command, description in COMMAND_SPECS))
                    continue
                if stripped.startswith("/") and not _is_read_only_command(stripped):
                    print(f"[unknown command] {stripped}")
                    continue
                was_active, queued_before = runner.enqueue(query)
                if runner.stable_prompt and not was_active and queued_before == 0:
                    print_user_message(query)
                if not runner.stable_prompt and not was_active and queued_before == 0:
                    print_user_message(query)
                if (was_active or queued_before) and not runner.stable_prompt:
                    ahead = queued_before + (1 if was_active else 0)
                    print(f"[queued; {ahead} item(s) ahead]")
    finally:
        runtime.authorization_request_handler = None
        runtime.mode_switch_request_handler = None
    return 0
