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
import json
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class MarketReviewRepository:
    """
    大盘复盘数据访问层

    封装 market_sector_snapshot / market_daily_stats 等表的数据库操作，
    提供与 demo-agent 兼容的接口（get_sector_hotspot_stats、get_prev_day_stats）。
    """

    def __init__(self, db_manager=None):
        from src.storage import get_db

        self._db = db_manager or get_db()

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
        return json.loads(MarketReviewRepository._safe_json_dumps(overview))

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

    @staticmethod
    def _safe_json_dumps(payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            return json.dumps(str(payload), ensure_ascii=False)

    def replace_daily_reviews(self, trade_date: date, records: List[Dict[str, Any]]) -> int:
        payloads = []
        for item in records:
            payloads.append(
                {
                    "region": item["region"],
                    "report_markdown": item["report_markdown"],
                    "overview_json": self._safe_json_dumps(self._serialize_overview(item.get("overview"))),
                    "news_json": self._safe_json_dumps(
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
