"""Automated test suite for Phase 1 stability improvements."""

from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from core.structured_logger import (
    structured_logger,
    log_user_input,
    log_intent_detected,
    log_tool_started,
    log_tool_completed,
    log_message,
    log_error,
    log_model_request,
    log_model_response,
)
from core.health_monitor import (
    HealthMonitor,
    register_health_provider,
    start_health_monitor,
    stop_health_monitor,
    get_system_health,
)
from core.process_manager import ProcessManager, ProcessType, ProcessConfig
from core.connection_recovery import ConnectionType, connection_recovery


class TestStructuredLogger(unittest.TestCase):
    def test_log_user_input(self) -> None:
        # We can't easily capture the log output, but we can ensure the function doesn't throw
        try:
            log_user_input("test.component", "test command", task_id="task1", execution_id="exec1")
        except Exception as e:
            self.fail(f"log_user_input raised {e}")

    def test_log_intent_detected(self) -> None:
        try:
            log_intent_detected("test.component", "test_intent", 0.95, task_id="task1", execution_id="exec1")
        except Exception as e:
            self.fail(f"log_intent_detected raised {e}")

    def test_log_tool_started_and_completed(self) -> None:
        try:
            log_tool_started("test.component", "test_tool", task_id="task1", execution_id="exec1")
            log_tool_completed("test.component", "test_tool", True, 100.0, task_id="task1", execution_id="exec1")
        except Exception as e:
            self.fail(f"log_tool methods raised {e}")

    def test_log_message_and_error(self) -> None:
        try:
            log_message("test.component", "test message", level="info")
            log_error("test.component", "test error", "TestError", task_id="task1", execution_id="exec1")
        except Exception as e:
            self.fail(f"log_message or log_error raised {e}")

    def test_log_model_request_and_response(self) -> None:
        try:
            log_model_request("test.component", "test-model", "test prompt", task_id="task1", execution_id="exec1")
            log_model_response("test.component", "test-model", "test response", 50.0, task_id="task1", execution_id="exec1")
        except Exception as e:
            self.fail(f"log_model methods raised {e}")


class TestHealthMonitor(unittest.TestCase):
    def setUp(self) -> None:
        self.monitor = HealthMonitor(update_interval=0.1)

    def tearDown(self) -> None:
        self.monitor.stop()

    def test_register_and_unregister_provider(self) -> None:
        def provider() -> dict:
            return {"status": "healthy"}

        self.monitor.register_provider("test", provider)
        self.assertIn("test", self.monitor._providers)

        self.monitor.unregister_provider("test")
        self.assertNotIn("test", self.monitor._providers)

    def test_health_collection_and_overall_status(self) -> None:
        def healthy_provider() -> dict:
            return {"status": "healthy", "value": 1}

        def unhealthy_provider() -> dict:
            return {"status": "unhealthy", "value": 0}

        self.monitor.register_provider("healthy", healthy_provider)
        self.monitor.register_provider("unhealthy", unhealthy_provider)

        # Trigger collection
        self.monitor._collect_and_publish()

        health = self.monitor.get_health()
        self.assertEqual(health["overall_status"], "unhealthy")
        self.assertIn("healthy", health["providers"])
        self.assertIn("unhealthy", health["providers"])
        self.assertEqual(health["providers"]["healthy"]["status"], "healthy")
        self.assertEqual(health["providers"]["unhealthy"]["status"], "unhealthy")

    def test_event_publishing(self) -> None:
        from core.event_bus import EventBus
        event_bus = EventBus()
        self.monitor._event_bus = event_bus

        def provider() -> dict:
            return {"status": "healthy"}

        self.monitor.register_provider("test", provider)

        events = []
        def handler(event):
            events.append(event)

        event_bus.subscribe("health.update", handler)

        self.monitor.start()
        # Wait for at least one tick
        import time
        time.sleep(0.2)
        self.monitor.stop()

        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0].type, "health.update")
        self.assertIn("providers", events[0].payload)
        self.assertIn("test", events[0].payload["providers"])

    def test_global_functions(self) -> None:
        def provider() -> dict:
            return {"status": "healthy"}

        register_health_provider("global_test", provider)
        start_health_monitor()
        # Trigger a health collection manually for testing (since the update interval is 30 seconds)
        from core.health_monitor import health_monitor
        health_monitor._collect_and_publish()
        health = get_system_health()
        stop_health_monitor()

        self.assertIn("providers", health)
        self.assertIn("overall_status", health)
        self.assertIn("global_test", health["providers"])
        self.assertEqual(health["providers"]["global_test"]["status"], "healthy")
        self.assertEqual(health["overall_status"], "healthy")


class TestProcessManager(unittest.TestCase):
    def setUp(self) -> None:
        self.pm = ProcessManager()

    def tearDown(self) -> None:
        self.pm.shutdown()

    def test_spawn_and_terminate_process(self) -> None:
        # Spawn a simple echo process that exits quickly
        config = ProcessConfig(
            process_type=ProcessType.SYSTEM_TOOL,
            name="echo-test",
            restart_on_failure=False,
            cleanup_on_exit=True
        )
        pid = self.pm.spawn_process(["echo", "hello"], config)
        self.assertIsInstance(pid, int)
        self.assertGreater(pid, 0)

        # Give it a moment to finish
        import time
        time.sleep(0.1)

        # Check that the process is no longer running (or at least we can get info)
        proc_info = self.pm.get_process_info(pid)
        self.assertIsNotNone(proc_info)
        # The process might still be in the list but not running
        # We can check is_running property
        if proc_info:
            # It might have already terminated
            pass

        # Clean up: terminate if still running
        if proc_info and proc_info.is_running:
            self.pm.terminate_process(pid, force=True)

    def test_get_stats(self) -> None:
        stats = self.pm.get_stats()
        self.assertIn("total_processes", stats)
        self.assertIn("running_processes", stats)
        self.assertIn("healthy_processes", stats)
        self.assertIn("processes_by_type", stats)
        self.assertIn("process_groups", stats)


class TestConnectionRecovery(unittest.TestCase):
    def test_connection_type_enum(self) -> None:
        self.assertIsInstance(ConnectionType.MCP_STDIO, ConnectionType)
        self.assertEqual(ConnectionType.MCP_STDIO.value, "mcp_stdio")

    def test_set_connection_type(self) -> None:
        # This is a no-op if the connection_id doesn't exist, but shouldn't throw
        try:
            connection_recovery.set_connection_type("test_id", ConnectionType.MCP_STDIO)
        except Exception as e:
            self.fail(f"set_connection_type raised {e}")

    def test_execute_with_recovery_success(self) -> None:
        def operation() -> str:
            return "success"

        result = connection_recovery.execute_with_recovery(
            "test_op",
            operation,
            connection_type=ConnectionType.MCP_STDIO,
            on_failure=lambda e: None
        )
        self.assertEqual(result, "success")

    def test_execute_with_recovery_failure(self) -> None:
        def operation() -> str:
            raise ValueError("test error")

        # Should raise the exception even with on_failure callback
        with self.assertRaises(ValueError) as cm:
            connection_recovery.execute_with_recovery(
                "test_op",
                operation,
                connection_type=ConnectionType.MCP_STDIO,
                on_failure=lambda e: None
            )
        self.assertEqual(str(cm.exception), "test error")


if __name__ == "__main__":
    unittest.main()