from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from openagent.cli.commands import _build_session_choices, cmd_chat
from openagent.cli.main import build_parser


class CliResumeTests(unittest.TestCase):
    def test_parser_defaults_to_chat_mode_without_command(self) -> None:
        args = build_parser().parse_args([])
        self.assertIsNone(args.command)
        self.assertFalse(args.resume)

    def test_parser_supports_short_and_single_dash_resume_flags(self) -> None:
        self.assertTrue(build_parser().parse_args(["-r"]).resume)
        self.assertTrue(build_parser().parse_args(["-resume"]).resume)

    def test_cmd_chat_starts_new_session_by_default(self) -> None:
        runtime = SimpleNamespace(
            create_session=lambda: SimpleNamespace(id="new-session", messages=[]),
        )

        with patch("openagent.cli.repl.run_repl", return_value=0) as mock_repl:
            result = cmd_chat(runtime, resume=False)

        self.assertEqual(result, 0)
        self.assertEqual(mock_repl.call_args.args[1].id, "new-session")
        self.assertFalse(mock_repl.call_args.kwargs["resumed"])

    def test_cmd_chat_resume_loads_selected_session(self) -> None:
        session = SimpleNamespace(
            id="session-1",
            updated_at=1.0,
            created_at=1.0,
            messages=[
                {"role": "user", "content": "history question"},
                {"role": "assistant", "content": [{"type": "text", "text": "history answer"}]},
            ],
        )
        runtime = SimpleNamespace(
            list_sessions=lambda: [session],
            load_session=lambda session_id: session if session_id == "session-1" else None,
            create_session=lambda: SimpleNamespace(id="fresh", messages=[]),
        )

        with patch("openagent.cli.commands.choose_session_interactively", return_value="session-1"), patch(
            "openagent.cli.repl.run_repl", return_value=0
        ) as mock_repl:
            result = cmd_chat(runtime, resume=True)

        self.assertEqual(result, 0)
        self.assertEqual(mock_repl.call_args.args[1].id, "session-1")
        self.assertTrue(mock_repl.call_args.kwargs["resumed"])

    def test_cmd_chat_resume_cancellation_falls_back_to_new_session(self) -> None:
        session = SimpleNamespace(id="fresh", messages=[])
        runtime = SimpleNamespace(
            list_sessions=lambda: [SimpleNamespace(id="old", updated_at=1.0, created_at=1.0, messages=[])],
            load_session=lambda session_id: None,
            create_session=lambda: session,
        )

        with patch("openagent.cli.commands.choose_session_interactively", return_value=None), patch(
            "openagent.cli.repl.run_repl", return_value=0
        ) as mock_repl:
            result = cmd_chat(runtime, resume=True)

        self.assertEqual(result, 0)
        self.assertEqual(mock_repl.call_args.args[1].id, "fresh")
        self.assertFalse(mock_repl.call_args.kwargs["resumed"])

    def test_session_history_ignores_empty_or_incomplete_sessions(self) -> None:
        empty = SimpleNamespace(id="empty", updated_at=10.0, created_at=10.0, messages=[])
        only_user = SimpleNamespace(
            id="only-user",
            updated_at=11.0,
            created_at=11.0,
            messages=[{"role": "user", "content": "hello"}],
        )
        only_assistant = SimpleNamespace(
            id="only-assistant",
            updated_at=12.0,
            created_at=12.0,
            messages=[{"role": "assistant", "content": [{"type": "text", "text": "hi"}]}],
        )
        valid = SimpleNamespace(
            id="valid",
            updated_at=13.0,
            created_at=13.0,
            messages=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": [{"type": "text", "text": "hi there"}]},
            ],
        )
        runtime = SimpleNamespace(list_sessions=lambda: [empty, only_user, only_assistant, valid])

        choices = _build_session_choices(runtime)

        self.assertEqual([choice.session_id for choice in choices], ["valid"])


if __name__ == "__main__":
    unittest.main()
