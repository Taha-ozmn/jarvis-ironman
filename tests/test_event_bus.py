"""Unit tests for EventBus."""

from __future__ import annotations

import unittest

from core.event_bus import Event, EventBus


class EventBusTests(unittest.TestCase):
    def test_publish_subscribe(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("cmd", lambda e: received.append(e))
        event = bus.publish("cmd", {"text": "hello"}, source="test")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].payload["text"], "hello")
        self.assertEqual(event.type, "cmd")
        self.assertTrue(event.event_id)

    def test_wildcard(self) -> None:
        bus = EventBus()
        types: list[str] = []
        bus.subscribe("*", lambda e: types.append(e.type))
        bus.publish("a")
        bus.publish("b")
        self.assertEqual(types, ["a", "b"])

    def test_unsubscribe(self) -> None:
        bus = EventBus()
        hits: list[int] = []

        def handler(_e: Event) -> None:
            hits.append(1)

        bus.subscribe("x", handler)
        bus.publish("x")
        bus.unsubscribe("x", handler)
        bus.publish("x")
        self.assertEqual(hits, [1])

    def test_handler_exception_isolated(self) -> None:
        bus = EventBus()
        ok: list[str] = []

        def bad(_e: Event) -> None:
            raise RuntimeError("boom")

        def good(e: Event) -> None:
            ok.append(e.type)

        bus.subscribe("t", bad)
        bus.subscribe("t", good)
        bus.publish("t")
        self.assertEqual(ok, ["t"])

    def test_recent_history(self) -> None:
        bus = EventBus()
        for i in range(5):
            bus.publish("n", {"i": i})
        recent = bus.recent(3)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[-1].payload["i"], 4)


if __name__ == "__main__":
    unittest.main()
