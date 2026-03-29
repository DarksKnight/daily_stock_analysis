# -*- coding: utf-8 -*-

import importlib
import sys
import types
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch


_inserted_stubs = {}


def _install_stub(name: str, module: types.ModuleType) -> None:
    if name not in sys.modules:
        sys.modules[name] = module
        _inserted_stubs[name] = module


search_service_stub = types.ModuleType("src.search_service")
search_service_stub.SearchService = object
_install_stub("src.search_service", search_service_stub)

notification_stub = types.ModuleType("src.notification")
notification_stub.NotificationService = object
_install_stub("src.notification", notification_stub)

analyzer_stub = types.ModuleType("src.analyzer")
analyzer_stub.GeminiAnalyzer = object
_install_stub("src.analyzer", analyzer_stub)

data_provider_pkg = types.ModuleType("data_provider")
data_provider_pkg.__path__ = []
data_provider_base_stub = types.ModuleType("data_provider.base")
data_provider_base_stub.DataFetcherManager = object
data_provider_pkg.base = data_provider_base_stub
_install_stub("data_provider", data_provider_pkg)
_install_stub("data_provider.base", data_provider_base_stub)

market_review_module = importlib.import_module("src.core.market_review")
market_analyzer_module = importlib.import_module("src.market_analyzer")

for name, module in list(_inserted_stubs.items()):
    if sys.modules.get(name) is module:
        del sys.modules[name]

run_market_review = market_review_module.run_market_review
MarketAnalyzer = market_analyzer_module.MarketAnalyzer
MarketOverview = market_analyzer_module.MarketOverview


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
    def test_run_market_review_persists_single_region_success(
        self,
        mock_market_analyzer,
        mock_repo_cls,
        mock_get_config,
    ) -> None:
        mock_get_config.return_value = SimpleNamespace(market_review_region="cn")

        notifier = MagicMock()
        notifier.save_report_to_file.return_value = "/tmp/market_review_20260329.md"
        notifier.is_available.return_value = False

        runner = MagicMock()
        runner.run_daily_review.return_value = "CN review"
        runner._last_overview = {"date": "2026-03-29", "market_condition": "回暖"}
        runner._last_news = [{"title": "cn headline"}]
        mock_market_analyzer.return_value = runner

        result = run_market_review(notifier=notifier, send_notification=False, override_region="cn")

        self.assertEqual(result, "CN review")
        mock_repo_cls.return_value.replace_daily_reviews.assert_called_once()
        self.assertEqual(
            mock_repo_cls.return_value.replace_daily_reviews.call_args.kwargs["records"],
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
        self.assertEqual(
            mock_repo_cls.return_value.replace_daily_reviews.call_args.kwargs["records"],
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


if __name__ == "__main__":
    import unittest

    unittest.main()
