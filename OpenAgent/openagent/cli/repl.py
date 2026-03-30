from __future__ import annotations

from contextlib import nullcontext
import json
import sys
from queue import Empty, Queue
from threading import Lock, Thread

from openagent.cli.commands import ConsoleStreamer
from openagent.cli.prompting import (
    COMMAND_SPECS,
    PROMPT_TEXT,
    create_prompt_session,
    fallback_prompt_message,
    styled_prompt_message,
)
from openagent.runtime.messages import render_text_content

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
            visible_messages.append(("You", content))
            continue
        if role == "assistant":
            text = render_text_content(content).strip()
            if not text:
                continue
            visible_messages.append(("Assistant", text))
    if not visible_messages:
        print("[resumed session has no visible chat history]")
        return
    print("[resumed history]")
    for speaker, text in visible_messages:
        print(f"{speaker}: {text}")
        print()


class TurnQueueRunner:
    THINKING_TEXT = "AI 思考中..."

    def __init__(self, runtime, session, *, stable_prompt: bool = False) -> None:
        self.runtime = runtime
        self.session = session
        self.stable_prompt = stable_prompt
        self._queue: Queue[str | None] = Queue()
        self._lock = Lock()
        self._worker = Thread(target=self._worker_loop, name="openagent-chat-worker", daemon=True)
        self._active = False
        self._queued = 0
        self._show_thinking = False

    def start(self) -> None:
        self._worker.start()

    def stats(self) -> tuple[bool, int]:
        with self._lock:
            return self._active, self._queued

    def enqueue(self, query: str) -> tuple[bool, int]:
        with self._lock:
            was_active = self._active
            queued_before = self._queued
            self._queued += 1
        self._queue.put(query)
        return was_active, queued_before

    def has_inflight_work(self) -> bool:
        active, queued = self.stats()
        return active or queued > 0

    def close(self, *, drain: bool) -> int:
        dropped = 0
        if not drain:
            dropped = self._clear_pending()
        self._queue.put(None)
        self._worker.join()
        return dropped

    def _clear_pending(self) -> int:
        dropped = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                break
            if item is None:
                self._queue.put(None)
                break
            dropped += 1
            self._queue.task_done()
        if dropped:
            with self._lock:
                self._queued = max(0, self._queued - dropped)
        return dropped

    def _worker_loop(self) -> None:
        while True:
            query = self._queue.get()
            if query is None:
                self._queue.task_done()
                return
            with self._lock:
                self._queued = max(0, self._queued - 1)
                self._active = True
                self._show_thinking = True
            self._render_thinking()
            streamer = ConsoleStreamer(
                start_on_new_line=True,
                line_buffered=self.stable_prompt,
                on_first_output=self._clear_thinking,
            )
            try:
                response = self.runtime.run_turn(self.session, query, text_callback=streamer)
                if streamer.has_output:
                    streamer.finish()
                    print()
                elif response:
                    self._clear_thinking()
                    print()
                    print(response)
                    print()
            except Exception as exc:
                self._clear_thinking()
                print(f"[turn failed] {exc}")
                print()
            finally:
                with self._lock:
                    self._active = False
                    self._show_thinking = False
                self._queue.task_done()

    def _clear_thinking(self) -> None:
        with self._lock:
            if not self._show_thinking:
                return
            self._show_thinking = False
        if self.stable_prompt:
            sys.stdout.write("\x1b[1A\r\x1b[2K\r")
            sys.stdout.flush()

    def _render_thinking(self) -> None:
        if self.stable_prompt:
            print(self.THINKING_TEXT, flush=True)
            return
        print(f"[{self.THINKING_TEXT}]")


def _is_read_only_command(command: str) -> bool:
    return any(command == prefix or command.startswith(f"{prefix} ") for prefix in READ_ONLY_COMMAND_PREFIXES)


def run_repl(runtime, session, resumed: bool = False) -> int:
    prompt_session = None
    try:
        prompt_session = create_prompt_session(runtime.settings.workspace_root)
    except Exception:
        prompt_session = None
    runner = TurnQueueRunner(runtime, session, stable_prompt=prompt_session is not None and patch_stdout is not None)
    runner.start()
    print(f"[session {session.id}]")
    if resumed:
        _print_resumed_history(session)
    prompt_context = patch_stdout(raw=True) if prompt_session is not None and patch_stdout is not None else nullcontext()
    with prompt_context:
        while True:
            try:
                if prompt_session is not None:
                    query = prompt_session.prompt(styled_prompt_message())
                else:
                    if sys.stdout.isatty():
                        query = input(fallback_prompt_message())
                    else:
                        query = input(PROMPT_TEXT)
            except (EOFError, KeyboardInterrupt):
                print()
                active, queued = runner.stats()
                if active or queued:
                    print(f"[waiting for {queued + (1 if active else 0)} in-flight item(s) before exit]")
                runner.close(drain=True)
                break
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
            if was_active or queued_before:
                ahead = queued_before + (1 if was_active else 0)
                print(f"[queued; {ahead} item(s) ahead]")
    return 0
