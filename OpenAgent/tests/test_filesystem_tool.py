from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from openagent.tools.filesystem import edit_file, glob_search, grep_search, safe_path, write_file
from openagent.tools.registry import ToolDefinition, ToolRegistry


class FilesystemToolTests(unittest.TestCase):
    def test_safe_path_normalizes_workspace_root_before_boundary_check(self) -> None:
        class _FakeResolvedPath:
            def __init__(self, value: str) -> None:
                self.value = value

            def resolve(self):
                return self

            def __truediv__(self, relative: str):
                return _FakeJoinedPath(self.value, relative)

            def is_relative_to(self, other) -> bool:
                base = getattr(other, "value", getattr(other, "raw_value", str(other))).rstrip("/\\")
                candidate = self.value.rstrip("/\\")
                return candidate == base or candidate.startswith(base + "\\")

        class _FakeJoinedPath:
            def __init__(self, base_value: str, relative: str) -> None:
                self.base_value = base_value.rstrip("/\\")
                self.relative = relative

            def resolve(self):
                return _FakeResolvedPath(f"{self.base_value}\\{self.relative}")

        class _FakeWorkspaceRoot:
            def __init__(self, raw_value: str, resolved_value: str) -> None:
                self.raw_value = raw_value
                self.resolved_value = resolved_value

            def resolve(self):
                return _FakeResolvedPath(self.resolved_value)

            def __truediv__(self, relative: str):
                return _FakeJoinedPath(self.resolved_value, relative)

            def __str__(self) -> str:
                return self.raw_value

        resolved = safe_path(
            _FakeWorkspaceRoot(
                raw_value=r"C:\Users\KEQIKE~1\AppData\Local\Temp\tmpabcd",
                resolved_value=r"C:\Users\keqikeqi321\AppData\Local\Temp\tmpabcd",
            ),
            "demo.txt",
        )

        self.assertEqual(resolved.value, r"C:\Users\keqikeqi321\AppData\Local\Temp\tmpabcd\demo.txt")

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

    def test_glob_search_returns_matching_workspace_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
            (root / "README.md").write_text("hello\n", encoding="utf-8")
            ctx = SimpleNamespace(
                runtime=SimpleNamespace(
                    settings=SimpleNamespace(
                        workspace_root=root,
                        runtime=SimpleNamespace(max_tool_output_chars=50000),
                    )
                ),
                session=None,
            )

            result = glob_search(ctx, {"pattern": "*.py", "recursive": True})

        self.assertEqual(result, "src/app.py")

    def test_read_file_falls_back_for_gbk_encoded_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "demo.cs"
            target.write_bytes("第一行\n第二行\n".encode("gb18030"))
            ctx = SimpleNamespace(
                runtime=SimpleNamespace(
                    settings=SimpleNamespace(
                        workspace_root=root,
                        runtime=SimpleNamespace(max_tool_output_chars=50000),
                    )
                ),
                session=None,
            )

            from openagent.tools.filesystem import read_file

            result = read_file(ctx, {"path": "demo.cs"})

        self.assertEqual(result, "第一行\n第二行")

    def test_grep_search_returns_matching_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("alpha\nbeta\n", encoding="utf-8")
            (root / "README.md").write_text("beta docs\n", encoding="utf-8")
            ctx = SimpleNamespace(
                runtime=SimpleNamespace(
                    settings=SimpleNamespace(
                        workspace_root=root,
                        runtime=SimpleNamespace(max_tool_output_chars=50000),
                    )
                ),
                session=None,
            )

            result = grep_search(ctx, {"pattern": "beta", "glob": "*.py"})

        self.assertEqual(result, "src/app.py:2:beta")

    def test_grep_search_reads_gbk_encoded_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "demo.cs"
            target.write_bytes("装饰器\n对象池\n".encode("gb18030"))
            ctx = SimpleNamespace(
                runtime=SimpleNamespace(
                    settings=SimpleNamespace(
                        workspace_root=root,
                        runtime=SimpleNamespace(max_tool_output_chars=50000),
                    )
                ),
                session=None,
            )

            result = grep_search(ctx, {"pattern": "对象池", "glob": "*.cs"})

        self.assertEqual(result, "demo.cs:2:对象池")

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
