from __future__ import annotations

import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openagent.runtime.agent import OpenAgentRuntime


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

    def test_build_system_prompt_includes_environment_guidance(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime.settings = SimpleNamespace(
            workspace_root=Path("D:/workspace"),
            agent=SimpleNamespace(system_prompt=None, name="OpenAgent"),
        )
        runtime.skill_loader = SimpleNamespace(descriptions=lambda: "none")

        prompt = OpenAgentRuntime.build_system_prompt(runtime)

        self.assertIn("Execution environment:", prompt)
        self.assertIn("Tool behavior:", prompt)
        self.assertIn("Workspace:", prompt)
        self.assertIn("bash", prompt)


if __name__ == "__main__":
    unittest.main()
