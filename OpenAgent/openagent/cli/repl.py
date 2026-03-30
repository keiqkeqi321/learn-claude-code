from __future__ import annotations

import json

from openagent.cli.commands import ConsoleStreamer


def run_repl(runtime) -> int:
    session = runtime.create_session()
    while True:
        try:
            query = input("openagent >> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        stripped = query.strip()
        if not stripped or stripped in {"q", "exit", "/exit"}:
            break
        if stripped == "/compact":
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
        if stripped == "/bg":
            print(runtime.background_manager.check())
            continue
        if stripped == "/help":
            print("/compact /tasks /team /inbox /bg /help /exit")
            continue
        streamer = ConsoleStreamer()
        response = runtime.run_turn(session, query, text_callback=streamer)
        if streamer.has_output:
            streamer.finish()
            print()
        elif response:
            print(response)
            print()
    return 0
