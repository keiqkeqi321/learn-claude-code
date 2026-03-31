from __future__ import annotations

import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openagent.config.models import ProviderProfileSettings, ProviderSettings
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
            provider=SimpleNamespace(name="openai", model="kimi-k2.5"),
        )
        runtime.skill_loader = SimpleNamespace(descriptions=lambda: "none")

        prompt = OpenAgentRuntime.build_system_prompt(runtime)

        self.assertIn("Execution environment:", prompt)
        self.assertIn("Tool behavior:", prompt)
        self.assertIn("Workspace:", prompt)
        self.assertIn("bash", prompt)
        self.assertIn("Active provider: openai", prompt)
        self.assertIn("Active model: kimi-k2.5", prompt)
        self.assertIn("Do not claim to be Claude", prompt)

    def test_switch_provider_model_updates_runtime_and_compact_manager(self) -> None:
        runtime = OpenAgentRuntime.__new__(OpenAgentRuntime)
        runtime.settings = SimpleNamespace(
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

        message = OpenAgentRuntime.switch_provider_model(runtime, "openai", "gpt-4.1-mini")

        self.assertIn("gpt-4.1-mini", message)
        self.assertEqual(runtime.settings.provider.name, "openai")
        self.assertEqual(runtime.settings.provider.model, "gpt-4.1-mini")
        self.assertEqual(runtime.provider, {"provider": "openai", "model": "gpt-4.1-mini"})
        self.assertEqual(runtime.compact_manager.provider, {"provider": "openai", "model": "gpt-4.1-mini"})
        self.assertEqual(runtime.compact_manager.model_max_tokens, 4096)


if __name__ == "__main__":
    unittest.main()
