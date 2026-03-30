from __future__ import annotations

import json
import threading
import time

from openagent.runtime.events import ToolExecutionContext
from openagent.runtime.messages import make_tool_result_message
from openagent.storage.common import now_ts
from openagent.tools.registry import ToolRegistry

UNSET = object()


class TeammateRuntimeManager:
    def __init__(self, runtime, team_store, bus, task_store, request_tracker):
        self.runtime = runtime
        self.team_store = team_store
        self.bus = bus
        self.task_store = task_store
        self.request_tracker = request_tracker
        self.threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._repair_state()

    def _repair_state(self) -> None:
        with self._lock:
            config = self.team_store.load()
            changed = False
            for member in config.get("members", []):
                if member.get("status") in {"starting", "working", "idle"}:
                    member["status"] = "shutdown"
                    member["activity"] = "stale_on_boot"
                    member["shutdown_reason"] = "runtime_restarted"
                    member["last_transition_at"] = now_ts()
                    changed = True
            if changed:
                self.team_store.save(config)

    def _load(self) -> dict:
        with self._lock:
            return self.team_store.load()

    def _save(self, payload: dict) -> None:
        with self._lock:
            self.team_store.save(payload)

    def _find(self, name: str) -> dict | None:
        with self._lock:
            config = self.team_store.load()
            for member in config.get("members", []):
                if member.get("name") == name:
                    return dict(member)
            return None

    def _upsert_member(self, name: str, role: str, status: str, activity: str) -> None:
        ts = now_ts()
        with self._lock:
            config = self.team_store.load()
            for member in config.get("members", []):
                if member.get("name") == name:
                    member["role"] = role
                    member["status"] = status
                    member["activity"] = activity
                    member["last_transition_at"] = ts
                    member["last_activity_at"] = ts
                    member["shutdown_reason"] = None
                    member["current_task_id"] = None
                    member["last_error"] = None
                    self.team_store.save(config)
                    return
            config.setdefault("members", []).append(
                {
                    "name": name,
                    "role": role,
                    "status": status,
                    "activity": activity,
                    "last_transition_at": ts,
                    "last_activity_at": ts,
                    "shutdown_reason": None,
                    "current_task_id": None,
                    "last_error": None,
                }
            )
            self.team_store.save(config)

    def _update_member(
        self,
        name: str,
        *,
        status: str | None = None,
        activity: str | None = None,
        shutdown_reason: str | None = None,
        current_task_id: int | None | object = UNSET,
        last_error: str | None = None,
        touch_activity: bool = True,
    ) -> None:
        with self._lock:
            config = self.team_store.load()
            for member in config.get("members", []):
                if member.get("name") == name:
                    if status is not None and member.get("status") != status:
                        member["status"] = status
                        member["last_transition_at"] = now_ts()
                    if activity is not None:
                        member["activity"] = activity
                    if shutdown_reason is not None or status == "shutdown":
                        member["shutdown_reason"] = shutdown_reason
                    if current_task_id is not UNSET:
                        member["current_task_id"] = current_task_id
                    if last_error is not None:
                        member["last_error"] = last_error
                    if touch_activity:
                        member["last_activity_at"] = now_ts()
                    self.team_store.save(config)
                    return

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find(name)
        if member and member.get("status") not in {"idle", "shutdown"}:
            return f"Error: '{name}' is currently {member['status']}"
        self._upsert_member(name, role, "starting", "booting")
        thread = threading.Thread(target=self._loop, args=(name, role, prompt), daemon=True)
        thread.start()
        self.threads[name] = thread
        return f"Spawned '{name}' (role: {role})"

    def _loop(self, name: str, role: str, prompt: str) -> None:
        messages = [{"role": "user", "content": prompt}]
        registry = ToolRegistry()
        self.runtime.register_worker_tools(registry)
        system_prompt = self.runtime.build_system_prompt(actor=name, role=role)
        self._update_member(name, status="working", activity="starting_work_loop")

        try:
            while True:
                for _ in range(self.runtime.settings.runtime.max_agent_rounds):
                    self._update_member(name, status="working", activity="checking_inbox")
                    inbox = self.bus.read_inbox(name)
                    for message in inbox:
                        if self._handle_control_message(name, message):
                            return
                        messages.append({"role": "user", "content": json.dumps(message, ensure_ascii=False)})

                    self._update_member(name, status="working", activity="waiting_for_model")
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
                            self._update_member(name, status="working", activity="preparing_for_idle")
                            output = "Entering idle phase."
                        else:
                            self._update_member(name, status="working", activity=f"running_tool:{tool_call.name}")
                            try:
                                output = registry.execute(ctx, tool_call.name, tool_call.input)
                                if tool_call.name == "claim_task":
                                    task_id = int(tool_call.input["task_id"])
                                    self._update_member(name, current_task_id=task_id)
                            except Exception as exc:
                                output = f"Error: {exc}"
                                self._update_member(name, last_error=str(exc))
                        self.runtime.print_tool_event(name, tool_call.name, tool_call.input, output)
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

                self._update_member(name, status="idle", activity="idle_polling", current_task_id=None)
                resume = False
                poll_total = max(self.runtime.settings.runtime.teammate_idle_timeout_seconds, 1)
                poll_interval = max(self.runtime.settings.runtime.teammate_poll_interval_seconds, 1)
                for _ in range(max(poll_total // poll_interval, 1)):
                    time.sleep(poll_interval)
                    self._update_member(name, status="idle", activity="idle_polling")
                    inbox = self.bus.read_inbox(name)
                    if inbox:
                        for message in inbox:
                            if self._handle_control_message(name, message):
                                return
                            messages.append({"role": "user", "content": json.dumps(message, ensure_ascii=False)})
                        self._update_member(name, status="working", activity="resuming_from_inbox")
                        resume = True
                        break
                    claimable = self.task_store.list_claimable()
                    if claimable:
                        task = claimable[0]
                        self.task_store.claim(task["id"], name)
                        self._update_member(name, status="working", activity="auto_claimed_task", current_task_id=task["id"])
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
                    self._update_member(
                        name,
                        status="shutdown",
                        activity="idle_timeout",
                        shutdown_reason="idle_timeout",
                        current_task_id=None,
                    )
                    return
                self._update_member(name, status="working", activity="resuming_work")
        except Exception as exc:
            self._update_member(
                name,
                status="shutdown",
                activity="runtime_error",
                shutdown_reason="runtime_error",
                current_task_id=None,
                last_error=str(exc),
            )
            return

    def _handle_control_message(self, name: str, message: dict) -> bool:
        if message.get("type") != "shutdown_request":
            return False
        request_id = message.get("request_id")
        if request_id:
            self.request_tracker.mark_shutdown_response(request_id, "accepted")
            self.bus.send(name, "lead", "Shutting down.", "shutdown_response", {"request_id": request_id})
        self._update_member(
            name,
            status="shutdown",
            activity="shutdown_request",
            shutdown_reason="shutdown_request",
            current_task_id=None,
        )
        return True

    def _refresh_thread_health(self) -> None:
        with self._lock:
            config = self.team_store.load()
            changed = False
            for member in config.get("members", []):
                name = member.get("name")
                thread = self.threads.get(name or "")
                if thread is None:
                    continue
                if not thread.is_alive() and member.get("status") not in {"shutdown"}:
                    member["status"] = "shutdown"
                    member["activity"] = "thread_exited"
                    member["shutdown_reason"] = member.get("shutdown_reason") or "thread_exited"
                    member["last_transition_at"] = now_ts()
                    changed = True
            if changed:
                self.team_store.save(config)

    def _format_age(self, ts: float | None) -> str:
        if not ts:
            return "unknown"
        delta = max(int(now_ts() - ts), 0)
        if delta < 60:
            return f"{delta}s"
        minutes, seconds = divmod(delta, 60)
        if minutes < 60:
            return f"{minutes}m{seconds:02d}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h{minutes:02d}m"

    def list_all(self) -> str:
        self._refresh_thread_health()
        config = self._load()
        members = config.get("members", [])
        if not members:
            return "No teammates."
        lines = [f"Team: {config.get('team_name', 'default')}"]
        for member in members:
            detail = member.get("activity", "unknown")
            extras: list[str] = [detail]
            if member.get("current_task_id") is not None:
                extras.append(f"task #{member['current_task_id']}")
            if member.get("shutdown_reason"):
                extras.append(f"reason={member['shutdown_reason']}")
            last_seen = self._format_age(member.get("last_activity_at"))
            lines.append(
                f"  {member['name']} ({member['role']}): {member['status']} [{', '.join(extras)}] last_seen={last_seen}"
            )
        return "\n".join(lines)

    def member_names(self) -> list[str]:
        return [member["name"] for member in self._load().get("members", [])]
