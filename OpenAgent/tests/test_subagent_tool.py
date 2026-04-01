from __future__ import annotations

import unittest

from openagent.tools.registry import ToolRegistry
from openagent.tools.subagent import register_subagent_tool


class SubagentToolTests(unittest.TestCase):
    def test_registers_subagent_tool_name(self) -> None:
        registry = ToolRegistry()

        register_subagent_tool(registry)

        self.assertIn("subagent", registry.names())
        self.assertNotIn("task", registry.names())
