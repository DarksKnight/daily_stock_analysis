# Market Review History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist complete market review results to the database and replace same-day market review history only after a new run succeeds.

**Architecture:** Add a dedicated `market_review_history` table in `src/storage.py`, extend `MarketReviewRepository` to serialize `MarketOverview` and market-news context into that table, and update `src/core/market_review.py` to collect successful per-region review payloads before replacing one full day of history in a single batch. `MarketAnalyzer` keeps generating the report, but now caches the most recent `overview` and `news` so the control layer can persist them without re-running data collection.

**Tech Stack:** Python, SQLAlchemy ORM, SQLite, unittest/pytest

---

## File Map

- Modify: `src/storage.py`
  - Add the `MarketReviewHistory` ORM model and storage helpers for replace/list/delete.
- Modify: `src/repositories/market_review_repo.py`
  - Accept injected DB instances in tests, serialize `overview/news`, and expose batch replace/list helpers.
- Modify: `src/market_analyzer.py`
  - Cache `self._last_overview` and `self._last_news` during `run_daily_review()`.
- Modify: `src/core/market_review.py`
  - Collect successful region outputs, replace the entire day's history only after at least one new review is generated, and keep existing file-save/notification behavior.
- Modify: `docs/CHANGELOG.md`
  - Append one flat `[改进]` entry under `[Unreleased]`.
- Create: `tests/test_market_review_history_storage.py`
  - Cover day-level replacement and filtered reads on the new table.
- Create: `tests/test_market_review_repo.py`
  - Cover repository serialization of dataclass-based `overview` and object/dict news items.
- Create: `tests/test_market_review_history_flow.py`
  - Cover `MarketAnalyzer` context caching and `run_market_review()` persistence orchestration.

## Task 1: Add Storage Coverage For `market_review_history`

**Files:**
- Create: `tests/test_market_review_history_storage.py`
- Modify: `src/storage.py`

- [ ] **Step 1: Write the failing storage tests**

```python
# tests/test_market_review_history_storage.py
# -*- coding: utf-8 -*-

import json
import os
import tempfile
import unittest
from datetime import date

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
```

- [ ] **Step 2: Run the storage test to verify it fails**

Run: `python -m pytest tests/test_market_review_history_storage.py -q`

Expected: FAIL with `AttributeError: 'DatabaseManager' object has no attribute 'replace_market_review_history_for_date'`

- [ ] **Step 3: Write the minimal storage implementation**

```python
# src/storage.py

class MarketReviewHistory(Base):
    __tablename__ = "market_review_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    region = Column(String(8), nullable=False, index=True)
    report_markdown = Column(Text, nullable=False)
    overview_json = Column(Text, nullable=False, default="{}")
    news_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index("ix_market_review_history_date", "trade_date"),
        Index("ix_market_review_history_date_region", "trade_date", "region"),
    )


def replace_market_review_history_for_date(
    self,
    trade_date: date,
    records: List[Dict[str, Any]],
) -> int:
    if trade_date is None:
        return 0

    rows = []
    try:
        with self.session_scope() as session:
            session.execute(delete(MarketReviewHistory).where(MarketReviewHistory.trade_date == trade_date))
            for item in records:
                rows.append(
                    MarketReviewHistory(
                        trade_date=trade_date,
                        region=item["region"],
                        report_markdown=item["report_markdown"],
                        overview_json=item.get("overview_json", "{}") or "{}",
                        news_json=item.get("news_json", "[]") or "[]",
                    )
                )
            if rows:
                session.add_all(rows)
        return len(rows)
    except Exception as exc:
        logger.error("[大盘] 替换完整复盘历史失败: %s", exc)
        return 0


def get_market_review_history(
    self,
    trade_date: Optional[date] = None,
    region: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    with self.get_session() as session:
        stmt = select(MarketReviewHistory)
        if trade_date is not None:
            stmt = stmt.where(MarketReviewHistory.trade_date == trade_date)
        if region:
            stmt = stmt.where(MarketReviewHistory.region == region)
        rows = (
            session.execute(
                stmt.order_by(desc(MarketReviewHistory.trade_date), desc(MarketReviewHistory.created_at)).limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": row.id,
                "trade_date": row.trade_date,
                "region": row.region,
                "report_markdown": row.report_markdown,
                "overview_json": row.overview_json,
                "news_json": row.news_json,
                "created_at": row.created_at,
            }
            for row in rows
        ]


def delete_market_review_history_for_date(self, trade_date: date) -> int:
    if trade_date is None:
        return 0
    try:
        with self.session_scope() as session:
            result = session.execute(delete(MarketReviewHistory).where(MarketReviewHistory.trade_date == trade_date))
        return int(result.rowcount or 0)
    except Exception as exc:
        logger.error("[大盘] 删除完整复盘历史失败: %s", exc)
        return 0
```

- [ ] **Step 4: Run the storage tests to verify they pass**

Run: `python -m pytest tests/test_market_review_history_storage.py -q`

Expected: PASS

- [ ] **Step 5: Check scope before moving on**

Run: `git diff -- src/storage.py tests/test_market_review_history_storage.py`

Expected: diff only shows the new ORM model and storage helpers plus the targeted tests. Do not commit unless the user explicitly authorizes it.

## Task 2: Add Repository Serialization For `overview` And `news`

**Files:**
- Create: `tests/test_market_review_repo.py`
- Modify: `src/repositories/market_review_repo.py`

- [ ] **Step 1: Write the failing repository test**

```python
# tests/test_market_review_repo.py
# -*- coding: utf-8 -*-

import json
import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace

from src.config import Config
from src.market_analyzer import MarketIndex, MarketOverview
from src.repositories.market_review_repo import MarketReviewRepository
from src.storage import DatabaseManager


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
        overview = MarketOverview(
            date="2026-03-29",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=12.0,
                    change_pct=0.36,
                )
            ],
            up_count=3200,
            down_count=1800,
            total_amount=12456.0,
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

        overview_payload = json.loads(rows[0]["overview_json"])
        news_payload = json.loads(rows[0]["news_json"])
        self.assertEqual(overview_payload["indices"][0]["name"], "上证指数")
        self.assertEqual(overview_payload["total_amount"], 12456.0)
        self.assertEqual(news_payload[0]["title"], "北向资金午后回流")
        self.assertEqual(news_payload[0]["source"], "unit-test")

    def test_list_reviews_returns_parsed_overview_and_news(self) -> None:
        self.db.replace_market_review_history_for_date(
            date(2026, 3, 29),
            [
                {
                    "region": "us",
                    "report_markdown": "## us review",
                    "overview_json": json.dumps({"date": "2026-03-29", "market_condition": "震荡"}),
                    "news_json": json.dumps([{"title": "US headline"}]),
                }
            ],
        )

        rows = self.repo.list_reviews(trade_date=date(2026, 3, 29), region="us", limit=5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["overview"]["market_condition"], "震荡")
        self.assertEqual(rows[0]["news"][0]["title"], "US headline")
```

- [ ] **Step 2: Run the repository test to verify it fails**

Run: `python -m pytest tests/test_market_review_repo.py -q`

Expected: FAIL with `TypeError` for unexpected `db_manager` init arg or `AttributeError` for missing `replace_daily_reviews()`

- [ ] **Step 3: Implement repository serialization and list helpers**

```python
# src/repositories/market_review_repo.py
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Optional, List, Dict, Any

from src.storage import DatabaseManager


class MarketReviewRepository:
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self._db = db_manager or DatabaseManager.get_instance()

    @staticmethod
    def _serialize_overview(overview: Any) -> Dict[str, Any]:
        if overview is None:
            return {}
        if is_dataclass(overview):
            return asdict(overview)
        if isinstance(overview, dict):
            return overview
        if hasattr(overview, "to_dict"):
            return overview.to_dict()
        return json.loads(DatabaseManager._safe_json_dumps(overview))

    @staticmethod
    def _serialize_news_item(item: Any) -> Dict[str, Any]:
        if isinstance(item, dict):
            getter = item.get
        else:
            getter = lambda key, default=None: getattr(item, key, default)
        return {
            "title": getter("title", "") or "",
            "snippet": getter("snippet", "") or "",
            "url": getter("url", "") or "",
            "source": getter("source", "") or "",
            "published_date": getter("published_date", None),
        }

    def replace_daily_reviews(self, trade_date: date, records: List[Dict[str, Any]]) -> int:
        payloads = []
        for item in records:
            payloads.append(
                {
                    "region": item["region"],
                    "report_markdown": item["report_markdown"],
                    "overview_json": DatabaseManager._safe_json_dumps(self._serialize_overview(item.get("overview"))),
                    "news_json": DatabaseManager._safe_json_dumps(
                        [self._serialize_news_item(news) for news in (item.get("news") or [])]
                    ),
                }
            )
        return self._db.replace_market_review_history_for_date(trade_date=trade_date, records=payloads)

    def list_reviews(
        self,
        trade_date: Optional[date] = None,
        region: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        rows = self._db.get_market_review_history(trade_date=trade_date, region=region, limit=limit)
        result = []
        for row in rows:
            result.append(
                {
                    "id": row["id"],
                    "trade_date": row["trade_date"],
                    "region": row["region"],
                    "report_markdown": row["report_markdown"],
                    "overview": json.loads(row["overview_json"] or "{}"),
                    "news": json.loads(row["news_json"] or "[]"),
                    "created_at": row["created_at"],
                }
            )
        return result
```

- [ ] **Step 4: Run the repository tests to verify they pass**

Run: `python -m pytest tests/test_market_review_repo.py -q`

Expected: PASS

- [ ] **Step 5: Review the repository diff**

Run: `git diff -- src/repositories/market_review_repo.py tests/test_market_review_repo.py`

Expected: the repository only gains serialization helpers, injected DB support, and list/replace methods.

## Task 3: Cache Analyzer Context And Persist Reviews From The Control Layer

**Files:**
- Create: `tests/test_market_review_history_flow.py`
- Modify: `src/market_analyzer.py`
- Modify: `src/core/market_review.py`

- [ ] **Step 1: Write the failing flow tests**

```python
# tests/test_market_review_history_flow.py
# -*- coding: utf-8 -*-

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from src.core.market_review import run_market_review
from src.market_analyzer import MarketAnalyzer, MarketOverview


class MarketReviewHistoryFlowTestCase(TestCase):
    def test_run_daily_review_caches_overview_and_news(self) -> None:
        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        overview = MarketOverview(date="2026-03-29")
        news = [{"title": "热点回流", "url": "https://example.com"}]

        analyzer.get_market_overview = MagicMock(return_value=overview)
        analyzer.search_market_news = MagicMock(return_value=news)
        analyzer.generate_market_review = MagicMock(return_value="## review")

        result = MarketAnalyzer.run_daily_review(analyzer)

        self.assertEqual(result, "## review")
        self.assertIs(analyzer._last_overview, overview)
        self.assertEqual(analyzer._last_news, news)

    @patch("src.core.market_review.get_config")
    @patch("src.core.market_review.MarketReviewRepository")
    @patch("src.core.market_review.MarketAnalyzer")
    def test_run_market_review_replaces_history_with_successful_regions_only(
        self,
        mock_market_analyzer,
        mock_repo_cls,
        mock_get_config,
    ) -> None:
        mock_get_config.return_value = SimpleNamespace(market_review_region="both")

        notifier = MagicMock()
        notifier.save_report_to_file.return_value = "/tmp/market_review_20260329.md"
        notifier.is_available.return_value = False

        cn_runner = MagicMock()
        cn_runner.run_daily_review.return_value = "CN review"
        cn_runner._last_overview = {"date": "2026-03-29", "market_condition": "回暖"}
        cn_runner._last_news = [{"title": "cn headline"}]

        us_runner = MagicMock()
        us_runner.run_daily_review.return_value = None
        us_runner._last_overview = {"date": "2026-03-29", "market_condition": "unused"}
        us_runner._last_news = [{"title": "us headline"}]

        mock_market_analyzer.side_effect = [cn_runner, us_runner]

        result = run_market_review(notifier=notifier, send_notification=False, override_region="both")

        self.assertIn("# A股大盘复盘", result)
        mock_repo_cls.return_value.replace_daily_reviews.assert_called_once()
        saved_records = mock_repo_cls.return_value.replace_daily_reviews.call_args.kwargs["records"]
        self.assertEqual(
            saved_records,
            [
                {
                    "region": "cn",
                    "report_markdown": "CN review",
                    "overview": {"date": "2026-03-29", "market_condition": "回暖"},
                    "news": [{"title": "cn headline"}],
                }
            ],
        )

    @patch("src.core.market_review.get_config")
    @patch("src.core.market_review.MarketReviewRepository")
    @patch("src.core.market_review.MarketAnalyzer")
    def test_run_market_review_keeps_old_history_when_every_region_fails(
        self,
        mock_market_analyzer,
        mock_repo_cls,
        mock_get_config,
    ) -> None:
        mock_get_config.return_value = SimpleNamespace(market_review_region="cn")

        notifier = MagicMock()
        runner = MagicMock()
        runner.run_daily_review.return_value = None
        runner._last_overview = None
        runner._last_news = []
        mock_market_analyzer.return_value = runner

        result = run_market_review(notifier=notifier, send_notification=False, override_region="cn")

        self.assertIsNone(result)
        mock_repo_cls.return_value.replace_daily_reviews.assert_not_called()
```

- [ ] **Step 2: Run the flow tests to verify they fail**

Run: `python -m pytest tests/test_market_review_history_flow.py -q`

Expected: FAIL because `MarketAnalyzer.run_daily_review()` does not populate `_last_news` and `run_market_review()` never calls `replace_daily_reviews()`

- [ ] **Step 3: Implement analyzer caching and control-layer replacement**

```python
# src/market_analyzer.py
class MarketAnalyzer:
    def __init__(self, search_service: Optional[SearchService] = None, analyzer=None, region: str = "cn"):
        self.config = get_config()
        self.search_service = search_service
        self.analyzer = analyzer
        self.data_manager = DataFetcherManager()
        self.region = region if region in ("cn", "us", "hk") else "cn"
        self.profile: MarketProfile = get_profile(self.region)
        self.strategy = get_market_strategy_blueprint(self.region)
        self._last_overview: Optional[MarketOverview] = None
        self._last_news: List[Dict[str, Any]] = []

    def run_daily_review(self) -> str:
        logger.info("========== 开始大盘复盘分析 ==========")

        overview = self.get_market_overview()
        news = self.search_market_news()
        report = self.generate_market_review(overview, news)

        self._last_overview = overview
        self._last_news = list(news or [])

        logger.info("========== 大盘复盘分析完成 ==========")
        return report
```

```python
# src/core/market_review.py
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from src.repositories.market_review_repo import MarketReviewRepository


def _build_history_record(region: str, report: str, market_analyzer: MarketAnalyzer) -> Dict[str, Any]:
    return {
        "region": region,
        "report_markdown": report,
        "overview": getattr(market_analyzer, "_last_overview", None),
        "news": getattr(market_analyzer, "_last_news", []),
    }


def _replace_review_history(records: List[Dict[str, Any]]) -> None:
    if not records:
        return
    repo = MarketReviewRepository()
    saved = repo.replace_daily_reviews(trade_date=date.today(), records=records)
    logger.info("[大盘] 完整复盘历史已替换: %d 条", saved)


def run_market_review(
    notifier: NotificationService,
    analyzer: Optional[GeminiAnalyzer] = None,
    search_service: Optional[SearchService] = None,
    send_notification: bool = True,
    merge_notification: bool = False,
    override_region: Optional[str] = None,
) -> Optional[str]:
    logger.info("开始执行大盘复盘分析...")
    config = get_config()
    region = override_region if override_region is not None else (getattr(config, "market_review_region", "cn") or "cn")
    if region not in ("cn", "hk", "us", "both", "all"):
        region = "cn"

    history_records = []

    try:
        if region in ("both", "all"):
            regions_to_run = ["cn", "us"] if region == "both" else ["cn", "hk", "us"]
            region_labels = {"cn": "A股", "hk": "港股", "us": "美股"}
            reports = {}
            for r in regions_to_run:
                r_analyzer = MarketAnalyzer(search_service=search_service, analyzer=analyzer, region=r)
                logger.info(f"生成{region_labels[r]}大盘复盘报告...")
                r_report = r_analyzer.run_daily_review()
                if r_report:
                    reports[r] = r_report
                    history_records.append(_build_history_record(r, r_report, r_analyzer))

            review_report = ""
            for r in regions_to_run:
                if r in reports:
                    label = region_labels[r]
                    if review_report:
                        review_report += f"\\n\\n---\\n\\n> 以下为{label}大盘复盘\\n\\n"
                    review_report += f"# {label}大盘复盘\\n\\n{reports[r]}"
            if not review_report:
                review_report = None
        else:
            market_analyzer = MarketAnalyzer(search_service=search_service, analyzer=analyzer, region=region)
            review_report = market_analyzer.run_daily_review()
            if review_report:
                history_records.append(_build_history_record(region, review_report, market_analyzer))

        if review_report:
            try:
                _replace_review_history(history_records)
            except Exception as exc:
                logger.error("[大盘] 完整复盘历史持久化失败: %s", exc)

            date_str = datetime.now().strftime("%Y%m%d")
            report_filename = f"market_review_{date_str}.md"
            filepath = notifier.save_report_to_file(f"# 🎯 大盘复盘\n\n{review_report}", report_filename)
            logger.info(f"大盘复盘报告已保存: {filepath}")

            if merge_notification and send_notification:
                logger.info("合并推送模式：跳过大盘复盘单独推送，将在个股+大盘复盘后统一发送")
            elif send_notification and notifier.is_available():
                report_content = f"🎯 大盘复盘\n\n{review_report}"
                success = notifier.send(report_content, email_send_to_all=True)
                if success:
                    logger.info("大盘复盘推送成功")
                else:
                    logger.warning("大盘复盘推送失败")
            elif not send_notification:
                logger.info("已跳过推送通知 (--no-notify)")

            return review_report

    except Exception as exc:
        logger.error(f"大盘复盘分析失败: {exc}")

    return None
```

- [ ] **Step 4: Run the flow tests to verify they pass**

Run: `python -m pytest tests/test_market_review_history_flow.py -q`

Expected: PASS

- [ ] **Step 5: Run the existing market review regression to confirm no breakage**

Run: `python -m pytest tests/test_market_analyzer_generate_text.py tests/test_market_analyzer_sector_limit_fallback.py -q`

Expected: PASS

## Task 4: Update Changelog And Run Backend Verification

**Files:**
- Modify: `docs/CHANGELOG.md`
- Reuse: `src/storage.py`, `src/repositories/market_review_repo.py`, `src/market_analyzer.py`, `src/core/market_review.py`
- Reuse: `tests/test_market_review_history_storage.py`, `tests/test_market_review_repo.py`, `tests/test_market_review_history_flow.py`

- [ ] **Step 1: Add the changelog entry**

```markdown
- [改进] 大盘复盘现在会把完整 Markdown 报告、`overview` 快照和新闻上下文写入 `market_review_history` 表；同日重复成功执行时会先清空当天旧复盘，再写入本次成功生成的市场区域记录。
```

- [ ] **Step 2: Run targeted Python syntax verification**

Run: `python -m py_compile src/storage.py src/repositories/market_review_repo.py src/market_analyzer.py src/core/market_review.py tests/test_market_review_history_storage.py tests/test_market_review_repo.py tests/test_market_review_history_flow.py`

Expected: no output

- [ ] **Step 3: Run the targeted test suite**

Run: `python -m pytest tests/test_market_review_history_storage.py tests/test_market_review_repo.py tests/test_market_review_history_flow.py tests/test_market_analyzer_generate_text.py tests/test_market_analyzer_sector_limit_fallback.py -q`

Expected: PASS

- [ ] **Step 4: Run the backend gate**

Run: `./scripts/ci_gate.sh`

Expected: PASS

- [ ] **Step 5: Final diff review**

Run: `git diff -- src/storage.py src/repositories/market_review_repo.py src/market_analyzer.py src/core/market_review.py tests/test_market_review_history_storage.py tests/test_market_review_repo.py tests/test_market_review_history_flow.py docs/CHANGELOG.md`

Expected: only the planned persistence, orchestration, tests, and changelog changes are present. Do not commit unless the user explicitly approves.

## Self-Review

- Spec coverage:
  - Dedicated `market_review_history` table: covered in Task 1
  - Full review markdown + `overview` + `news` persistence: covered in Tasks 1-3
  - Same-day replacement only after at least one new review succeeds: covered in Task 3
  - Partial success for `both/all` replacing the whole day with the successful subset: covered in Task 3 tests
  - Changelog update and backend verification: covered in Task 4
- Placeholder scan:
  - No placeholder markers or undefined helper references remain.
- Type consistency:
  - Storage layer writes raw JSON strings.
  - Repository layer serializes/deserializes Python objects.
  - Control layer passes `overview/news` objects to the repository rather than writing JSON directly.
