import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

from data_provider.akshare_fetcher import AkshareFetcher


class TestAkshareSectorLimitStats(unittest.TestCase):
    def test_get_sector_limit_stats_uses_dtgc_alias_when_stock_dt_pool_em_missing(self):
        fetcher = AkshareFetcher()

        fake_ak = types.SimpleNamespace(
            stock_zt_pool_em=lambda date: pd.DataFrame({"所属行业": ["半导体", "半导体", "证券"]}),
            stock_zt_pool_dtgc_em=lambda date: pd.DataFrame({"所属行业": ["煤炭", "煤炭", "半导体"]}),
            stock_board_industry_name_em=lambda: pd.DataFrame(
                {
                    "板块名称": ["半导体", "证券", "煤炭"],
                    "涨跌幅": [3.2, 1.8, -1.5],
                    "上涨家数": [38, 24, 5],
                    "下跌家数": [2, 6, 18],
                }
            ),
        )

        with (
            patch.object(fetcher, "_set_random_user_agent", lambda: None),
            patch.object(fetcher, "_enforce_rate_limit", lambda: None),
            patch.dict(sys.modules, {"akshare": fake_ak}),
        ):
            result = fetcher.get_sector_limit_stats(trade_date="20260329")

        self.assertIsNotNone(result)
        by_name = {item["name"]: item for item in result}
        self.assertEqual(by_name["半导体"]["limit_up_count"], 2)
        self.assertEqual(by_name["半导体"]["limit_down_count"], 1)
        self.assertEqual(by_name["煤炭"]["limit_down_count"], 2)
        self.assertEqual(by_name["证券"]["limit_up_count"], 1)
