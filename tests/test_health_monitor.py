"""Unit tests for HealthMonitor."""

from __future__ import annotations

import time
import unittest
from unittest.mock import Mock

from core.health_monitor import HealthMonitor, register_health_provider, start_health_monitor, stop_health_monitor, get_system_health
from core.event_bus import EventBus


class HealthMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        # Create a fresh monitor for each test
        self.monitor = HealthMonitor(update_interval=0.1)  # Fast interval for testing
        self.event_bus = EventBus()
        self.monitor._event_bus = self.event_bus  # Inject our event bus to capture events

    def tearDown(self) -> None:
        self.monitor.stop()

    def test_register_provider(self) -> None:
        def provider() -> dict:
            return {"status": "healthy"}

        self.monitor.register_provider("test", provider)
        self.assertIn("test", self.monitor._providers)

    def test_unregister_provider(self) -> None:
        def provider() -> dict:
            return {"status": "healthy"}

        self.monitor.register_provider("test", provider)
        self.monitor.unregister_provider("test")
        self.assertNotIn("test", self.monitor._providers)

    def test_health_collection(self) -> None:
        def healthy_provider() -> dict:
            return {"status": "healthy", "value": 1}

        def unhealthy_provider() -> dict:
            return {"status": "unhealthy", "value": 0}

        self.monitor.register_provider("healthy", healthy_provider)
        self.monitor.register_provider("unhealthy", unhealthy_provider)

        # Trigger a collection
        self.monitor._collect_and_publish()

        health = self.monitor.get_health()
        self.assertEqual(health["overall_status"], "unhealthy")
        self.assertIn("healthy", health["providers"])
        self.assertIn("unhealthy", health["providers"])
        self.assertEqual(health["providers"]["healthy"]["status"], "healthy")
        self.assertEqual(health["providers"]["unhealthy"]["status"], "unhealthy")

    def test_event_publishing(self) -> None:
        def provider() -> dict:
            return {"status": "healthy"}

        self.monitor.register_provider("test", provider)

        # Capture events
        events = []
        def handler(event):
            events.append(event)

        self.event_bus.subscribe("health.update", handler)

        # Start monitor and wait for a tick
        self.monitor.start()
        time.sleep(0.2)  # Wait for at least one update interval (0.1s)
        self.monitor.stop()

        # We should have at least one event
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0].type, "health.update")
        self.assertIn("providers", events[0].payload)
        self.assertIn("test", events[0].payload["providers"])

    def test_global_functions(self) -> None:
        # Test the global convenience functions
        def provider() -> dict:
            return {"status": "healthy"}

        register_health_provider("global_test", provider)
        # The global monitor should have the provider
        # We can't directly access the global monitor's providers, but we can check via get_system_health
        # after starting the monitor.
        start_health_monitor()
        # Trigger a health collection manually for testing (since the update interval is 30 seconds)
        from core.health_monitor import health_monitor
        health_monitor._collect_and_publish()
        health = get_system_health()
        stop_health_monitor()
        # The global monitor should have collected health from our provider
        # Note: there may be other providers registered by other tests, but we assume not.
        # We'll just check that the structure is as expected.
        self.assertIn("providers", health)
        self.assertIn("overall_status", health)
        self.assertIn("global_test", health["providers"])
        self.assertEqual(health["providers"]["global_test"]["status"], "healthy")
        self.assertEqual(health["overall_status"], "healthy")


if __name__ == "__main__":
    unittest.main()