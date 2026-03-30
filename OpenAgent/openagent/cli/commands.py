from __future__ import annotations

import json

from openagent.runtime.agent import OpenAgentRuntime


class ConsoleStreamer:
    def __init__(self) -> None:
        self.has_output = False

    def __call__(self, text: str) -> None:
        if not text:
            return
        print(text, end="", flush=True)
        self.has_output = True

    def finish(self) -> None:
        if self.has_output:
            print()


def cmd_chat(runtime: OpenAgentRuntime) -> int:
    from openagent.cli.repl import run_repl

    return run_repl(runtime)


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
