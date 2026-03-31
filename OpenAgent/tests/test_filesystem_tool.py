from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from openagent.tools.filesystem import edit_file, write_file
from openagent.tools.registry import ToolDefinition, ToolRegistry


class FilesystemToolTests(unittest.TestCase):
    def test_write_file_returns_diff_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session = SimpleNamespace(pending_file_changes=[])
            ctx = SimpleNamespace(
                runtime=SimpleNamespace(
                    settings=SimpleNamespace(
                        workspace_root=root,
                        runtime=SimpleNamespace(max_tool_output_chars=50000),
                    )
                ),
                session=session,
            )
            result = write_file(ctx, {"path": "demo.txt", "content": "a\nb\n"})

        self.assertEqual(result["path"], "demo.txt")
        self.assertTrue(result["absolute_path"].endswith("demo.txt"))
        self.assertEqual(result["added_lines"], 2)
        self.assertEqual(result["removed_lines"], 0)
        self.assertEqual(len(session.pending_file_changes), 1)

    def test_edit_file_returns_diff_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "demo.txt"
            target.write_text("a\nb\n", encoding="utf-8")
            session = SimpleNamespace(pending_file_changes=[])
            ctx = SimpleNamespace(
                runtime=SimpleNamespace(
                    settings=SimpleNamespace(
                        workspace_root=root,
                        runtime=SimpleNamespace(max_tool_output_chars=50000),
                    )
                ),
                session=session,
            )
            result = edit_file(ctx, {"path": "demo.txt", "old_text": "b\n", "new_text": "b\nc\n"})

        self.assertEqual(result["path"], "demo.txt")
        self.assertTrue(result["absolute_path"].endswith("demo.txt"))
        self.assertEqual(result["added_lines"], 1)
        self.assertEqual(result["removed_lines"], 0)
        self.assertEqual(len(session.pending_file_changes), 1)

    def test_tool_registry_applies_execution_mode_guard_before_write_handler(self) -> None:
        registry = ToolRegistry()
        called: list[dict[str, str]] = []
        registry.register(
            ToolDefinition(
                name="write_file",
                description="Write content to a file.",
                input_schema={"type": "object", "properties": {}},
                handler=lambda ctx, payload: called.append(payload) or {"status": "ok"},
            )
        )
        ctx = SimpleNamespace(
            runtime=SimpleNamespace(authorize_tool_call=lambda name, payload, ctx=None: "blocked by mode"),
            session=None,
        )

        result = registry.execute(ctx, "write_file", {"path": "demo.txt"})

        self.assertEqual(result, "blocked by mode")
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
