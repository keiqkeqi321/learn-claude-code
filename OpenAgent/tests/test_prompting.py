from __future__ import annotations

import unittest
from types import SimpleNamespace

from openagent.cli.prompting import _handle_tab_action


class PromptingTests(unittest.TestCase):
    def test_tab_accepts_inline_history_suggestion(self) -> None:
        inserted: list[str] = []
        buffer = SimpleNamespace(
            suggestion=SimpleNamespace(text="git"),
            complete_state=None,
            insert_text=lambda text: inserted.append(text),
        )

        handled = _handle_tab_action(buffer)

        self.assertTrue(handled)
        self.assertEqual(inserted, ["git"])

    def test_tab_applies_current_completion(self) -> None:
        applied: list[str] = []
        completion = SimpleNamespace(text="compact")
        buffer = SimpleNamespace(
            suggestion=None,
            complete_state=SimpleNamespace(current_completion=completion, completions=[completion]),
            apply_completion=lambda item: applied.append(item.text),
        )

        handled = _handle_tab_action(buffer)

        self.assertTrue(handled)
        self.assertEqual(applied, ["compact"])

    def test_tab_starts_completion_and_applies_first_result(self) -> None:
        applied: list[str] = []
        completion = SimpleNamespace(text="model")
        buffer = SimpleNamespace(
            suggestion=None,
            complete_state=None,
        )

        def start_completion(*, select_first: bool) -> None:
            self.assertTrue(select_first)
            buffer.complete_state = SimpleNamespace(current_completion=completion, completions=[completion])

        buffer.start_completion = start_completion
        buffer.apply_completion = lambda item: applied.append(item.text)

        handled = _handle_tab_action(buffer)

        self.assertTrue(handled)
        self.assertEqual(applied, ["model"])


if __name__ == "__main__":
    unittest.main()
