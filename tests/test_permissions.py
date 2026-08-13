"""Unit tests for permission levels."""

from __future__ import annotations

import unittest

from security.permissions import PermissionGate, PermissionLevel


class PermissionTests(unittest.TestCase):
    def test_allows_lower_or_equal(self) -> None:
        gate = PermissionGate(PermissionLevel.SYSTEM)
        self.assertTrue(gate.allows(PermissionLevel.READ))
        self.assertTrue(gate.allows(PermissionLevel.LOCAL))
        self.assertTrue(gate.allows(PermissionLevel.SYSTEM))
        self.assertFalse(gate.allows(PermissionLevel.DANGEROUS))

    def test_require_raises(self) -> None:
        gate = PermissionGate(PermissionLevel.LOCAL)
        with self.assertRaises(PermissionError):
            gate.require(PermissionLevel.SYSTEM)

    def test_label(self) -> None:
        gate = PermissionGate(PermissionLevel.READ)
        self.assertEqual(gate.label(), "read")

    def test_int_enum_ordering(self) -> None:
        self.assertLess(PermissionLevel.READ, PermissionLevel.DANGEROUS)


if __name__ == "__main__":
    unittest.main()
