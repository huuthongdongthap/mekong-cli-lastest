"""Tests for Agent Registry and Dispatcher.

Verifies all 10 agents are registered and resolvable via AGENT_REGISTRY.
"""

import sys
import os
import unittest

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.agent_registry import AgentRegistry
from src.core.agent_base import AgentBase
from src.agents import registry, AGENT_REGISTRY


class TestAgentRegistry(unittest.TestCase):
    """Test AgentRegistry class functionality."""

    def setUp(self):
        """Set up fresh registry for each test."""
        self.test_registry = AgentRegistry()

    def test_register_valid_agent(self):
        """Test registering a valid AgentBase subclass."""
        class TestAgent(AgentBase):
            def plan(self, input_data):
                return []

            def execute(self, task):
                pass

        self.test_registry.register("test", TestAgent)
        retrieved = self.test_registry.get("test")
        self.assertEqual(retrieved, TestAgent)

    def test_register_invalid_agent_warns(self):
        """Test registering non-AgentBase class logs a warning."""
        class NotAnAgent:
            pass

        with self.assertLogs("src.core.agent_registry", level="WARNING") as cm:
            self.test_registry.register("invalid", NotAnAgent)
        self.assertTrue(any("not an AgentBase subclass" in msg for msg in cm.output))

    def test_get_unknown_agent_raises_error(self):
        """Test getting unknown agent raises KeyError with helpful message."""
        with self.assertRaises(KeyError) as context:
            self.test_registry.get("unknown_agent_xyz")
        self.assertIn("Unknown agent", str(context.exception))
        self.assertIn("Available agents", str(context.exception))

    def test_list_agents_sorted(self):
        """Test list_agents returns sorted list."""
        self.test_registry.register("zebra", type("Zebra", (AgentBase,), {
            "plan": lambda self, x: [],
            "execute": lambda self, t: None,
        }))
        self.test_registry.register("alpha", type("Alpha", (AgentBase,), {
            "plan": lambda self, x: [],
            "execute": lambda self, t: None,
        }))
        agents = self.test_registry.list_agents()
        self.assertEqual(agents, ["alpha", "zebra"])

    def test_register_decorator(self):
        """Test decorator registration pattern."""
        @self.test_registry.register_decorator("decorated")
        class DecoratedAgent(AgentBase):
            def plan(self, input_data):
                return []

            def execute(self, task):
                pass

        retrieved = self.test_registry.get("decorated")
        self.assertEqual(retrieved.__name__, "DecoratedAgent")

    def test_contains_method(self):
        """Test __contains__ method for 'in' syntax."""
        self.test_registry.register("test", type("Test", (AgentBase,), {
            "plan": lambda self, x: [],
            "execute": lambda self, t: None,
        }))
        self.assertIn("test", self.test_registry)
        self.assertNotIn("missing", self.test_registry)

    def test_len_method(self):
        """Test __len__ method."""
        self.assertEqual(len(self.test_registry), 0)
        self.test_registry.register("a", type("A", (AgentBase,), {
            "plan": lambda self, x: [],
            "execute": lambda self, t: None,
        }))
        self.test_registry.register("b", type("B", (AgentBase,), {
            "plan": lambda self, x: [],
            "execute": lambda self, t: None,
        }))
        self.assertEqual(len(self.test_registry), 2)


class TestGlobalRegistry(unittest.TestCase):
    """Test the global registry instance in src/agents/__init__.py."""

    def test_all_10_agents_registered(self):
        """Test all 10 core agents are registered."""
        expected_agents = [
            "git",
            "file",
            "shell",
            "database",
            "db",  # Alias
            "lead",
            "content",
            "crawler",
            "workspace",
            "google",  # Alias for workspace
            "monitor",
            "network",
        ]

        for agent_name in expected_agents:
            self.assertIn(agent_name, AGENT_REGISTRY)

    def test_agent_count_minimum(self):
        """Test minimum number of agents registered."""
        # At least 10 core agents (some may be aliases)
        self.assertGreaterEqual(len(AGENT_REGISTRY), 10)

    def test_registry_list_not_empty(self):
        """Test registry.list_agents() returns non-empty list."""
        agents = registry.list_agents()
        self.assertGreater(len(agents), 0)

    def test_all_registered_agents_are_agentbase_subclasses(self):
        """Test all registered agents inherit from AgentBase."""
        for name, cls in AGENT_REGISTRY.items():
            self.assertTrue(
                issubclass(cls, AgentBase),
                f"{name} ({cls}) is not a subclass of AgentBase"
            )

    def test_resolve_and_instantiate_git_agent(self):
        """Test resolving and instantiating GitAgent."""
        GitAgent = registry.get("git")
        agent = GitAgent()
        self.assertEqual(agent.name, "GitAgent")

    def test_resolve_and_instantiate_file_agent(self):
        """Test resolving and instantiating FileAgent."""
        FileAgent = registry.get("file")
        agent = FileAgent()
        self.assertEqual(agent.name, "FileAgent")

    def test_resolve_and_instantiate_shell_agent(self):
        """Test resolving and instantiating ShellAgent."""
        ShellAgent = registry.get("shell")
        agent = ShellAgent()
        self.assertEqual(agent.name, "ShellAgent")

    def test_resolve_and_instantiate_database_agent(self):
        """Test resolving and instantiating DatabaseAgent."""
        DatabaseAgent = registry.get("database")
        agent = DatabaseAgent()
        self.assertEqual(agent.name, "DatabaseAgent")

    def test_resolve_and_instantiate_lead_hunter(self):
        """Test resolving and instantiating LeadHunter."""
        LeadHunter = registry.get("lead")
        agent = LeadHunter()
        self.assertEqual(agent.name, "LeadHunter")

    def test_resolve_and_instantiate_content_writer(self):
        """Test resolving and instantiating ContentWriter."""
        ContentWriter = registry.get("content")
        agent = ContentWriter()
        self.assertEqual(agent.name, "ContentWriter")

    def test_resolve_and_instantiate_recipe_crawler(self):
        """Test resolving and instantiating RecipeCrawler."""
        RecipeCrawler = registry.get("crawler")
        agent = RecipeCrawler()
        self.assertEqual(agent.name, "RecipeCrawler")

    @unittest.mock.patch('src.agents.workspace_agent.WorkspaceAgent._check_gws_installed')
    def test_resolve_and_instantiate_workspace_agent(self, mock_check):
        """Test resolving and instantiating WorkspaceAgent."""
        # Skip if gws CLI not installed (required by WorkspaceAgent.__init__)
        import shutil
        if shutil.which("gws") is None:
            raise unittest.SkipTest("@googleworkspace/cli (gws) not installed")
        WorkspaceAgent = registry.get("workspace")
        agent = WorkspaceAgent()
        self.assertEqual(agent.name, "workspace")

    def test_resolve_and_instantiate_monitor_agent(self):
        """Test resolving and instantiating MonitorAgent."""
        MonitorAgent = registry.get("monitor")
        agent = MonitorAgent()
        self.assertEqual(agent.name, "monitor")

    def test_resolve_and_instantiate_network_agent(self):
        """Test resolving and instantiating NetworkAgent."""
        NetworkAgent = registry.get("network")
        agent = NetworkAgent()
        self.assertEqual(agent.name, "network")


if __name__ == "__main__":
    unittest.main()
