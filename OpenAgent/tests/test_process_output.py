from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openagent.tools.background import BackgroundManager
from openagent.tools.process import CommandResult, decode_output, run_command
from openagent.tools.shell import run_shell


class _FakeJobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.notifications: list[dict] = []

    def create(self, job_id: str, payload: dict) -> None:
        self.jobs[job_id] = dict(payload)

    def update(self, job_id: str, **changes):
        self.jobs[job_id].update(changes)
        return self.jobs[job_id]

    def get(self, job_id: str):
        return self.jobs.get(job_id)

    def list_all(self):
        return self.jobs

    def notify(self, payload: dict) -> None:
        self.notifications.append(payload)


class ProcessOutputTests(unittest.TestCase):
    def test_decode_output_prefers_utf8_for_chinese_bytes(self) -> None:
        text = "提交 git 中文infor"
        self.assertEqual(decode_output(text.encode("utf-8")), text)

    def test_run_command_uses_binary_mode_and_decodes_output(self) -> None:
        with patch("openagent.tools.process.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args="git status",
                returncode=0,
                stdout="提交 git 中文infor".encode("utf-8"),
                stderr=b"",
            )

            result = run_command("git status", shell=True, cwd=Path.cwd(), timeout=10)

        self.assertEqual(result.stdout, "提交 git 中文infor")
        self.assertFalse(mock_run.call_args.kwargs["text"])

    def test_run_shell_returns_unicode_output(self) -> None:
        ctx = SimpleNamespace(
            runtime=SimpleNamespace(
                settings=SimpleNamespace(
                    workspace_root=Path.cwd(),
                    runtime=SimpleNamespace(command_timeout_seconds=15, max_tool_output_chars=500),
                )
            )
        )

        with patch("openagent.tools.shell.run_command") as mock_run:
            mock_run.return_value = CommandResult(
                args="git status",
                returncode=0,
                stdout="提交 git 中文infor\n",
                stderr="",
            )

            result = run_shell(ctx, {"command": "git status"})

        self.assertEqual(result, "提交 git 中文infor")

    def test_background_manager_records_unicode_result(self) -> None:
        store = _FakeJobStore()
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BackgroundManager(store, Path(tmpdir), default_timeout=30, max_output_chars=500)
            store.create("job1", {"id": "job1", "command": "git status", "status": "running", "result": None})

            with patch("openagent.tools.background.run_command") as mock_run:
                mock_run.return_value = CommandResult(
                    args="git status",
                    returncode=0,
                    stdout="提交 git 中文infor",
                    stderr="",
                )

                manager._execute("job1", "git status", 30)

        self.assertEqual(store.jobs["job1"]["status"], "completed")
        self.assertEqual(store.jobs["job1"]["result"], "提交 git 中文infor")


if __name__ == "__main__":
    unittest.main()
