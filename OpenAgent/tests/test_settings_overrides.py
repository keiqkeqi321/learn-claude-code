from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from openagent.config.settings import load_settings


class SettingsOverrideTests(unittest.TestCase):
    def test_load_settings_reads_provider_profiles_and_default_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "openagent.toml").write_text(
                textwrap.dedent(
                    """
                    [providers]
                    default = "anthropic"

                    [providers.anthropic]
                    models = ["glm-5", "claude-sonnet-4-5"]
                    default_model = "glm-5"
                    """
                ).strip(),
                encoding="utf-8",
            )

            settings = load_settings(root)

        self.assertEqual(settings.provider.name, "anthropic")
        self.assertEqual(settings.provider.model, "glm-5")
        self.assertEqual(settings.provider_profiles["anthropic"].models, ["glm-5", "claude-sonnet-4-5"])

    def test_load_settings_can_override_provider_and_model_from_configured_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "openagent.toml").write_text(
                textwrap.dedent(
                    """
                    [providers]
                    default = "anthropic"

                    [providers.anthropic]
                    models = ["glm-5", "claude-sonnet-4-5"]
                    default_model = "glm-5"

                    [providers.openai]
                    models = ["gpt-4.1", "gpt-4.1-mini"]
                    default_model = "gpt-4.1"
                    api_key = "sk-test"
                    base_url = "https://openai.example/v1"
                    organization = "org-test"
                    """
                ).strip(),
                encoding="utf-8",
            )

            settings = load_settings(root, provider_override="openai", model_override="gpt-4.1-mini")

        self.assertEqual(settings.provider.name, "openai")
        self.assertEqual(settings.provider.model, "gpt-4.1-mini")
        self.assertEqual(settings.provider.api_key, "sk-test")
        self.assertEqual(settings.provider.base_url, "https://openai.example/v1")
        self.assertEqual(settings.provider.organization, "org-test")

    def test_load_settings_falls_back_to_builtin_default_when_profiles_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)

        self.assertEqual(settings.provider.name, "anthropic")
        self.assertEqual(settings.provider.model, "claude-sonnet-4-5")
        self.assertEqual(settings.provider_profiles["anthropic"].models, ["claude-sonnet-4-5"])


if __name__ == "__main__":
    unittest.main()
