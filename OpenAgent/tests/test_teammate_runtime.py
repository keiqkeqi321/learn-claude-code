from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from openagent.collaboration.bus import MessageBus
from openagent.collaboration.protocols import RequestTracker
from openagent.runtime.messages import AssistantTurn, ToolCall
from openagent.runtime.teammate import TeammateRuntimeManager
from openagent.storage.inbox import InboxStore
from openagent.storage.team import TeamStore
from openagent.tools.registry import ToolDefinition


class TeammateRuntimeTests(unittest.TestCase):
    def test_list_all_and_render_log_show_team_log_entry_points(self) -> None:
        class _MemoryTeamStore:
            def __init__(self) -> None:
                self.payload = {"team_name": "default", "members": []}
                self.logs: dict[str, list[dict]] = {}

            def load(self) -> dict:
                return self.payload

            def save(self, payload: dict) -> None:
                self.payload = payload

            def reset_log(self, name: str, payload: dict) -> None:
                self.logs[name] = [payload]

            def append_log(self, name: str, payload: dict) -> None:
                self.logs.setdefault(name, []).append(payload)

            def read_log(self, name: str) -> list[dict]:
                return list(self.logs.get(name, []))

        team_store = _MemoryTeamStore()
        manager = TeammateRuntimeManager(
            runtime=SimpleNamespace(),
            team_store=team_store,
            bus=SimpleNamespace(),
            task_store=SimpleNamespace(),
            request_tracker=SimpleNamespace(),
        )

        manager._upsert_member("Analyst", "algorithm analyst", "working", "running_tool:grep")
        manager._update_member("Analyst", current_tool_log_id="abc123", current_task_id=7)
        manager._append_log("Analyst", "assistant_message", {"content": "I will inspect crease generation."})
        manager._append_log(
            "Analyst",
            "tool_call",
            {
                "tool_name": "grep",
                "tool_input": {"pattern": "crease"},
                "output_preview": "Found 12 matches",
                "tool_log_id": "abc123",
            },
        )

        roster = manager.list_all()
        log_output = manager.render_log("Analyst")

        self.assertIn("View team logs: /teamlog Analyst", roster)
        self.assertIn("tool grep", roster)
        self.assertIn("[team log Analyst]", log_output)
        self.assertIn("assistant: I will inspect crease generation.", log_output)
        self.assertIn("Tool log: /toollog abc123", log_output)

    def test_interrupt_active_stops_teammate_before_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            executed_tools: list[str] = []
            model_seen = False

            runtime = SimpleNamespace(
                settings=SimpleNamespace(
                    runtime=SimpleNamespace(
                        max_agent_rounds=1,
                        teammate_idle_timeout_seconds=1,
                        teammate_poll_interval_seconds=1,
                    )
                ),
                build_system_prompt=lambda actor, role: "system",
                print_tool_event=lambda *args, **kwargs: None,
            )

            def register_worker_tools(registry) -> None:
                registry.register(
                    ToolDefinition(
                        name="probe",
                        description="Test tool.",
                        input_schema={"type": "object", "properties": {}},
                        handler=lambda ctx, payload: executed_tools.append("probe") or "ok",
                    )
                )

            def fake_complete(system_prompt, messages, tools, text_callback=None, should_interrupt=None):
                nonlocal model_seen
                model_seen = True
                deadline = time.time() + 2
                while time.time() < deadline:
                    if should_interrupt is not None and should_interrupt():
                        break
                    time.sleep(0.01)
                return AssistantTurn(
                    stop_reason="tool_use",
                    text_blocks=["I will inspect files."],
                    tool_calls=[ToolCall("call-1", "probe", {})],
                )

            runtime.register_worker_tools = register_worker_tools
            runtime.complete = fake_complete

            manager = TeammateRuntimeManager(
                runtime=runtime,
                team_store=TeamStore(root / "team"),
                bus=MessageBus(InboxStore(root / "inbox")),
                task_store=SimpleNamespace(list_claimable=lambda: [], claim=lambda task_id, owner: None),
                request_tracker=RequestTracker(root / "requests"),
            )

            spawn_result = manager.spawn("worker", "explore", "Inspect the workspace.")

            self.assertIn("Spawned 'worker'", spawn_result)

            deadline = time.time() + 2
            while time.time() < deadline and not model_seen:
                time.sleep(0.01)
            self.assertTrue(model_seen)

            interrupted = manager.interrupt_active(reason="lead_interrupt")
            worker_thread = manager.threads["worker"]
            worker_thread.join(timeout=2)

            self.assertEqual(interrupted, 1)
            self.assertFalse(worker_thread.is_alive())
            self.assertEqual(executed_tools, [])

            member = manager._find("worker")
            self.assertIsNotNone(member)
            self.assertEqual(member["status"], "shutdown")
            self.assertEqual(member["shutdown_reason"], "lead_interrupt")


if __name__ == "__main__":
    unittest.main()
