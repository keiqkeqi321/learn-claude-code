from __future__ import annotations

import unittest
from types import SimpleNamespace

from openagent.cli.repl import TurnQueueRunner


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


if __name__ == "__main__":
    unittest.main()
