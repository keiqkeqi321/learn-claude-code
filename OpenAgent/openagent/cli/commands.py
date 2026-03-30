from __future__ import annotations

import json

from openagent.runtime.agent import OpenAgentRuntime


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


def cmd_chat(runtime: OpenAgentRuntime, resume: bool = False) -> int:
    from openagent.cli.repl import run_repl

    session = runtime.latest_session() if resume else runtime.create_session()
    return run_repl(runtime, session, resumed=resume)


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
