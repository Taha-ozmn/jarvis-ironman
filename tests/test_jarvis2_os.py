"""Test suite for JarvisOS (Core Orchestrator)"""

from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock
import tempfile
import sys
from pathlib import Path

# Add the project root to sys.path so we can import core modules
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Mock the problematic external dependencies before importing
sys.modules['yaml'] = MagicMock()
sys.modules['edge_tts'] = MagicMock()
sys.modules['websockets'] = MagicMock()

class TestJarvisOS(unittest.TestCase):
    """Test the JarvisOS core orchestrator"""

    def setUp(self) -> None:
        """Set up a temporary directory and basic config for each test"""
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)

        # Basic config that mimics the structure in config.yaml
        self.config = {
            "jarvis2": {
                "enabled": True,
                "soft_init": True,
                "db_path": "data/jarvis_test.db",
                "full_autonomy": False,  # Safer for testing
                "auto_approve_dangerous": False,
                "auto_approve_level_0_1_2": True,
                "max_permission_level": 2,
                "automation": False,  # Disable automation to avoid side effects
                "automation_tick_seconds": 0.1,  # Fast for testing
                "automation_max_failures": 1,
                "confirm_timeout": 1,
                "deep_max_iterations": 2,
                "plan_timeout_sec": 1,
                "plan_max_retries": 0,
                "proactive": {
                    "enabled": False,  # Disable for simpler testing
                    "seed_daily_briefing": False
                },
                "mcp": {
                    "enabled": False  # Disable MCP for testing
                },
                "memory_recall_limit": 2,
                "memory_recall_max_chars": 100
            },
            "jarvis": {
                "user_name": "test_user",
                "language": "en-GB",
                "model": "composer-2.5",
                "conversation_turns": 5,
                "workspace": str(self.root),
                "narrate": False,
                "fast_mode": True,
                "max_speech_chars": 100,
                "persona": "iron_man",
                "setting_sources": [],
                "skip_model_list": True,
                "background_on_timeout": True,
                "auto_review": False,
                "models": {
                    "default": "composer-2.5"
                }
            },
            "system": {
                "full_shell_access": False  # Safer for testing
            },
            "ui": {
                "enabled": False  # Disable UI for testing
            },
            "voice": {
                "engine": "jarvis",
                "native_voice": "Daniel",
                "speech_rate": "+0%",
                "self_listen_guard": False
            },
            "cost": {
                "enabled": False  # Disable cost metering for testing
            },
            "screen": {
                "always_watch": False
            }
        }

        # Create a mock MacOSController
        self.macos_mock = MagicMock()
        self.macos_mock.full_shell_access = False

        # Import JarvisOS and try_create_os after mocking dependencies
        from core.app import JarvisOS, try_create_os
        self.JarvisOS = JarvisOS
        self.try_create_os = try_create_os

    def tearDown(self) -> None:
        """Clean up after each test"""
        self.test_dir.cleanup()

    def test_initialization(self) -> None:
        """Test that JarvisOS initializes correctly"""
        # Create the JarvisOS instance
        os_core = self.JarvisOS(
            config=self.config,
            root=self.root,
            macos=self.macos_mock
        )

        # Assert that the basic attributes are set
        self.assertIsNotNone(os_core)
        self.assertEqual(os_core.root, self.root)
        self.assertEqual(os_core.config, self.config)
        self.assertFalse(os_core.full_autonomy)
        self.assertTrue(os_core.auto_approve_level_0_1_2)
        # Note: auto_approve_dangerous is not stored as an attribute, so we skip it
        self.assertEqual(os_core.permissions.max_level.value, 2)
        # The db_path is resolved, so we compare with the resolved expected path
        expected_db_path = (self.root / "data" / "jarvis_test.db").resolve()
        self.assertEqual(os_core.db_path, expected_db_path)
        self.assertTrue(os_core._ready)

        # Assert that the db directory was created
        self.assertTrue((self.root / "data").exists())

    def test_health_methods(self) -> None:
        """Test the health and health_cached methods"""
        # Patch the SelfDiagnostics.summary method
        with patch('core.app.SelfDiagnostics') as mock_self_diagnostics:
            # Mock the diagnostics summary method
            mock_self_diagnostics_instance = MagicMock()
            mock_self_diagnostics_instance.summary.return_value = {
                "ok": True,
                "passed": 5,
                "total": 5,
                "checks": []
            }
            mock_self_diagnostics.return_value = mock_self_diagnostics_instance

            # Also need to mock subsystems to avoid actual calls; we can patch get_subsystem_health
            with patch.object(self.JarvisOS, 'get_subsystem_health', return_value={"test_sub": {"ok": True}}):
                # Create the JarvisOS instance
                os_core = self.JarvisOS(
                    config=self.config,
                    root=self.root,
                    macos=self.macos_mock
                )

                # Test health method
                health = os_core.health()
                self.assertEqual(health["ok"], True)
                self.assertEqual(health["passed"], 5)
                self.assertEqual(health["total"], 5)
                # New keys
                self.assertIn("subsystems", health)
                self.assertIsInstance(health["subsystems"], dict)
                self.assertIn("test_sub", health["subsystems"])

                # Test health_cached method (should return the same since no light mode)
                health_cached = os_core.health_cached(max_age_sec=1.0)
                self.assertEqual(health_cached["ok"], True)
                self.assertIn("subsystems", health_cached)
                self.assertEqual(health_cached, health)  # should be same (cache miss first call)

                # Test that the diagnostics summary was called
                mock_self_diagnostics_instance.summary.assert_called()

    def test_command_center(self) -> None:
        """Test the command_center method"""
        # Patch the ui.hud_data.build_command_center function
        with patch('ui.hud_data.build_command_center') as mock_build_cc:
            # Mock the build_command_center function
            mock_build_cc.return_value = {"test": "data"}

            # Create the JarvisOS instance
            os_core = self.JarvisOS(
                config=self.config,
                root=self.root,
                macos=self.macos_mock
            )

            # Call command_center
            result = os_core.command_center()

            # Assert that the build_command_center was called with self
            mock_build_cc.assert_called_once_with(os_core)
            self.assertEqual(result, {"test": "data"})

    def test_recall_for_prompt(self) -> None:
        """Test the recall_for_prompt method"""
        # Patch the MemoryLayers.retrieve_for_prompt method
        with patch('core.app.MemoryLayers') as mock_memory_layers:
            # Mock the memory layers to return a recall block
            mock_memory_layers_instance = MagicMock()
            mock_memory_layers_instance.retrieve_for_prompt.return_value = "Recalled memories"
            mock_memory_layers.return_value = mock_memory_layers_instance

            # Create the JarvisOS instance
            os_core = self.JarvisOS(
                config=self.config,
                root=self.root,
                macos=self.macos_mock
            )

            # Test with a query
            result = os_core.recall_for_prompt("test query")

            # Assertions
            self.assertEqual(result, "Recalled memories")
            mock_memory_layers_instance.retrieve_for_prompt.assert_called_once_with(
                "test query",
                profile_limit=4,
                episodic_limit=2,
                semantic_limit=2,  # From config: memory_recall_limit: 2
                max_chars=180,  # From config: memory_recall_max_chars: 100 + 80
                skip_semantic=False
            )

    def test_try_create_os_helper(self) -> None:
        """Test the try_create_os helper function"""
        # Patch the JarvisOS class
        with patch('core.app.JarvisOS') as mock_jarvis_os:
            # Mock the JarvisOS constructor to return an instance
            mock_instance = MagicMock()
            mock_instance.health.return_value = {"ok": True, "passed": 5, "total": 5}
            mock_jarvis_os.return_value = mock_instance

            # Call try_create_os
            result = self.try_create_os(
                config=self.config,
                root=self.root,
                macos=self.macos_mock
            )

            # Assertions
            self.assertIsNotNone(result)
            self.assertEqual(result, mock_instance)
            # Note: try_create_os calls JarvisOS(config, root=root, macos=macos)
            mock_jarvis_os.assert_called_once_with(
                self.config,  # positional argument
                root=self.root,
                macos=self.macos_mock
            )

    def test_try_create_os_disabled(self) -> None:
        """Test try_create_os when jarvis2.enabled is false"""
        config_disabled = self.config.copy()
        config_disabled["jarvis2"]["enabled"] = False

        # Call try_create_os
        result = self.try_create_os(
            config=config_disabled,
            root=self.root,
            macos=self.macos_mock
        )

        # Assertions
        self.assertIsNone(result)

    def test_subsystem_health_and_trends(self) -> None:
        """Test subsystem health tracking and history"""
        # Create instance
        os_core = self.JarvisOS(
            config=self.config,
            root=self.root,
            macos=self.macos_mock
        )

        # Test get_subsystem_health method
        subsystems = os_core.get_subsystem_health()
        self.assertIsInstance(subsystems, dict)
        # Should have many subsystems
        self.assertGreater(len(subsystems), 10)
        # Each subsystem should have at least an 'ok' key
        for name, health in subsystems.items():
            self.assertIn("ok", health, f"Subsystem {name} missing 'ok' key")
            self.assertIsInstance(health["ok"], bool, f"Subsystem {name} 'ok' should be bool")

        # Test health method includes subsystems
        health = os_core.health()
        self.assertIn("subsystems", health)
        self.assertEqual(health["subsystems"], subsystems)  # should be same dict

        # Test health history tracking
        # Initial call already added to history
        self.assertEqual(len(os_core._health_history), 1)
        history_entry = os_core._health_history[0]
        self.assertIn("ts", history_entry)
        self.assertIn("ok", history_entry)
        self.assertIn("diagnostics_ok", history_entry)
        self.assertIn("subsystems_ok", history_entry)

        # Call health again to see if history grows
        health2 = os_core.health()
        self.assertEqual(len(os_core._health_history), 2)
        # Second entry should have different timestamp (or same if called very fast)
        self.assertGreaterEqual(os_core._health_history[1]["ts"], history_entry["ts"])

if __name__ == "__main__":
    unittest.main()