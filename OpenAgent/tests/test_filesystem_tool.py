from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from openagent.tools.filesystem import edit_file, write_file


class FilesystemToolTests(unittest.TestCase):
    def test_write_file_returns_diff_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ctx = SimpleNamespace(
                runtime=SimpleNamespace(
                    settings=SimpleNamespace(
                        workspace_root=root,
                        runtime=SimpleNamespace(max_tool_output_chars=50000),
                    )
                )
            )
            result = write_file(ctx, {"path": "demo.txt", "content": "a\nb\n"})

        self.assertEqual(result["path"], "demo.txt")
        self.assertTrue(result["absolute_path"].endswith("demo.txt"))
        self.assertEqual(result["added_lines"], 2)
        self.assertEqual(result["removed_lines"], 0)

    def test_edit_file_returns_diff_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "demo.txt"
            target.write_text("a\nb\n", encoding="utf-8")
            ctx = SimpleNamespace(
                runtime=SimpleNamespace(
                    settings=SimpleNamespace(
                        workspace_root=root,
                        runtime=SimpleNamespace(max_tool_output_chars=50000),
                    )
                )
            )
            result = edit_file(ctx, {"path": "demo.txt", "old_text": "b\n", "new_text": "b\nc\n"})

        self.assertEqual(result["path"], "demo.txt")
        self.assertTrue(result["absolute_path"].endswith("demo.txt"))
        self.assertEqual(result["added_lines"], 1)
        self.assertEqual(result["removed_lines"], 0)


if __name__ == "__main__":
    unittest.main()
