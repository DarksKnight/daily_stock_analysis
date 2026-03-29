# -*- coding: utf-8 -*-

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import MagicMock

if "pandas" not in sys.modules:
    sys.modules["pandas"] = MagicMock()

from src.config import Config
from src.storage import DatabaseManager


class MarketReviewHistoryStorageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_market_review_history.db")
        os.environ["DATABASE_PATH"] = self._db_path
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def test_replace_market_review_history_for_date_replaces_all_regions(self) -> None:
        trade_date = date(2026, 3, 29)

        first_saved = self.db.replace_market_review_history_for_date(
            trade_date,
            [
                {
                    "region": "cn",
                    "report_markdown": "old-cn",
                    "overview_json": json.dumps({"date": "2026-03-29", "tag": "old-cn"}, ensure_ascii=False),
                    "news_json": json.dumps([{"title": "old-cn"}], ensure_ascii=False),
                },
                {
                    "region": "us",
                    "report_markdown": "old-us",
                    "overview_json": json.dumps({"date": "2026-03-29", "tag": "old-us"}, ensure_ascii=False),
                    "news_json": json.dumps([{"title": "old-us"}], ensure_ascii=False),
                },
            ],
        )
        self.assertEqual(first_saved, 2)

        second_saved = self.db.replace_market_review_history_for_date(
            trade_date,
            [
                {
                    "region": "hk",
                    "report_markdown": "new-hk",
                    "overview_json": json.dumps({"date": "2026-03-29", "tag": "new-hk"}, ensure_ascii=False),
                    "news_json": json.dumps([{"title": "new-hk"}], ensure_ascii=False),
                }
            ],
        )
        self.assertEqual(second_saved, 1)

        rows = self.db.get_market_review_history(trade_date=trade_date, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["region"], "hk")
        self.assertEqual(rows[0]["report_markdown"], "new-hk")
        self.assertEqual(json.loads(rows[0]["overview_json"])["tag"], "new-hk")

    def test_get_market_review_history_supports_date_and_region_filters(self) -> None:
        self.db.replace_market_review_history_for_date(
            date(2026, 3, 28),
            [
                {
                    "region": "cn",
                    "report_markdown": "review-0328",
                    "overview_json": "{}",
                    "news_json": "[]",
                }
            ],
        )
        self.db.replace_market_review_history_for_date(
            date(2026, 3, 29),
            [
                {
                    "region": "us",
                    "report_markdown": "review-0329-us",
                    "overview_json": "{}",
                    "news_json": "[]",
                },
                {
                    "region": "cn",
                    "report_markdown": "review-0329-cn",
                    "overview_json": "{}",
                    "news_json": "[]",
                },
            ],
        )

        date_rows = self.db.get_market_review_history(trade_date=date(2026, 3, 29), limit=10)
        region_rows = self.db.get_market_review_history(trade_date=date(2026, 3, 29), region="us", limit=10)

        self.assertEqual({row["region"] for row in date_rows}, {"cn", "us"})
        self.assertEqual(len(region_rows), 1)
        self.assertEqual(region_rows[0]["report_markdown"], "review-0329-us")


if __name__ == "__main__":
    unittest.main()
