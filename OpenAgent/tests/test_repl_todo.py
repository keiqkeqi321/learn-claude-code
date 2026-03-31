from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from openagent.cli.repl import TurnQueueRunner, _handle_model_command


def _render_prompt_text(fragments) -> str:
    return "".join(text for _, text, *rest in fragments)


class ReplTodoTests(unittest.TestCase):
    def test_prompt_message_shows_open_todos_between_status_and_prompt(self) -> None:
        session = SimpleNamespace(
            todo_items=[
                {"content": "Refactor module", "status": "in_progress", "activeForm": "Refactoring module"},
                {"content": "Add tests", "status": "pending", "activeForm": "Adding tests"},
                {"content": "Run checks", "status": "completed", "activeForm": "Running checks"},
            ]
        )
        runner = TurnQueueRunner(SimpleNamespace(), session, stable_prompt=True)
        runner._status = "thinking"
        runner._thinking_phrase = "Loading genius"
        runner._status_changed_at = 0.0

        rendered = _render_prompt_text(runner.prompt_message())

        self.assertIn("todo (1/3 completed)", rendered)
        self.assertIn("⏳ Refactor module <- Refactoring module", rendered)
        self.assertIn("☐ Add tests", rendered)
        self.assertIn("✅ Run checks", rendered)
        self.assertLess(rendered.index("Loading genius"), rendered.index("todo (1/3 completed)"))
        self.assertLess(rendered.index("todo (1/3 completed)"), rendered.index("openagent >> "))

    def test_prompt_message_hides_todos_when_all_completed(self) -> None:
        session = SimpleNamespace(
            todo_items=[
                {"content": "Refactor module", "status": "completed", "activeForm": "Refactoring module"},
                {"content": "Add tests", "status": "completed", "activeForm": "Adding tests"},
            ]
        )
        runner = TurnQueueRunner(SimpleNamespace(), session, stable_prompt=True)

        rendered = _render_prompt_text(runner.prompt_message())

        self.assertNotIn("todo (", rendered)
        self.assertEqual(rendered, "openagent >> ")

    def test_model_command_switches_provider_and_model_from_interactive_choices(self) -> None:
        runtime = SimpleNamespace(
            configured_provider_profiles=lambda: {
                "anthropic": SimpleNamespace(default_model="glm-5", models=["glm-5", "claude-sonnet-4-5"])
            },
            switch_provider_model=lambda provider, model: f"switched {provider}:{model}",
        )

        with patch("openagent.cli.repl.choose_item_interactively", side_effect=["anthropic", "glm-5"]), patch(
            "builtins.print"
        ) as mock_print:
            _handle_model_command(runtime)

        mock_print.assert_called_with("switched anthropic:glm-5")


if __name__ == "__main__":
    unittest.main()
