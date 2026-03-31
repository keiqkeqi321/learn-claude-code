from __future__ import annotations

import json
from dataclasses import dataclass

from openagent.runtime.agent import OpenAgentRuntime
from openagent.runtime.messages import render_text_content
from openagent.cli.prompting import choose_session_interactively, format_session_timestamp


class ConsoleStreamer:
    def __init__(
        self,
        start_on_new_line: bool = False,
        line_buffered: bool = False,
        on_first_output=None,
    ) -> None:
        self.has_output = False
        self.start_on_new_line = start_on_new_line
        self.line_buffered = line_buffered
        self.on_first_output = on_first_output
        self._pending = ""

    def __call__(self, text: str) -> None:
        if not text:
            return
        if self.line_buffered:
            self._pending += text
            if "\n" not in self._pending:
                return
            before, self._pending = self._pending.rsplit("\n", 1)
            text = before + "\n"
        if not self.has_output and self.on_first_output is not None:
            self.on_first_output()
        if self.start_on_new_line and not self.has_output:
            print()
        print(text, end="", flush=True)
        self.has_output = True

    def finish(self) -> None:
        if self.line_buffered and self._pending:
            if not self.has_output and self.on_first_output is not None:
                self.on_first_output()
            if self.start_on_new_line and not self.has_output:
                print()
            print(self._pending, end="", flush=True)
            self.has_output = True
            self._pending = ""
        if self.has_output:
            print()


@dataclass(slots=True)
class SessionChoice:
    session_id: str
    label: str


def _has_visible_exchange(session) -> bool:
    has_user = False
    has_assistant = False
    for message in session.messages:
        role = message.get("role")
        content = message.get("content")
        if role == "user" and isinstance(content, str):
            if content.startswith("<background-results>") or content.startswith("<inbox>"):
                continue
            if content.strip():
                has_user = True
        elif role == "assistant":
            text = render_text_content(content).strip()
            if text:
                has_assistant = True
        if has_user and has_assistant:
            return True
    return False


def _session_preview(session) -> str:
    for message in reversed(session.messages):
        role = message.get("role")
        content = message.get("content")
        if role == "assistant":
            text = render_text_content(content).strip()
        elif role == "user" and isinstance(content, str):
            if content.startswith("<background-results>") or content.startswith("<inbox>"):
                continue
            text = content.strip()
        else:
            continue
        if text:
            return " ".join(text.split())[:80]
    return "[no visible messages]"


def _build_session_choices(runtime: OpenAgentRuntime) -> list[SessionChoice]:
    choices: list[SessionChoice] = []
    for session in runtime.list_sessions():
        if not _has_visible_exchange(session):
            continue
        stamp = format_session_timestamp(session.updated_at or session.created_at)
        preview = _session_preview(session)
        label = f"{session.id} | {stamp} | {preview}"
        choices.append(SessionChoice(session_id=session.id, label=label))
    return choices


def _select_session(runtime: OpenAgentRuntime):
    choices = _build_session_choices(runtime)
    if not choices:
        print("No saved sessions. Starting a new chat.")
        return runtime.create_session(), False

    selected_id = choose_session_interactively([(item.session_id, item.label) for item in choices])
    if not selected_id:
        print("Session selection cancelled. Starting a new chat.")
        return runtime.create_session(), False
    return runtime.load_session(selected_id), True


def cmd_chat(runtime: OpenAgentRuntime, resume: bool = False) -> int:
    from openagent.cli.repl import run_repl

    session, resumed = _select_session(runtime) if resume else (runtime.create_session(), False)
    return run_repl(runtime, session, resumed=resumed)


def cmd_run(runtime: OpenAgentRuntime, prompt: str) -> int:
    session = runtime.create_session()
    streamer = ConsoleStreamer()
    result = runtime.run_turn(session, prompt, text_callback=streamer)
    if streamer.has_output:
        streamer.finish()
    elif result:
        print(result)
    return 0


def cmd_tasks_list(runtime: OpenAgentRuntime) -> int:
    tasks = runtime.task_store.list_all()
    if not tasks:
        print("No tasks.")
    else:
        for task in tasks:
            print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0


def cmd_tasks_get(runtime: OpenAgentRuntime, task_id: int) -> int:
    print(json.dumps(runtime.task_store.get(task_id), ensure_ascii=False, indent=2))
    return 0


def cmd_compact(runtime: OpenAgentRuntime) -> int:
    session = runtime.latest_session()
    runtime.compact_session(session)
    print(f"Compacted session {session.id}")
    return 0


def cmd_doctor(runtime: OpenAgentRuntime) -> int:
    print(runtime.doctor())
    return 0
