from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import RequestTrace
from observability.audit import AuditLogger
from session.manager import SessionManager


class SessionManagerTestCase(unittest.TestCase):
    def test_sessions_are_isolated(self) -> None:
        manager = SessionManager(ttl_seconds=60)

        manager.update_context("session-a", "q1", "a1")
        manager.update_context("session-b", "q2", "a2")

        context_a = manager.get_context("session-a")
        context_b = manager.get_context("session-b")

        self.assertEqual(context_a.turns[0].content, "q1")
        self.assertEqual(context_b.turns[0].content, "q2")
        self.assertNotEqual(context_a.session_id, context_b.session_id)


class AuditLoggerTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_log_request_masks_sensitive_fields_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = AuditLogger(Path(temp_dir) / "audit.db")
            await logger.initialize()

            try:
                trace = RequestTrace(
                    request_id="req-1",
                    session_id="session-a",
                    user_id="user@example.com",
                    raw_query="联系我：user@example.com，手机号 13800138000",
                    generated_sql="SELECT * FROM fact_orders WHERE phone = 13800138000",
                )
                await logger.log_request(trace)
                await logger.log_request(trace)
                await logger.close()

                import aiosqlite

                async with aiosqlite.connect(Path(temp_dir) / "audit.db") as db:
                    async with db.execute(
                        "SELECT user_id, raw_query, generated_sql, COUNT(*) OVER () FROM request_audit"
                    ) as cursor:
                        row = await cursor.fetchone()

                self.assertIsNotNone(row)
                self.assertNotEqual(row[0], "user@example.com")
                self.assertIn("[redacted-email]", row[1])
                self.assertIn("[redacted-number]", row[1])
                self.assertEqual(row[3], 1)
            finally:
                await logger.close()


if __name__ == "__main__":
    unittest.main()
