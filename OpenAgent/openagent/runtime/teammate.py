from __future__ import annotations

import json
import threading
import time

from openagent.runtime.events import ToolExecutionContext
from openagent.runtime.messages import make_tool_result_message
from openagent.tools.registry import ToolRegistry


class TeammateRuntimeManager:
    def __init__(self, runtime, team_store, bus, task_store, request_tracker):
        self.runtime = runtime
        self.team_store = team_store
        self.bus = bus
        self.task_store = task_store
        self.request_tracker = request_tracker
        self.threads: dict[str, threading.Thread] = {}
        self._repair_state()

    def _repair_state(self) -> None:
        config = self.team_store.load()
        changed = False
        for member in config.get("members", []):
            if member.get("status") == "working":
                member["status"] = "shutdown"
                changed = True
        if changed:
            self.team_store.save(config)

    def _load(self) -> dict:
        return self.team_store.load()

    def _save(self, payload: dict) -> None:
        self.team_store.save(payload)

    def _find(self, name: str) -> dict | None:
        config = self._load()
        for member in config.get("members", []):
            if member.get("name") == name:
                return member
        return None

    def _upsert_member(self, name: str, role: str, status: str) -> None:
        config = self._load()
        for member in config.get("members", []):
            if member.get("name") == name:
                member["role"] = role
                member["status"] = status
                self._save(config)
                return
        config.setdefault("members", []).append({"name": name, "role": role, "status": status})
        self._save(config)

    def _set_status(self, name: str, status: str) -> None:
        config = self._load()
        for member in config.get("members", []):
            if member.get("name") == name:
                member["status"] = status
                self._save(config)
                return

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find(name)
        if member and member.get("status") not in {"idle", "shutdown"}:
            return f"Error: '{name}' is currently {member['status']}"
        self._upsert_member(name, role, "working")
        thread = threading.Thread(target=self._loop, args=(name, role, prompt), daemon=True)
        thread.start()
        self.threads[name] = thread
        return f"Spawned '{name}' (role: {role})"

    def _loop(self, name: str, role: str, prompt: str) -> None:
        messages = [{"role": "user", "content": prompt}]
        registry = ToolRegistry()
        self.runtime.register_worker_tools(registry)
        system_prompt = self.runtime.build_system_prompt(actor=name, role=role)

        while True:
            for _ in range(self.runtime.settings.runtime.max_agent_rounds):
                inbox = self.bus.read_inbox(name)
                for message in inbox:
                    if message.get("type") == "shutdown_request":
                        request_id = message.get("request_id")
                        if request_id:
                            self.request_tracker.mark_shutdown_response(request_id, "accepted")
                            self.bus.send(name, "lead", "Shutting down.", "shutdown_response", {"request_id": request_id})
                        self._set_status(name, "shutdown")
                        return
                    messages.append({"role": "user", "content": json.dumps(message, ensure_ascii=False)})

                turn = self.runtime.complete(system_prompt, messages, registry.schemas())
                messages.append(turn.as_message())
                if not turn.has_tool_calls():
                    break
                ctx = ToolExecutionContext(runtime=self.runtime, session=None, actor=name, trace_id=f"{name}-{int(time.time())}")
                tool_results: list[dict] = []
                idle_requested = False
                for tool_call in turn.tool_calls:
                    if tool_call.name == "idle":
                        idle_requested = True
                        output = "Entering idle phase."
                    else:
                        try:
                            output = registry.execute(ctx, tool_call.name, tool_call.input)
                        except Exception as exc:
                            output = f"Error: {exc}"
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_call_id": tool_call.id,
                            "content": str(output),
                        }
                    )
                messages.append(make_tool_result_message(tool_results))
                if idle_requested:
                    break

            self._set_status(name, "idle")
            resume = False
            poll_total = max(self.runtime.settings.runtime.teammate_idle_timeout_seconds, 1)
            poll_interval = max(self.runtime.settings.runtime.teammate_poll_interval_seconds, 1)
            for _ in range(poll_total // poll_interval):
                time.sleep(poll_interval)
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for message in inbox:
                        if message.get("type") == "shutdown_request":
                            request_id = message.get("request_id")
                            if request_id:
                                self.request_tracker.mark_shutdown_response(request_id, "accepted")
                                self.bus.send(name, "lead", "Shutting down.", "shutdown_response", {"request_id": request_id})
                            self._set_status(name, "shutdown")
                            return
                        messages.append({"role": "user", "content": json.dumps(message, ensure_ascii=False)})
                    resume = True
                    break
                claimable = self.task_store.list_claimable()
                if claimable:
                    task = claimable[0]
                    self.task_store.claim(task["id"], name)
                    messages.append(
                        {
                            "role": "user",
                            "content": f"<auto-claimed>Task #{task['id']}: {task['subject']}\n{task.get('description', '')}</auto-claimed>",
                        }
                    )
                    messages.append({"role": "assistant", "content": f"Claimed task #{task['id']}. Working on it."})
                    resume = True
                    break
            if not resume:
                self._set_status(name, "shutdown")
                return
            self._set_status(name, "working")

    def list_all(self) -> str:
        config = self._load()
        members = config.get("members", [])
        if not members:
            return "No teammates."
        lines = [f"Team: {config.get('team_name', 'default')}"]
        for member in members:
            lines.append(f"  {member['name']} ({member['role']}): {member['status']}")
        return "\n".join(lines)

    def member_names(self) -> list[str]:
        return [member["name"] for member in self._load().get("members", [])]
