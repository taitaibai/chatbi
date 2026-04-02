from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config.loader import get_semantic_model


class SemanticLoaderTestCase(unittest.TestCase):
    def test_refund_rate_uses_joins_instead_of_filters(self) -> None:
        model = get_semantic_model(force_reload=True)
        sales_domain = next(domain for domain in model.domains if domain.id == "sales")
        refund_rate = next(metric for metric in sales_domain.metrics if metric.id == "refund_rate")

        self.assertEqual(refund_rate.filters, [])
        self.assertEqual(len(refund_rate.joins), 1)
        self.assertEqual(refund_rate.joins[0].table, "fact_refunds")


if __name__ == "__main__":
    unittest.main()
