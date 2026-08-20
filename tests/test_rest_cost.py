"""Cost meter estimates + thin REST /api/health|state|command."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from core.cost_meter import CostMeter, estimate_tokens, estimate_usd
from core.rest_api import attach_rest_routes, build_health, dispatch_command


class CostEstimateTests(unittest.TestCase):
    def test_fast_is_zero_tokens(self) -> None:
        tin, tout = estimate_tokens("chrome aç", complexity="fast")
        self.assertEqual((tin, tout), (0, 0))
        self.assertEqual(estimate_usd(0, 0, input_per_million=3, output_per_million=15), 0.0)

    def test_priced_estimate_from_rates(self) -> None:
        usd = estimate_usd(
            1_000_000,
            500_000,
            input_per_million=1.0,
            output_per_million=2.0,
        )
        self.assertEqual(usd, 2.0)

    def test_meter_logs_request_id_not_invoice(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            meter = CostMeter(
                Path(tmp.name) / "cost.json",
                rates={
                    "chars_per_token": 4,
                    "rates": {
                        "default": {
                            "input_per_million": 3.0,
                            "output_per_million": 15.0,
                        }
                    },
                },
            )
            entry = meter.record(
                "büyük proje yaz",
                brain_path="deep",
                request_id="abc123",
                model="composer-2.5",
            )
            self.assertEqual(entry["request_id"], "abc123")
            self.assertFalse(entry["invoice"])
            self.assertTrue(entry["priced"])
            self.assertGreater(entry["tokens_in"] + entry["tokens_out"], 0)
            self.assertGreaterEqual(entry["estimated_usd"], 0.0)
            totals = meter.totals()
            self.assertFalse(totals.get("invoice"))
            self.assertIn("estimated_usd", totals)
        finally:
            tmp.cleanup()

    def test_unpriced_when_rates_zero(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            meter = CostMeter(Path(tmp.name) / "cost.json")
            entry = meter.record("merhaba", brain_path="deep", request_id="r2")
            self.assertFalse(entry["priced"])
            self.assertEqual(entry["estimated_usd"], 0.0)
            self.assertIn("unpriced", entry["note"])
        finally:
            tmp.cleanup()


class RestDispatchTests(unittest.TestCase):
    def test_empty_command(self) -> None:
        out = dispatch_command("  ")
        self.assertFalse(out["ok"])
        self.assertIn("empty", out["error"])

    def test_os_core_fast_path(self) -> None:
        os_core = MagicMock()
        os_core.try_handle_command.return_value = "Saat 12:00."
        os_core._last_brain_path = "fast"
        out = dispatch_command("saat kaç", os_core=os_core)
        self.assertTrue(out["ok"])
        self.assertEqual(out["speech"], "Saat 12:00.")
        self.assertEqual(out["path"], "fast")
        self.assertTrue(out["request_id"])

    def test_command_fn_takes_precedence(self) -> None:
        os_core = MagicMock()
        os_core.try_handle_command.return_value = "fast"
        out = dispatch_command(
            "x",
            os_core=os_core,
            command_fn=lambda t: f"core:{t}",
        )
        self.assertEqual(out["speech"], "core:x")
        os_core.try_handle_command.assert_not_called()

    def test_health_without_core(self) -> None:
        h = build_health(None)
        self.assertTrue(h["ok"])
        self.assertEqual(h["core"], "not_loaded")
        self.assertFalse(h["hud_required"])


class RestRouteTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        app = web.Application()
        os_core = MagicMock()
        os_core.try_handle_command.return_value = "Tamam."
        os_core._last_brain_path = "fast"
        os_core.security_profile.return_value = {"full_autonomy": True}
        os_core.state.snapshot.return_value.as_dict.return_value = {
            "status": "idle",
            "user_name": "Taha",
        }
        os_core.mcp = None
        os_core.cost_meter = None
        attach_rest_routes(app, os_core=os_core)
        self._os = os_core
        return app

    async def test_health(self) -> None:
        resp = await self.client.get("/api/health")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("ok"))

    async def test_state(self) -> None:
        resp = await self.client.get("/api/state")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("available"))
        self.assertEqual(data.get("status"), "idle")

    async def test_command_post(self) -> None:
        resp = await self.client.post(
            "/api/command",
            data=json.dumps({"text": "saat kaç"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["speech"], "Tamam.")
        self._os.try_handle_command.assert_called_once_with("saat kaç")


if __name__ == "__main__":
    unittest.main()
