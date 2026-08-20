"""Health monitoring system for JARVIS 2.0.

Collects and aggregates health status from various system components.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from core.event_bus import EventBus

# We'll avoid importing specific components to prevent circular dependencies.
# Instead, we'll rely on duck typing: any object with a get_health() method.


class HealthMonitor:
    """Monitors health of registered components and publishes updates."""

    def __init__(self, update_interval: float = 30.0, event_bus: Optional[EventBus] = None) -> None:
        """
        Args:
            update_interval: Seconds between health checks.
            event_bus: Optional event bus to publish health updates.
                       If None, a new EventBus is created.
        """
        self._update_interval = float(update_interval)
        self._event_bus = event_bus or EventBus()
        self._providers: Dict[str, Callable[[], Dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_health: Dict[str, Any] = {}
        self._stop_event = threading.Event()

    def register_provider(self, name: str, provider: Callable[[], Dict[str, Any]]) -> None:
        """Register a health provider.

        Args:
            name: Unique identifier for the provider.
            provider: A callable that returns a dict with health information.
                      Expected keys: at least 'status' (string) and optional 'details'.
        """
        with self._lock:
            self._providers[name] = provider

    def unregister_provider(self, name: str) -> None:
        """Unregister a health provider."""
        with self._lock:
            self._providers.pop(name, None)

    def get_health(self) -> Dict[str, Any]:
        """Get the latest aggregated health data."""
        with self._lock:
            # Return a copy to avoid external mutation
            return dict(self._last_health)

    def start(self) -> None:
        """Start the background health monitoring thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="JARVIS-HealthMonitor"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and wait for it to finish."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        """Background loop to collect and publish health data."""
        while not self._stop_event.wait(self._update_interval):
            try:
                self._collect_and_publish()
            except Exception as e:  # pylint: disable=broad-except
                # Log error but keep the monitor running
                print(f"⚠️  Health monitor error: {e}")

    def _collect_and_publish(self) -> None:
        """Collect health from all providers and publish if changed."""
        health_data: Dict[str, Any] = {
            "timestamp": time.time(),
            "providers": {},
            "overall_status": "healthy",  # Will be updated based on providers
        }

        overall_status = "healthy"
        with self._lock:
            for name, provider in self._providers.items():
                try:
                    provider_health = provider()
                    # Ensure it's a dict
                    if not isinstance(provider_health, dict):
                        provider_health = {"error": "Provider did not return a dict"}
                    health_data["providers"][name] = provider_health

                    # Determine overall status: if any provider is not healthy, overall becomes unhealthy
                    status = str(provider_health.get("status", "")).lower()
                    if status and status != "healthy":
                        overall_status = "unhealthy"
                except Exception as e:  # pylint: disable=broad-except
                    health_data["providers"][name] = {
                        "error": str(e),
                        "status": "error"
                    }
                    overall_status = "unhealthy"

        health_data["overall_status"] = overall_status

        # Compare with last health to see if we should publish
        with self._lock:
            changed = self._last_health != health_data
            if changed:
                self._last_health = health_data

        if changed:
            # Publish event
            self._event_bus.publish(
                "health.update",
                payload=health_data,
                source="HealthMonitor"
            )


# Global health monitor instance (optional)
health_monitor = HealthMonitor()


def register_health_provider(name: str, provider: Callable[[], Dict[str, Any]]) -> None:
    """Convenience function to register a provider with the global monitor."""
    health_monitor.register_provider(name, provider)


def unregister_health_provider(name: str) -> None:
    """Convenience function to unregister a provider."""
    health_monitor.unregister_provider(name)


def start_health_monitor() -> None:
    """Start the global health monitor."""
    health_monitor.start()


def stop_health_monitor() -> None:
    """Stop the global health monitor."""
    health_monitor.stop()


def get_system_health() -> Dict[str, Any]:
    """Get the latest system health data."""
    return health_monitor.get_health()