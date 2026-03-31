from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openagent.config.models import ProviderProfileSettings, ProviderSettings
from openagent.runtime.agent import OpenAgentRuntime, TurnInterrupted
from openagent.runtime.session import AgentSession


class RuntimeToolOutputTests(unittest.TestCase):
    def test_todowrite_is_logged_but_not_printed(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime.tool_log_store = SimpleNamespace(write=lambda **kwargs: {"id": "todo-log"})

        class _Stdout(io.StringIO):
            def isatty(self) -> bool:
                return True

        fake_stdout = _Stdout()
        with patch("sys.stdout", fake_stdout):
            log_id = OpenAgentRuntime.print_tool_event(runtime, "lead", "TodoWrite", {"items": []}, "ok")

        self.assertEqual(log_id, "todo-log")
        self.assertEqual(fake_stdout.getvalue(), "")

    def test_file_edit_tool_event_uses_compact_diffstat_output(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime.tool_log_store = SimpleNamespace(write=lambda **kwargs: {"id": "edit-log"})
        runtime._supports_ansi_output = lambda: False

        class _Stdout(io.StringIO):
            def isatty(self) -> bool:
                return True

        fake_stdout = _Stdout()
        with patch("sys.stdout", fake_stdout):
            log_id = OpenAgentRuntime.print_tool_event(
                runtime,
                "lead",
                "edit_file",
                {"path": "openagent/config/settings.py"},
                {
                    "status": "ok",
                    "path": "openagent/config/settings.py",
                    "absolute_path": "D:/workspace/openagent/config/settings.py",
                    "added_lines": 67,
                    "removed_lines": 0,
                },
            )

        rendered = fake_stdout.getvalue()
        self.assertEqual(log_id, "edit-log")
        self.assertIn("edit_file", rendered)
        self.assertIn("View by: /toollog edit-log", rendered)
        self.assertIn("openagent/config/settings.py +67 -0", rendered)
        self.assertLess(rendered.index("edit_file"), rendered.index("View by: /toollog edit-log"))
        self.assertLess(
            rendered.index("View by: /toollog edit-log"),
            rendered.index("openagent/config/settings.py +67 -0"),
        )
        self.assertNotIn("TOOL lead", rendered)

    def test_print_last_turn_file_summary_shows_undo_hint(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime._supports_ansi_output = lambda: False
        session = AgentSession(
            id="session-1",
            last_turn_file_changes=[
                {
                    "path": "greet.py",
                    "absolute_path": "D:/workspace/greet.py",
                    "added_lines": 6,
                    "removed_lines": 0,
                }
            ],
        )

        class _Stdout(io.StringIO):
            def isatty(self) -> bool:
                return True

        fake_stdout = _Stdout()
        with patch("sys.stdout", fake_stdout):
            printed = OpenAgentRuntime.print_last_turn_file_summary(runtime, session)

        rendered = fake_stdout.getvalue()
        self.assertTrue(printed)
        self.assertIn("Changed files", rendered)
        self.assertIn("Undo by: /undo", rendered)
        self.assertIn("greet.py +6 -0", rendered)

    def test_clickable_file_label_uses_hyperlink_and_blue_text_when_ansi_enabled(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime._supports_ansi_output = lambda: True

        rendered = OpenAgentRuntime._format_clickable_file_label(runtime, "greet.py", "D:/workspace/greet.py")

        self.assertIn("greet.py", rendered)
        self.assertIn("\x1b]8;;file:///", rendered)
        self.assertIn("\x1b[38;5;39m", rendered)

    def test_build_system_prompt_includes_environment_guidance(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime.settings = SimpleNamespace(
            workspace_root=Path("D:/workspace"),
            agent=SimpleNamespace(system_prompt=None, name="OpenAgent"),
            provider=SimpleNamespace(name="openai", model="kimi-k2.5"),
        )
        runtime.execution_mode = "plan"
        runtime.skill_loader = SimpleNamespace(descriptions=lambda: "none")

        prompt = OpenAgentRuntime.build_system_prompt(runtime)

        self.assertIn("Execution environment:", prompt)
        self.assertIn("Tool behavior:", prompt)
        self.assertIn("Workspace:", prompt)
        self.assertIn("bash", prompt)
        self.assertIn("Active provider: openai", prompt)
        self.assertIn("Active model: kimi-k2.5", prompt)
        self.assertIn("Current mode: ⏸ plan mode on.", prompt)
        self.assertIn("Return a concrete implementation plan", prompt)
        self.assertIn("Do not claim to be Claude", prompt)

    def test_authorize_tool_call_blocks_non_edit_tools_in_accept_edits_mode(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime.execution_mode = "accept_edits"

        blocked = OpenAgentRuntime.authorize_tool_call(runtime, "bash", {"command": "git status"})
        allowed = OpenAgentRuntime.authorize_tool_call(runtime, "write_file", {"path": "demo.txt", "content": "ok"})

        self.assertIn("requires explicit user approval", blocked)
        self.assertIsNone(allowed)

    def test_authorize_tool_call_blocks_file_edits_in_plan_mode(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime.execution_mode = "plan"

        blocked = OpenAgentRuntime.authorize_tool_call(runtime, "edit_file", {"path": "demo.txt"})

        self.assertIn("workspace files are read-only", blocked)

    def test_switch_provider_model_updates_runtime_and_compact_manager(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime.settings = SimpleNamespace(
            workspace_root=Path("D:/workspace"),
            raw_config={"providers": {}},
            provider=ProviderSettings(name="anthropic", model="glm-5", max_tokens=8000),
            provider_profiles={
                "openai": ProviderProfileSettings(
                    name="openai",
                    models=["gpt-4.1", "gpt-4.1-mini"],
                    default_model="gpt-4.1",
                    api_key="",
                    base_url="https://api.openai.com/v1",
                    max_tokens=4096,
                    timeout_seconds=60,
                )
            },
        )
        runtime.compact_manager = SimpleNamespace(provider=None, model_max_tokens=0)
        runtime.provider = "old-provider"
        runtime._instantiate_provider = lambda provider_settings: {
            "provider": provider_settings.name,
            "model": provider_settings.model,
        }

        with patch("openagent.runtime.agent.persist_provider_selection") as mock_persist:
            message = OpenAgentRuntime.switch_provider_model(runtime, "openai", "gpt-4.1-mini")

        self.assertIn("gpt-4.1-mini", message)
        self.assertIn("saved it to openagent.toml", message)
        self.assertEqual(runtime.settings.provider.name, "openai")
        self.assertEqual(runtime.settings.provider.model, "gpt-4.1-mini")
        self.assertEqual(runtime.provider, {"provider": "openai", "model": "gpt-4.1-mini"})
        self.assertEqual(runtime.compact_manager.provider, {"provider": "openai", "model": "gpt-4.1-mini"})
        self.assertEqual(runtime.compact_manager.model_max_tokens, 4096)
        self.assertEqual(runtime.settings.provider_profiles["openai"].default_model, "gpt-4.1-mini")
        mock_persist.assert_called_once_with(runtime.settings, "openai", "gpt-4.1-mini")

    def test_undo_last_turn_restores_previous_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "greet.py"
            target.write_text("new\n", encoding="utf-8")
            runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
            runtime.settings = SimpleNamespace(workspace_root=root)
            runtime.session_manager = SimpleNamespace(save=lambda session: None)
            session = AgentSession(
                id="session-1",
                undo_stack=[
                    {
                        "turn_id": "turn-1",
                        "files": [
                            {
                                "path": "greet.py",
                                "absolute_path": str(target),
                                "existed_before": True,
                                "previous_content": "old\n",
                            }
                        ],
                    }
                ],
                last_turn_file_changes=[{"path": "greet.py", "added_lines": 1, "removed_lines": 1}],
            )

            message = OpenAgentRuntime.undo_last_turn(runtime, session)

            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(session.undo_stack, [])
            self.assertEqual(session.last_turn_file_changes, [])
            self.assertIn("Undid 1 file change", message)

    def test_complete_does_not_retry_turn_interrupt(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime.settings = SimpleNamespace(provider=SimpleNamespace(max_tokens=1024))
        attempts: list[str] = []

        class _Provider:
            def complete(self, **kwargs):
                attempts.append("called")
                raise TurnInterrupted("Interrupted by user.")

        runtime.provider = _Provider()

        with self.assertRaises(TurnInterrupted):
            OpenAgentRuntime.complete(runtime, "system", [], [], text_callback=None)

        self.assertEqual(attempts, ["called"])


if __name__ == "__main__":
    unittest.main()
