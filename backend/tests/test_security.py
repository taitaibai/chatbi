from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.security import SQLUnsafeError, security_checker


class SecurityCheckerTestCase(unittest.TestCase):
    def test_rejects_select_star(self) -> None:
        with self.assertRaises(SQLUnsafeError):
            security_checker.validate("SELECT * FROM fact_orders LIMIT 10")

    def test_rejects_non_aggregate_without_limit(self) -> None:
        with self.assertRaises(SQLUnsafeError):
            security_checker.validate("SELECT channel FROM fact_orders WHERE status = 'paid'")

    def test_allows_aggregate_query(self) -> None:
        self.assertTrue(
            security_checker.validate(
                "SELECT channel, SUM(amount) AS gmv FROM fact_orders WHERE status = 'paid' GROUP BY channel"
            )
        )

    def test_rejects_schema_prefixed_table_outside_whitelist(self) -> None:
        with self.assertRaises(SQLUnsafeError):
            security_checker.validate(
                "SELECT channel, SUM(amount) AS gmv FROM hidden_schema.fact_orders GROUP BY channel"
            )


if __name__ == "__main__":
    unittest.main()
