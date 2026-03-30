from __future__ import annotations

import json

from openagent.cli.commands import ConsoleStreamer
from openagent.cli.prompting import COMMAND_SPECS, create_prompt_session
from openagent.runtime.messages import render_text_content


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


def run_repl(runtime, session, resumed: bool = False) -> int:
    prompt_session = None
    try:
        prompt_session = create_prompt_session(runtime.settings.workspace_root)
    except Exception:
        prompt_session = None
    print(f"[session {session.id}]")
    if resumed:
        _print_resumed_history(session)
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
