# -*- coding: utf-8 -*-
"""
===================================
大盘复盘历史数据访问层
===================================

职责：
1. 封装大盘复盘历史的数据库操作（sector_snapshot、market_daily_stats）
2. 提供板块热点趋势统计接口
"""

import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class MarketReviewRepository:
    """
    大盘复盘数据访问层

    封装 market_sector_snapshot / market_daily_stats 等表的数据库操作，
    提供与 demo-agent 兼容的接口（get_sector_hotspot_stats、get_prev_day_stats）。
    """

    def __init__(self):
        from src.storage import get_db

        self._db = get_db()

    def get_prev_day_stats(
        self,
        region: str = "cn",
        before_date: Optional[date] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        查询指定日期之前最近一个交易日的市场统计数据。

        Args:
            region: 市场区域（cn / us）
            before_date: 参考日期，默认今日

        Returns:
            Dict with keys: total_amount, up_count, down_count, flat_count,
            limit_up_count, limit_down_count, trade_date (str)
            找不到时返回 None
        """
        if before_date is None:
            before_date = datetime.now().date()
        try:
            prev = self._db.get_prev_market_daily_stats(region=region, before_date=before_date)
            if prev:
                return prev
        except Exception as e:
            logger.warning("[MarketReviewRepo] 查询前日统计失败（非致命）: %s", e)
        return None

    def get_sector_hotspot_stats(
        self,
        days: int = 5,
        region: str = "cn",
    ) -> Dict[str, Any]:
        """
        分析近 N 个交易日的板块热点趋势。

        从 market_sector_snapshot 表读取近期快照，统计各板块领涨/领跌天数。

        Args:
            days: 分析窗口（交易日数），建议 3~7
            region: 市场区域

        Returns:
            Dict with:
              - days_analyzed: int   实际找到的交易日数
              - dates: List[str]     覆盖日期（降序）
              - top_sectors: List[{name, days, details: [{date, change_pct}]}]
              - bottom_sectors: List[{name, days, details: [{date, change_pct}]}]
        """
        try:
            rows = self._db.get_recent_sector_snapshots(region=region, days=days)
            if not rows:
                return {"days_analyzed": 0, "dates": [], "top_sectors": [], "bottom_sectors": []}

            seen_dates: set = set()
            top_counts: Dict[str, int] = defaultdict(int)
            bottom_counts: Dict[str, int] = defaultdict(int)
            top_details: Dict[str, list] = defaultdict(list)
            bottom_details: Dict[str, list] = defaultdict(list)

            for r in rows:
                trade_date = r.get("trade_date") or r.get("date")
                date_key = trade_date.isoformat() if hasattr(trade_date, "isoformat") else str(trade_date)
                seen_dates.add(date_key)
                name = r.get("sector_name", "")
                rank_type = r.get("rank_type", "")
                change_pct = r.get("change_pct", 0.0)
                if rank_type == "top":
                    top_counts[name] += 1
                    top_details[name].append({"date": date_key, "change_pct": change_pct})
                else:
                    bottom_counts[name] += 1
                    bottom_details[name].append({"date": date_key, "change_pct": change_pct})

            top_sorted = sorted(top_counts.items(), key=lambda x: -x[1])
            bottom_sorted = sorted(bottom_counts.items(), key=lambda x: -x[1])

            return {
                "days_analyzed": len(seen_dates),
                "dates": sorted(seen_dates, reverse=True),
                "top_sectors": [{"name": n, "days": cnt, "details": top_details[n]} for n, cnt in top_sorted],
                "bottom_sectors": [{"name": n, "days": cnt, "details": bottom_details[n]} for n, cnt in bottom_sorted],
            }
        except Exception as e:
            logger.warning("[MarketReviewRepo] 获取热点趋势统计失败（非致命）: %s", e)
            return {"days_analyzed": 0, "dates": [], "top_sectors": [], "bottom_sectors": []}
