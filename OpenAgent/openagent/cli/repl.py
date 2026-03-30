from __future__ import annotations

import json

from openagent.cli.commands import ConsoleStreamer
from openagent.cli.prompting import COMMAND_SPECS, create_prompt_session


def run_repl(runtime) -> int:
    session = runtime.create_session()
    prompt_session = None
    try:
        prompt_session = create_prompt_session(runtime.settings.workspace_root)
    except Exception:
        prompt_session = None
    while True:
        try:
            if prompt_session is not None:
                query = prompt_session.prompt("openagent >> ")
            else:
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
        if stripped == "/mcp":
            print(runtime.mcp_status())
            continue
        if stripped == "/bg":
            print(runtime.background_manager.check())
            continue
        if stripped == "/help":
            print("\n".join(f"{command} - {description}" for command, description in COMMAND_SPECS))
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
