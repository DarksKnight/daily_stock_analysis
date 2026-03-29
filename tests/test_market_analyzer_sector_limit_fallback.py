# -*- coding: utf-8 -*-
"""Regression tests for sector limit-stat fallback in market review."""

import sys
import types
from unittest.mock import MagicMock, call, patch


# market_analyzer only needs the SearchService symbol at import time.
search_service_stub = types.ModuleType("src.search_service")
search_service_stub.SearchService = object
sys.modules.setdefault("src.search_service", search_service_stub)

# The regression test instantiates MarketAnalyzer via __new__, so a lightweight
# DataFetcherManager symbol is enough and avoids importing pandas-dependent code.
data_provider_pkg = types.ModuleType("data_provider")
data_provider_pkg.__path__ = []
data_provider_base_stub = types.ModuleType("data_provider.base")
data_provider_base_stub.DataFetcherManager = object
data_provider_pkg.base = data_provider_base_stub
sys.modules.setdefault("data_provider", data_provider_pkg)
sys.modules.setdefault("data_provider.base", data_provider_base_stub)

from src.market_analyzer import MarketAnalyzer, MarketOverview


class TestMarketAnalyzerSectorLimitFallback:
    def test_sector_limit_rankings_fall_back_to_recent_trade_date(self):
        ma = MarketAnalyzer.__new__(MarketAnalyzer)
        ma.region = "cn"
        ma.data_manager = MagicMock()
        ma._save_sector_snapshot = MagicMock()

        ma.data_manager.get_sector_rankings.return_value = (
            [
                {"name": "半导体", "change_pct": 3.2},
                {"name": "证券", "change_pct": 1.8},
            ],
            [
                {"name": "煤炭", "change_pct": -1.5},
            ],
        )
        ma.data_manager.get_concept_sector_rankings.return_value = ([], [])
        ma.data_manager.get_sector_limit_stats.side_effect = [
            [],
            [
                {
                    "name": "半导体",
                    "change_pct": 3.2,
                    "limit_up_count": 4,
                    "limit_down_count": 0,
                    "up_count": 38,
                    "down_count": 2,
                },
                {
                    "name": "煤炭",
                    "change_pct": -1.5,
                    "limit_up_count": 0,
                    "limit_down_count": 2,
                    "up_count": 5,
                    "down_count": 18,
                },
            ],
        ]

        with patch.object(ma, "_get_recent_sector_limit_trade_dates", return_value=["20260329", "20260328"]):
            overview = MarketOverview(date="2026-03-29")
            ma._get_sector_rankings(overview)

        assert ma.data_manager.get_sector_limit_stats.call_args_list == [
            call(trade_date="20260329"),
            call(trade_date="20260328"),
        ]
        assert overview.top_sectors[0]["name"] == "半导体"
        assert overview.top_sectors[0]["limit_up_count"] == 4
        assert overview.top_sectors_by_limit_up[0]["name"] == "半导体"
        assert overview.top_sectors_by_limit_up[0]["limit_up_count"] == 4
        assert overview.top_sectors_by_limit_down[0]["name"] == "煤炭"
        assert overview.top_sectors_by_limit_down[0]["limit_down_count"] == 2
