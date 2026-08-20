"""Screen vision / OCR tests — mocked capture and tesseract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.screen_tools import ScreenDescribeTool
from tools.vision import ocr_image, vision_status


class VisionOcrTests(unittest.TestCase):
    def test_vision_status_structure(self) -> None:
        info = vision_status()
        self.assertIn("fallback", info)
        self.assertIn("tesseract", info)

    def test_ocr_image_mocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "x.png"
            img.write_bytes(b"fake")

            class Fake:
                returncode = 0
                stdout = "Hello OCR World\n"
                stderr = ""

            with patch("tools.vision.tesseract_available", return_value=True), patch(
                "tools.vision.subprocess.run", return_value=Fake()
            ):
                text = ocr_image(img)
            self.assertEqual(text, "Hello OCR World")

    def test_describe_uses_ocr_when_available(self) -> None:
        with patch(
            "tools.screen_tools.capture_screen",
            return_value=(True, "/tmp/fake.png"),
        ), patch(
            "tools.screen_tools.ocr_image",
            return_value="Invoice total 42",
        ), patch(
            "tools.screen_tools.frontmost_app_info",
            return_value={"name": "Preview", "bundle": "com.apple.Preview", "title": "doc"},
        ):
            result = ScreenDescribeTool().run({})
        self.assertTrue(result.ok)
        self.assertIn("42", str(result.data))
        self.assertIn("Preview", str(result.data))
        self.assertTrue(
            "OCR" in str(result.data) or "Ekrandaki metin" in str(result.data)
        )

    def test_describe_fallback_metadata(self) -> None:
        with patch(
            "tools.screen_tools.capture_screen",
            return_value=(True, "/tmp/fake.png"),
        ), patch(
            "tools.screen_tools.ocr_image",
            return_value=None,
        ), patch(
            "tools.screen_tools.frontmost_app_info",
            return_value={"name": "Cursor", "bundle": "x", "title": "main"},
        ), patch(
            "tools.screen_tools.vision_status",
            return_value={"note": "Install tesseract"},
        ):
            result = ScreenDescribeTool().run({})
        self.assertTrue(result.ok)
        self.assertIn("Cursor", str(result.data))
        self.assertIn("görebiliyorum", str(result.data).lower())


if __name__ == "__main__":
    unittest.main()
