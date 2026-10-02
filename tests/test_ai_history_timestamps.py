from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from catlabel.api import routes_ai
from catlabel.core.models import AIConversation


class AIHistoryTimestampTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine: Engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        engine_patch = patch("catlabel.core.database.engine", self.engine)
        engine_patch.start()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(engine_patch.stop)

    def test_history_create_update_read_and_list_keep_naive_sqlite_timestamps(
        self,
    ) -> None:
        first_id = routes_ai.create_history(
            {"title": "First", "messages": [{"role": "user", "content": "one"}]}
        )["id"]
        second_id = routes_ai.create_history(
            {"title": "Second", "messages": [{"role": "user", "content": "two"}]}
        )["id"]
        assert isinstance(first_id, int)
        assert isinstance(second_id, int)

        first = self._stored_conversation(first_id)
        second = self._stored_conversation(second_id)
        self.assertIsNone(first.updated_at.tzinfo)
        self.assertIsNone(second.updated_at.tzinfo)

        older_id = first_id if first.updated_at <= second.updated_at else second_id
        other_id = second_id if older_id == first_id else first_id
        future_update = max(first.updated_at, second.updated_at) + timedelta(days=1)

        with patch.object(routes_ai, "datetime") as datetime_mock:
            datetime_mock.utcnow.return_value = future_update
            result = routes_ai.update_history(
                older_id,
                {
                    "title": "Updated first",
                    "messages": [{"role": "assistant", "content": "updated"}],
                },
            )

        self.assertEqual(result, {"status": "ok"})

        stored = self._stored_conversation(older_id)
        self.assertEqual(stored.title, "Updated first")
        self.assertEqual(
            stored.messages_json, '[{"role": "assistant", "content": "updated"}]'
        )
        self.assertEqual(stored.updated_at, future_update)
        self.assertIsNone(stored.updated_at.tzinfo)

        raw_timestamp = self._raw_updated_at(older_id)
        parsed_timestamp = datetime.fromisoformat(raw_timestamp)
        self.assertEqual(parsed_timestamp, future_update)
        self.assertIsNone(parsed_timestamp.tzinfo)

        history = routes_ai.get_history(older_id)
        self.assertEqual(history["title"], "Updated first")
        self.assertEqual(
            history["messages"], [{"role": "assistant", "content": "updated"}]
        )

        history_list = routes_ai.get_histories()
        self.assertEqual([item["id"] for item in history_list], [older_id, other_id])
        self.assertEqual(history_list[0]["updated_at"], future_update)
        self.assertIsNone(history_list[0]["updated_at"].tzinfo)

        with self.engine.connect() as connection:
            columns = connection.exec_driver_sql(
                "PRAGMA table_info(aiconversation)"
            ).all()
        self.assertEqual(
            [column[1] for column in columns],
            ["id", "title", "messages_json", "updated_at"],
        )
        timestamp_column = next(
            column for column in columns if column[1] == "updated_at"
        )
        self.assertEqual(timestamp_column[2], "DATETIME")

    def _stored_conversation(self, conversation_id: int) -> AIConversation:
        with self.engine.connect() as connection:
            result = (
                connection.exec_driver_sql(
                    "SELECT id, title, messages_json, updated_at "
                    "FROM aiconversation WHERE id = ?",
                    (conversation_id,),
                )
                .mappings()
                .one()
            )
        updated_at = datetime.fromisoformat(result["updated_at"])
        return AIConversation(
            id=result["id"],
            title=result["title"],
            messages_json=result["messages_json"],
            updated_at=updated_at,
        )

    def _raw_updated_at(self, conversation_id: int) -> str:
        with self.engine.connect() as connection:
            return connection.exec_driver_sql(
                "SELECT updated_at FROM aiconversation WHERE id = ?",
                (conversation_id,),
            ).scalar_one()


if __name__ == "__main__":
    unittest.main()
