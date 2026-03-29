# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

from src.config import Config
from src.repositories.market_review_repo import MarketReviewRepository
from src.storage import DatabaseManager


@dataclass
class FakeMarketIndex:
    code: str
    name: str
    current: float
    change_pct: float


@dataclass
class FakeMarketOverview:
    date: str
    indices: list[FakeMarketIndex] = field(default_factory=list)
    total_amount: float = 0.0
    market_condition: str = ""


class MarketReviewRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_market_review_repo.db")
        os.environ["DATABASE_PATH"] = self._db_path
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.repo = MarketReviewRepository(db_manager=self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def test_replace_daily_reviews_serializes_dataclass_overview_and_news_objects(self) -> None:
        overview = FakeMarketOverview(
            date="2026-03-29",
            indices=[
                FakeMarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change_pct=0.36,
                )
            ],
            total_amount=12456.0,
            market_condition="回暖",
        )
        news = [
            SimpleNamespace(
                title="北向资金午后回流",
                snippet="权重股带动指数回升",
                url="https://example.com/news/1",
                source="unit-test",
                published_date="2026-03-29 15:10:00",
            )
        ]

        saved = self.repo.replace_daily_reviews(
            trade_date=date(2026, 3, 29),
            records=[
                {
                    "region": "cn",
                    "report_markdown": "## 2026-03-29 大盘复盘",
                    "overview": overview,
                    "news": news,
                }
            ],
        )

        self.assertEqual(saved, 1)
        rows = self.db.get_market_review_history(trade_date=date(2026, 3, 29), region="cn", limit=5)
        self.assertEqual(len(rows), 1)

        repo_rows = self.repo.list_reviews(trade_date=date(2026, 3, 29), region="cn", limit=5)
        self.assertEqual(len(repo_rows), 1)
        self.assertEqual(repo_rows[0]["overview"]["indices"][0]["name"], "上证指数")
        self.assertEqual(repo_rows[0]["overview"]["total_amount"], 12456.0)
        self.assertEqual(repo_rows[0]["news"][0]["title"], "北向资金午后回流")
        self.assertEqual(repo_rows[0]["news"][0]["source"], "unit-test")

    def test_list_reviews_parses_existing_json_payloads(self) -> None:
        self.db.replace_market_review_history_for_date(
            date(2026, 3, 29),
            [
                {
                    "region": "us",
                    "report_markdown": "## us review",
                    "overview_json": '{"date": "2026-03-29", "market_condition": "震荡"}',
                    "news_json": '[{"title": "US headline"}]',
                }
            ],
        )

        rows = self.repo.list_reviews(trade_date=date(2026, 3, 29), region="us", limit=5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["overview"]["market_condition"], "震荡")
        self.assertEqual(rows[0]["news"][0]["title"], "US headline")


if __name__ == "__main__":
    unittest.main()
