# -*- coding: utf-8 -*-
"""
===================================
大盘复盘分析模块
===================================

职责：
1. 获取大盘指数数据（上证、深证、创业板）
2. 搜索市场新闻形成复盘情报
3. 使用大模型生成每日大盘复盘报告
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd

from src.config import get_config
from src.search_service import SearchService
from src.core.market_profile import get_profile, MarketProfile
from src.core.market_strategy import get_market_strategy_blueprint
from data_provider.base import DataFetcherManager

logger = logging.getLogger(__name__)


@dataclass
class MarketIndex:
    """大盘指数数据"""

    code: str  # 指数代码
    name: str  # 指数名称
    current: float = 0.0  # 当前点位
    change: float = 0.0  # 涨跌点数
    change_pct: float = 0.0  # 涨跌幅(%)
    open: float = 0.0  # 开盘点位
    high: float = 0.0  # 最高点位
    low: float = 0.0  # 最低点位
    prev_close: float = 0.0  # 昨收点位
    volume: float = 0.0  # 成交量（手）
    amount: float = 0.0  # 成交额（元）
    amplitude: float = 0.0  # 振幅(%)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "current": self.current,
            "change": self.change,
            "change_pct": self.change_pct,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "volume": self.volume,
            "amount": self.amount,
            "amplitude": self.amplitude,
        }


@dataclass
class MarketOverview:
    """市场概览数据"""

    date: str  # 日期
    indices: List[MarketIndex] = field(default_factory=list)  # 主要指数
    up_count: int = 0  # 上涨家数
    down_count: int = 0  # 下跌家数
    flat_count: int = 0  # 平盘家数
    limit_up_count: int = 0  # 涨停家数（含ST）
    limit_down_count: int = 0  # 跌停家数（含ST）
    non_st_limit_up_count: int = 0  # 非ST涨停家数
    non_st_limit_down_count: int = 0  # 非ST跌停家数
    total_amount: float = 0.0  # 两市成交额（亿元）
    prev_total_amount: float = 0.0  # 前一交易日成交额（亿元），0 表示无历史数据
    # north_flow: float = 0.0           # 北向资金净流入（亿元）- 已废弃，接口不可用

    # 板块涨幅榜
    top_sectors: List[Dict] = field(default_factory=list)  # 行业涨幅前5板块
    bottom_sectors: List[Dict] = field(default_factory=list)  # 行业跌幅前5板块
    # 概念板块涨跌榜
    top_concept_sectors: List[Dict] = field(default_factory=list)  # 概念涨幅前10板块
    bottom_concept_sectors: List[Dict] = field(default_factory=list)  # 概念跌幅前10板块
    # 近 N 日领涨/领跌统计（由 MarketAnalyzer 计算填充）
    sector_trend: List[Dict] = field(default_factory=list)
    # 按涨停/跌停家数排名的板块榜（前10，仅 A 股）
    sector_up_limit_ranking: List[Dict] = field(default_factory=list)  # 涨停数量 Top10
    sector_down_limit_ranking: List[Dict] = field(default_factory=list)  # 跌停数量 Top10


class MarketAnalyzer:
    """
    大盘复盘分析器

    功能：
    1. 获取大盘指数实时行情
    2. 获取市场涨跌统计
    3. 获取板块涨跌榜
    4. 搜索市场新闻
    5. 生成大盘复盘报告
    """

    def __init__(
        self,
        search_service: Optional[SearchService] = None,
        analyzer=None,
        region: str = "cn",
    ):
        """
        初始化大盘分析器

        Args:
            search_service: 搜索服务实例
            analyzer: AI分析器实例（用于调用LLM）
            region: 市场区域 cn=A股 us=美股
        """
        self.config = get_config()
        self.search_service = search_service
        self.analyzer = analyzer
        self.data_manager = DataFetcherManager()
        self.region = region if region in ("cn", "us", "hk") else "cn"
        self.profile: MarketProfile = get_profile(self.region)
        self.strategy = get_market_strategy_blueprint(self.region)

    def get_market_overview(self) -> MarketOverview:
        """
        获取市场概览数据

        Returns:
            MarketOverview: 市场概览数据对象
        """
        today = datetime.now().strftime("%Y-%m-%d")
        overview = MarketOverview(date=today)

        # 1. 获取主要指数行情（按 region 切换 A 股/美股）
        overview.indices = self._get_main_indices()

        # 2. 获取涨跌统计（A 股有，美股无等效数据）
        if self.profile.has_market_stats:
            self._get_market_statistics(overview)

        # 3. 获取板块涨跌榜（A 股有，美股暂无）
        if self.profile.has_sector_rankings:
            self._get_sector_rankings(overview)

        # 4. 获取概念板块涨跌榜（A 股独有）
        if self.profile.has_sector_rankings:
            self._get_concept_sector_rankings(overview)

        # 5. 获取板块涨停/跌停家数排行（A 股独有）
        if self.profile.has_sector_rankings:
            self._get_sector_limit_rankings(overview)

        # 5. 获取北向资金（可选）
        # self._get_north_flow(overview)

        return overview

    def _get_main_indices(self) -> List[MarketIndex]:
        """获取主要指数实时行情"""
        indices = []

        try:
            logger.info("[大盘] 获取主要指数实时行情...")

            # 使用 DataFetcherManager 获取指数行情（按 region 切换）
            data_list = self.data_manager.get_main_indices(region=self.region)

            if data_list:
                for item in data_list:
                    index = MarketIndex(
                        code=item["code"],
                        name=item["name"],
                        current=item["current"],
                        change=item["change"],
                        change_pct=item["change_pct"],
                        open=item["open"],
                        high=item["high"],
                        low=item["low"],
                        prev_close=item["prev_close"],
                        volume=item["volume"],
                        amount=item["amount"],
                        amplitude=item["amplitude"],
                    )
                    indices.append(index)

            # A 股复盘额外补充港股恒生指数、恒生科技指数供参考
            if self.region == "cn":
                hk_ref = self._get_hk_reference_indices()
                indices.extend(hk_ref)

            if not indices:
                logger.warning("[大盘] 所有行情数据源失败，将依赖新闻搜索进行分析")
            else:
                logger.info(f"[大盘] 获取到 {len(indices)} 个指数行情")

        except Exception as e:
            logger.error(f"[大盘] 获取指数行情失败: {e}")

        return indices

    def _get_hk_reference_indices(self) -> List["MarketIndex"]:
        """获取港股参考指数（恒生指数、恒生科技指数）供 A 股复盘参考。"""
        _HK_INCLUDE = frozenset({"HSI", "HSTECH"})
        try:
            hk_data = self.data_manager.get_main_indices(region="hk")
            if not hk_data:
                return []
            result = []
            for item in hk_data:
                if item.get("code") not in _HK_INCLUDE:
                    continue
                result.append(
                    MarketIndex(
                        code=item["code"],
                        name=item["name"],
                        current=item["current"],
                        change=item["change"],
                        change_pct=item["change_pct"],
                        open=item.get("open", 0.0),
                        high=item.get("high", 0.0),
                        low=item.get("low", 0.0),
                        prev_close=item.get("prev_close", 0.0),
                        volume=item.get("volume", 0.0),
                        amount=item.get("amount", 0.0),
                        amplitude=item.get("amplitude", 0.0),
                    )
                )
            if result:
                logger.info("[大盘] 已补充港股参考指数: %s", [i.name for i in result])
            return result
        except Exception as e:
            logger.warning("[大盘] 获取港股参考指数失败，跳过: %s", e)
            return []

    def _get_market_statistics(self, overview: MarketOverview):
        """获取市场涨跌统计"""
        try:
            logger.info("[大盘] 获取市场涨跌统计...")

            stats = self.data_manager.get_market_stats()

            if stats:
                overview.up_count = stats.get("up_count", 0)
                overview.down_count = stats.get("down_count", 0)
                overview.flat_count = stats.get("flat_count", 0)
                overview.limit_up_count = stats.get("limit_up_count", 0)
                overview.limit_down_count = stats.get("limit_down_count", 0)
                overview.non_st_limit_up_count = stats.get("non_st_limit_up_count", 0)
                overview.non_st_limit_down_count = stats.get("non_st_limit_down_count", 0)
                overview.total_amount = stats.get("total_amount", 0.0)

                logger.info(
                    f"[大盘] 涨:{overview.up_count} 跌:{overview.down_count} 平:{overview.flat_count} "
                    f"涨停:{overview.limit_up_count}(非ST:{overview.non_st_limit_up_count}) "
                    f"跌停:{overview.limit_down_count}(非ST:{overview.non_st_limit_down_count}) "
                    f"成交额:{overview.total_amount:.0f}亿"
                )

                # 持久化当日统计，并读取前一交易日数据用于成交额对比
                self._save_and_load_market_daily_stats(overview)

        except Exception as e:
            logger.error(f"[大盘] 获取涨跌统计失败: {e}")

    def _save_and_load_market_daily_stats(self, overview: MarketOverview) -> None:
        """保存当日市场统计到 DB，并将前一交易日成交额填入 overview.prev_total_amount。"""
        try:
            from datetime import date as _date
            from src.storage import get_db

            db = get_db()
            today = _date.today()
            db.save_market_daily_stats(
                trade_date=today,
                region=self.region,
                total_amount=overview.total_amount,
                up_count=overview.up_count,
                down_count=overview.down_count,
                flat_count=overview.flat_count,
                limit_up_count=overview.limit_up_count,
                limit_down_count=overview.limit_down_count,
                non_st_limit_up_count=overview.non_st_limit_up_count,
                non_st_limit_down_count=overview.non_st_limit_down_count,
            )
            prev = db.get_prev_market_daily_stats(region=self.region, before_date=today)
            if prev:
                overview.prev_total_amount = prev["total_amount"]
                logger.info(
                    "[大盘] 前一交易日(%s)成交额: %.0f亿，今日: %.0f亿",
                    prev["trade_date"],
                    prev["total_amount"],
                    overview.total_amount,
                )
        except Exception as exc:
            logger.warning("[大盘] 市场统计历史对比失败: %s", exc)

    def _get_sector_rankings(self, overview: MarketOverview):
        """获取板块涨跌榜"""
        try:
            logger.info("[大盘] 获取板块涨跌榜...")

            top_sectors, bottom_sectors = self.data_manager.get_sector_rankings(5)

            if top_sectors or bottom_sectors:
                overview.top_sectors = top_sectors
                overview.bottom_sectors = bottom_sectors

                logger.info(f"[大盘] 领涨板块: {[s['name'] for s in overview.top_sectors]}")
                logger.info(f"[大盘] 领跌板块: {[s['name'] for s in overview.bottom_sectors]}")

                # 保存当日快照到 DB，并计算近 N 日领涨/领跌统计
                self._save_and_calc_sector_trend(overview)

        except Exception as e:
            logger.error(f"[大盘] 获取板块涨跌榜失败: {e}")

    # def _get_north_flow(self, overview: MarketOverview):
    #     """获取北向资金流入"""
    #     ...

    # 统计性虚拟板块：这些并非真实投资主题，需从概念涨跌榜中过滤掉
    _CONCEPT_EXCLUDE = frozenset(
        {
            "昨日连板",
            "昨日连板_含一字",
            "东方财富热股",
            "昨日首板",
            "昨日涨停",
            "昨日涨停_含一字",
            "昨日触板",
            "昨日炸板",
            "昨日高换手",
            "昨日高振幅",
        }
    )

    def _get_concept_sector_rankings(self, overview: MarketOverview) -> None:
        """获取概念板块涨跌榜（A 股独有）"""
        try:
            logger.info("[大盘] 获取概念板块涨跌榜...")
            top_concept, bottom_concept = self.data_manager.get_concept_sector_rankings(10)
            if top_concept or bottom_concept:
                # 过滤掉统计性虚拟板块（昨日连板、东方财富热股、昨日首板等）
                top_concept = [s for s in top_concept if s.get("name") not in self._CONCEPT_EXCLUDE]
                bottom_concept = [s for s in bottom_concept if s.get("name") not in self._CONCEPT_EXCLUDE]
                overview.top_concept_sectors = top_concept
                overview.bottom_concept_sectors = bottom_concept
                logger.info("[大盘] 领涨概念: %s", [s["name"] for s in overview.top_concept_sectors[:5]])
                logger.info("[大盘] 领跌概念: %s", [s["name"] for s in overview.bottom_concept_sectors[:5]])
        except Exception as e:
            logger.error("[大盘] 获取概念板块涨跌榜失败: %s", e)

    def _get_sector_limit_rankings(self, overview: MarketOverview) -> None:
        """获取板块涨停/跌停家数排行，并保存到数据库。"""
        try:
            logger.info("[大盘] 获取板块涨停/跌停家数排行...")
            from datetime import date as _date
            from src.storage import get_db

            today_str = _date.today().strftime("%Y%m%d")
            all_sectors = self.data_manager.get_sector_limit_stats(trade_date=today_str)
            if not all_sectors:
                logger.info("[大盘] 板块涨跌停统计暂无数据（盘中或非交易日），跳过")
                return

            # 按涨停数量 Top10
            top_up = sorted(all_sectors, key=lambda x: -x.get("limit_up_count", 0))[:10]
            top_down = sorted(all_sectors, key=lambda x: -x.get("limit_down_count", 0))[:10]
            # 过滤掉涨停/跌停数为 0 的
            overview.sector_up_limit_ranking = [s for s in top_up if s.get("limit_up_count", 0) > 0]
            overview.sector_down_limit_ranking = [s for s in top_down if s.get("limit_down_count", 0) > 0]

            if overview.sector_up_limit_ranking:
                logger.info(
                    "[大盘] 涨停板块 Top%d: %s",
                    len(overview.sector_up_limit_ranking),
                    [f"{s['name']}({s['limit_up_count']})" for s in overview.sector_up_limit_ranking[:5]],
                )
            if overview.sector_down_limit_ranking:
                logger.info(
                    "[大盘] 跌停板块 Top%d: %s",
                    len(overview.sector_down_limit_ranking),
                    [f"{s['name']}({s['limit_down_count']})" for s in overview.sector_down_limit_ranking[:5]],
                )

            # 持久化到数据库
            try:
                db = get_db()
                db.save_sector_limit_stats(
                    trade_date=_date.today(),
                    region=self.region,
                    all_sectors=all_sectors,
                )
            except Exception as db_exc:
                logger.warning("[大盘] 板块涨跌停统计存库失败: %s", db_exc)

        except Exception as e:
            logger.error("[大盘] 获取板块涨停/跌停家数排行失败: %s", e)

    def _save_and_calc_sector_trend(self, overview: MarketOverview, days: int = 5) -> None:
        """保存当日板块快照，并将近 N 日领涨/领跌统计写入 overview.sector_trend。"""
        try:
            from datetime import date as _date
            from src.storage import get_db

            db = get_db()
            today = _date.today()
            db.save_sector_snapshot(
                trade_date=today,
                region=self.region,
                top_sectors=overview.top_sectors,
                bottom_sectors=overview.bottom_sectors,
            )
            rows = db.get_recent_sector_snapshots(region=self.region, days=days)
            overview.sector_trend = self._aggregate_sector_trend(rows, days)
        except Exception as exc:
            logger.warning("[大盘] 板块趋势计算失败: %s", exc)

    @staticmethod
    def _aggregate_sector_trend(rows: List[Dict], days: int) -> List[Dict]:
        """
        将原始快照行汇总为板块领涨/领跌天数统计。

        Returns:
            List[Dict]，每项：
              name, top_days(领涨天数), bottom_days(领跌天数),
              top_avg_pct(领涨均幅), bottom_avg_pct(领跌均幅)
        按 top_days desc 排序。
        """
        from collections import defaultdict

        summary: Dict[str, Dict] = defaultdict(
            lambda: {
                "top_days": 0,
                "bottom_days": 0,
                "top_pct_sum": 0.0,
                "bottom_pct_sum": 0.0,
            }
        )
        for r in rows:
            name = r["sector_name"]
            if r["rank_type"] == "top":
                summary[name]["top_days"] += 1
                summary[name]["top_pct_sum"] += r["change_pct"]
            else:
                summary[name]["bottom_days"] += 1
                summary[name]["bottom_pct_sum"] += r["change_pct"]

        result = []
        for name, d in summary.items():
            result.append(
                {
                    "name": name,
                    "top_days": d["top_days"],
                    "bottom_days": d["bottom_days"],
                    "top_avg_pct": (d["top_pct_sum"] / d["top_days"] if d["top_days"] else 0.0),
                    "bottom_avg_pct": (d["bottom_pct_sum"] / d["bottom_days"] if d["bottom_days"] else 0.0),
                    "days_window": days,
                }
            )
        result.sort(key=lambda x: (-x["top_days"], -x["top_avg_pct"]))
        return result

    def search_market_news(self) -> List[Dict]:
        """
        搜索市场新闻

        Returns:
            新闻列表
        """
        if not self.search_service:
            logger.warning("[大盘] 搜索服务未配置，跳过新闻搜索")
            return []

        all_news = []

        # 按 region 使用不同的新闻搜索词
        search_queries = self.profile.news_queries

        try:
            logger.info("[大盘] 开始搜索市场新闻...")

            # 根据 region 设置搜索上下文名称，避免美股搜索被解读为 A 股语境
            market_name = "大盘" if self.region == "cn" else "US market"
            for query in search_queries:
                response = self.search_service.search_stock_news(
                    stock_code="market", stock_name=market_name, max_results=3, focus_keywords=query.split()
                )
                if response and response.results:
                    all_news.extend(response.results)
                    logger.info(f"[大盘] 搜索 '{query}' 获取 {len(response.results)} 条结果")

            logger.info(f"[大盘] 共获取 {len(all_news)} 条市场新闻")

        except Exception as e:
            logger.error(f"[大盘] 搜索市场新闻失败: {e}")

        return all_news

    def generate_market_review(self, overview: MarketOverview, news: List) -> str:
        """
        使用大模型生成大盘复盘报告

        Args:
            overview: 市场概览数据
            news: 市场新闻列表 (SearchResult 对象列表)

        Returns:
            大盘复盘报告文本
        """
        if not self.analyzer or not self.analyzer.is_available():
            logger.warning("[大盘] AI分析器未配置或不可用，使用模板生成报告")
            return self._generate_template_review(overview, news)

        # 构建 Prompt
        prompt = self._build_review_prompt(overview, news)

        logger.info("[大盘] 调用大模型生成复盘报告...")
        # Use the public generate_text() entry point — never access private analyzer attributes.
        review = self.analyzer.generate_text(prompt, max_tokens=2048, temperature=0.7)

        if review:
            logger.info("[大盘] 复盘报告生成成功，长度: %d 字符", len(review))
            # Inject structured data tables into LLM prose sections
            return self._inject_data_into_review(review, overview)
        else:
            logger.warning("[大盘] 大模型返回为空，使用模板报告")
            return self._generate_template_review(overview, news)

    def _inject_data_into_review(self, review: str, overview: MarketOverview) -> str:
        """Inject structured data tables into the corresponding LLM prose sections."""
        import re

        # Build data blocks
        stats_block = self._build_stats_block(overview)
        indices_block = self._build_indices_block(overview)
        sector_block = self._build_sector_block(overview)

        # Inject market stats after "### 一、市场总结" section (before next ###)
        if stats_block:
            review = self._insert_after_section(review, r"###\s*一、市场总结", stats_block)

        # Inject indices table after "### 二、指数点评" section
        if indices_block:
            review = self._insert_after_section(review, r"###\s*二、指数点评", indices_block)

        # Inject sector rankings after "### 四、热点解读" section
        if sector_block:
            review = self._insert_after_section(review, r"###\s*四、热点解读", sector_block)

        return review

    @staticmethod
    def _insert_after_section(text: str, heading_pattern: str, block: str) -> str:
        """Insert a data block at the end of a markdown section (before the next ### heading)."""
        import re

        # Find the heading
        match = re.search(heading_pattern, text)
        if not match:
            return text
        start = match.end()
        # Find the next ### heading after this one
        next_heading = re.search(r"\n###\s", text[start:])
        if next_heading:
            insert_pos = start + next_heading.start()
        else:
            # No next heading — append at end
            insert_pos = len(text)
        # Insert the block before the next heading, with spacing
        return text[:insert_pos].rstrip() + "\n\n" + block + "\n\n" + text[insert_pos:].lstrip("\n")

    def _build_stats_block(self, overview: MarketOverview) -> str:
        """Build market statistics block."""
        has_stats = overview.up_count or overview.down_count or overview.total_amount
        if not has_stats:
            return ""

        # 成交额对比
        if overview.prev_total_amount > 0 and overview.total_amount > 0:
            diff_pct = (overview.total_amount - overview.prev_total_amount) / overview.prev_total_amount * 100
            if diff_pct >= 10:
                vol_tag = f"🔺 较前日**+{diff_pct:.1f}%** 放量"
            elif diff_pct >= 3:
                vol_tag = f"🔼 较前日**+{diff_pct:.1f}%** 温和放量"
            elif diff_pct > -3:
                vol_tag = f"➡️ 较前日**{diff_pct:+.1f}%** 基本持平"
            elif diff_pct > -10:
                vol_tag = f"🔽 较前日**{diff_pct:.1f}%** 温和缩量"
            else:
                vol_tag = f"🔻 较前日**{diff_pct:.1f}%** 缩量"
            amount_str = (
                f"成交额 **{overview.total_amount:.0f}** 亿（昨 {overview.prev_total_amount:.0f} 亿，{vol_tag}）"
            )
        else:
            amount_str = f"成交额 **{overview.total_amount:.0f}** 亿"

        # 涨多跌少判断
        total_stocks = overview.up_count + overview.down_count + overview.flat_count
        if total_stocks > 0:
            up_ratio = overview.up_count / total_stocks
            if overview.up_count > overview.down_count * 1.5:
                breadth_tag = "📈 涨多跌少"
            elif overview.down_count > overview.up_count * 1.5:
                breadth_tag = "📉 跌多涨少"
            else:
                breadth_tag = "↔️ 涨跌均衡"
        else:
            breadth_tag = ""

        lines = [
            f"> {breadth_tag}  上涨 **{overview.up_count}** 家 / 下跌 **{overview.down_count}** 家 / "
            f"平盘 **{overview.flat_count}** 家 | "
            f"涨停 **{overview.limit_up_count}**（非ST **{overview.non_st_limit_up_count}**）/ "
            f"跌停 **{overview.limit_down_count}**（非ST **{overview.non_st_limit_down_count}**）| "
            f"{amount_str}"
        ]
        return "\n".join(lines)

    def _build_indices_block(self, overview: MarketOverview) -> str:
        """构建指数行情表格（不含振幅）"""
        if not overview.indices:
            return ""
        lines = ["| 指数 | 最新 | 涨跌幅 | 成交额(亿) |", "|------|------|--------|-----------|"]
        for idx in overview.indices:
            arrow = "🔴" if idx.change_pct < 0 else "🟢" if idx.change_pct > 0 else "⚪"
            amount_raw = idx.amount or 0.0
            if amount_raw == 0.0:
                # Yahoo Finance 不提供成交额，显示 N/A 避免误解
                amount_str = "N/A"
            elif amount_raw > 1e6:
                amount_str = f"{amount_raw / 1e8:.0f}"
            else:
                amount_str = f"{amount_raw:.0f}"
            lines.append(f"| {idx.name} | {idx.current:.2f} | {arrow} {idx.change_pct:+.2f}% | {amount_str} |")
        return "\n".join(lines)

    def _build_sector_block(self, overview: MarketOverview) -> str:
        """Build sector ranking block, including limit stats and multi-day trend statistics."""
        has_data = (
            overview.top_sectors
            or overview.bottom_sectors
            or overview.top_concept_sectors
            or overview.bottom_concept_sectors
            or overview.sector_up_limit_ranking
            or overview.sector_down_limit_ranking
        )
        if not has_data:
            return ""
        lines = []

        # 概念板块（近1日热点追踪）
        if overview.top_concept_sectors or overview.bottom_concept_sectors:
            lines.append("**近1日热点追踪**")
        if overview.top_concept_sectors:
            top_c = " | ".join([f"**{s['name']}**({s['change_pct']:+.2f}%)" for s in overview.top_concept_sectors[:10]])
            lines.append(f"> 🚀 概念领涨: {top_c}")
        if overview.bottom_concept_sectors:
            bot_c = " | ".join(
                [f"**{s['name']}**({s['change_pct']:+.2f}%)" for s in overview.bottom_concept_sectors[:10]]
            )
            lines.append(f"> 🔻 概念领跌: {bot_c}")

        # 涨停/跌停数量榜
        limit_block = self._build_sector_limit_block(overview)
        if limit_block:
            lines.append("")
            lines.append(limit_block)

        # 近 N 日领涨/领跌天数统计
        trend_block = self._build_sector_trend_block(overview)
        if trend_block:
            lines.append("")
            lines.append(trend_block)

        return "\n".join(lines)

    @staticmethod
    def _build_sector_limit_block(overview: MarketOverview) -> str:
        """渲染板块涨停/跌停家数排行表。"""
        if not overview.sector_up_limit_ranking and not overview.sector_down_limit_ranking:
            return ""
        lines = ["**今日板块涨停/跌停家数榜**"]
        if overview.sector_up_limit_ranking:
            lines.append("")
            lines.append("| 板块 | 涨停家数 | 板块涨跌幅 |")
            lines.append("|------|---------|----------|")
            for s in overview.sector_up_limit_ranking:
                pct_str = f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "N/A"
                lines.append(f"| {s['name']} | **{s['limit_up_count']}** | {pct_str} |")
        if overview.sector_down_limit_ranking:
            lines.append("")
            lines.append("| 板块 | 跌停家数 | 板块涨跌幅 |")
            lines.append("|------|---------|----------|")
            for s in overview.sector_down_limit_ranking:
                pct_str = f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "N/A"
                lines.append(f"| {s['name']} | **{s['limit_down_count']}** | {pct_str} |")
        return "\n".join(lines)

    @staticmethod
    def _build_sector_trend_block(overview: MarketOverview) -> str:
        """渲染近 N 日领涨/领跌板块统计表。"""
        if not overview.sector_trend:
            return ""
        days = overview.sector_trend[0].get("days_window", 5) if overview.sector_trend else 5

        # 领涨榜 top 5
        top_trend = [r for r in overview.sector_trend if r["top_days"] > 0]
        top_trend.sort(key=lambda x: (-x["top_days"], -x["top_avg_pct"]))

        # 领跌榜 top 5（按领跌天数降序）
        bot_trend = [r for r in overview.sector_trend if r["bottom_days"] > 0]
        bot_trend.sort(key=lambda x: (-x["bottom_days"], x["bottom_avg_pct"]))

        if not top_trend and not bot_trend:
            return ""

        lines = [f"**近 {days} 日板块领涨/领跌统计**"]
        if top_trend:
            lines.append("")
            lines.append(f"| 板块 | 近{days}日领涨天数 | 平均涨幅 |")
            lines.append("|------|-------------|---------|")
            for r in top_trend[:5]:
                lines.append(f"| {r['name']} | {r['top_days']} 天 | {r['top_avg_pct']:+.2f}% |")
        if bot_trend:
            lines.append("")
            lines.append(f"| 板块 | 近{days}日领跌天数 | 平均跌幅 |")
            lines.append("|------|-------------|---------|")
            for r in bot_trend[:5]:
                lines.append(f"| {r['name']} | {r['bottom_days']} 天 | {r['bottom_avg_pct']:+.2f}% |")
        return "\n".join(lines)

    @staticmethod
    @staticmethod
    def _build_limit_text_for_prompt(overview: MarketOverview) -> str:
        """将板块涨停/跌停家数排行汇总成 Prompt 可用的简洁纯文本。"""
        lines = []
        if overview.sector_up_limit_ranking:
            parts = [f"{s['name']}({s['limit_up_count']}家涨停)" for s in overview.sector_up_limit_ranking[:10]]
            lines.append("## 板块涨停家数排行（Top10）")
            lines.append(" | ".join(parts))
        if overview.sector_down_limit_ranking:
            parts = [f"{s['name']}({s['limit_down_count']}家跌停)" for s in overview.sector_down_limit_ranking[:10]]
            lines.append("## 板块跌停家数排行")
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    def _build_trend_text_for_prompt(overview: MarketOverview) -> str:
        """将 sector_trend 汇总成 Prompt 可用的简洁纯文本。"""
        if not overview.sector_trend:
            return ""
        days = overview.sector_trend[0].get("days_window", 5)

        top_trend = [r for r in overview.sector_trend if r["top_days"] > 0]
        top_trend.sort(key=lambda x: (-x["top_days"], -x["top_avg_pct"]))

        bot_trend = [r for r in overview.sector_trend if r["bottom_days"] > 0]
        bot_trend.sort(key=lambda x: (-x["bottom_days"], x["bottom_avg_pct"]))

        if not top_trend and not bot_trend:
            return ""

        lines = [f"## 近 {days} 日板块领涨/领跌统计"]
        if top_trend:
            parts = [f"{r['name']}(领涨{r['top_days']}天,均涨{r['top_avg_pct']:+.2f}%)" for r in top_trend[:5]]
            lines.append("近期领涨主线: " + " | ".join(parts))
        if bot_trend:
            parts = [f"{r['name']}(领跌{r['bottom_days']}天,均跌{r['bottom_avg_pct']:+.2f}%)" for r in bot_trend[:5]]
            lines.append("近期持续领跌: " + " | ".join(parts))
        return "\n".join(lines)

    def _build_concept_text_for_prompt(self, overview: MarketOverview) -> str:
        """将概念板块涨跌榜汇总成 Prompt 可用的简洁纯文本。"""
        if not overview.top_concept_sectors and not overview.bottom_concept_sectors:
            return ""
        lines = ["## 概念板块涨跌榜"]
        if overview.top_concept_sectors:
            parts = [f"{s['name']}({s['change_pct']:+.2f}%)" for s in overview.top_concept_sectors[:10]]
            lines.append("领涨概念(Top10): " + " | ".join(parts))
        if overview.bottom_concept_sectors:
            parts = [f"{s['name']}({s['change_pct']:+.2f}%)" for s in overview.bottom_concept_sectors[:10]]
            lines.append("领跌概念(Top10): " + " | ".join(parts))
        return "\n".join(lines)

    def _build_review_prompt(self, overview: MarketOverview, news: List) -> str:
        """构建复盘报告 Prompt"""
        # 指数行情信息（简洁格式，不用emoji）
        indices_text = ""
        for idx in overview.indices:
            direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
            indices_text += f"- {idx.name}: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n"

        # 板块信息
        top_sectors_text = ", ".join([f"{s['name']}({s['change_pct']:+.2f}%)" for s in overview.top_sectors[:3]])
        bottom_sectors_text = ", ".join([f"{s['name']}({s['change_pct']:+.2f}%)" for s in overview.bottom_sectors[:3]])

        # 近 N 日领涨/领跌板块趋势文本
        trend_text = self._build_trend_text_for_prompt(overview)
        # 板块涨停/跌停家数排行文本
        limit_text = self._build_limit_text_for_prompt(overview)
        # 概念板块涨跌文本
        concept_text = self._build_concept_text_for_prompt(overview)

        # 新闻信息 - 支持 SearchResult 对象或字典
        news_text = ""
        for i, n in enumerate(news[:6], 1):
            # 兼容 SearchResult 对象和字典
            if hasattr(n, "title"):
                title = n.title[:50] if n.title else ""
                snippet = n.snippet[:100] if n.snippet else ""
            else:
                title = n.get("title", "")[:50]
                snippet = n.get("snippet", "")[:100]
            news_text += f"{i}. {title}\n   {snippet}\n"

        # 按 region 组装市场概况与板块区块（美股无涨跌家数、板块数据）
        stats_block = ""
        sector_block = ""
        if self.region == "us":
            if self.profile.has_market_stats:
                stats_block = f"""## Market Overview
- Up: {overview.up_count} | Down: {overview.down_count} | Flat: {overview.flat_count}
- Limit up: {overview.limit_up_count} | Limit down: {overview.limit_down_count}
- Total volume (CNY bn): {overview.total_amount:.0f}"""
            else:
                stats_block = "## Market Overview\n(US market has no equivalent advance/decline stats.)"

            if self.profile.has_sector_rankings:
                sector_block = f"""## Sector Performance
Leading: {top_sectors_text if top_sectors_text else "N/A"}
Lagging: {bottom_sectors_text if bottom_sectors_text else "N/A"}
{trend_text}"""
            else:
                sector_block = "## Sector Performance\n(US sector data not available.)"
        else:
            if self.profile.has_market_stats:
                # 成交额与前日对比
                if overview.prev_total_amount > 0 and overview.total_amount > 0:
                    diff_pct = (overview.total_amount - overview.prev_total_amount) / overview.prev_total_amount * 100
                    amount_desc = (
                        f"{overview.total_amount:.0f} 亿元"
                        f"（前一日 {overview.prev_total_amount:.0f} 亿，较前日 {diff_pct:+.1f}%，"
                        f"{'放量' if diff_pct >= 5 else '缩量' if diff_pct <= -5 else '基本持平'}）"
                    )
                else:
                    amount_desc = f"{overview.total_amount:.0f} 亿元"

                # 涨跌家数多寡
                total_stocks = overview.up_count + overview.down_count + overview.flat_count
                if total_stocks > 0:
                    breadth_desc = (
                        f"上涨 {overview.up_count} 家，下跌 {overview.down_count} 家，平盘 {overview.flat_count} 家"
                        f"（{'涨多跌少' if overview.up_count > overview.down_count else '跌多涨少' if overview.down_count > overview.up_count else '涨跌均衡'}）"
                    )
                else:
                    breadth_desc = f"上涨 {overview.up_count} 家，下跌 {overview.down_count} 家"

                stats_block = f"""## 市场概况
- {breadth_desc}
- 涨停: {overview.limit_up_count} 家（其中非ST涨停: {overview.non_st_limit_up_count} 家）| 跌停: {overview.limit_down_count} 家（其中非ST跌停: {overview.non_st_limit_down_count} 家）
- 两市成交额: {amount_desc}"""
            else:
                if self.region == "hk":
                    stats_block = "## 市场概况\n（港股暂无涨跌家数等统计）"
                else:
                    stats_block = "## 市场概况\n（美股暂无涨跌家数等统计）"

            if self.profile.has_sector_rankings:
                sector_block = f"""## 行业板块表现
领涨: {top_sectors_text if top_sectors_text else "暂无数据"}
领跌: {bottom_sectors_text if bottom_sectors_text else "暂无数据"}
{limit_text}
{trend_text}

{concept_text}"""
            else:
                if self.region == "hk":
                    sector_block = "## 板块表现\n（港股暂无板块行业数据）"
                else:
                    sector_block = "## 板块表现\n（美股暂无板块涨跌数据）"

        data_no_indices_hint = (
            "注意：由于行情数据获取失败，请主要根据【市场新闻】进行定性分析和总结，不要编造具体的指数点位。"
            if not indices_text
            else ""
        )
        indices_placeholder = (
            indices_text
            if indices_text
            else ("No index data (API error)" if self.region == "us" else "暂无指数数据（接口异常）")
        )
        news_placeholder = news_text if news_text else ("No relevant news" if self.region == "us" else "暂无相关新闻")

        # 美股场景使用英文提示语，便于生成更符合美股语境的报告
        if self.region == "us":
            data_no_indices_hint_en = (
                "Note: Market data fetch failed. Rely mainly on [Market News] for qualitative analysis. Do not invent index levels."
                if not indices_text
                else ""
            )
            return f"""You are a professional US/A/H market analyst. Please produce a concise US market recap report based on the data below.

[Requirements]
- Output pure Markdown only
- No JSON
- No code blocks
- Use emoji sparingly in headings (at most one per heading)

---

# Today's Market Data

## Date
{overview.date}

## Major Indices
{indices_placeholder}

{stats_block}

{sector_block}

## Market News
{news_placeholder}

{data_no_indices_hint_en}

{self.strategy.to_prompt_block()}

---

# Output Template (follow this structure)

## {overview.date} US Market Recap

### 1. Market Summary
(2-3 sentences on overall market performance, index moves, volume)

### 2. Index Commentary
(Analyse S&P 500, Nasdaq, Dow and other major index moves.)

### 3. Fund Flows
(Interpret volume and flow implications)

### 4. Sector/Theme Highlights
(Analyze drivers behind leading/lagging sectors)

### 5. Outlook
(Short-term view based on price action and news)

### 6. Risk Alerts
(Key risks to watch)

### 7. Strategy Plan
(Provide risk-on/neutral/risk-off stance, position sizing guideline, and one invalidation trigger.)

---

Output the report content directly, no extra commentary.
"""

        # A 股 / 港股场景使用中文提示语（相同的七段式结构）
        market_label = "A股" if self.region == "cn" else "港股"
        if self.region == "cn":
            sentiment_hint = (
                f"全市场涨多跌少还是跌多涨少？"
                f"非ST涨停 {overview.non_st_limit_up_count} 家（含ST总计 {overview.limit_up_count} 家）/ "
                f"非ST跌停 {overview.non_st_limit_down_count} 家（含ST总计 {overview.limit_down_count} 家），"
                f"是否反映情绪过热或恐慌？"
            )
        else:
            sentiment_hint = "港股成交量是否放大？南北向资金净流向如何？"
        return f"""你是一位专业的A/H/美股市场分析师，请根据以下数据生成一份简洁的{market_label}大盘复盘报告。

【重要】输出要求：
- 必须输出纯 Markdown 文本格式
- 禁止输出 JSON 格式
- 禁止输出代码块
- emoji 仅在标题处少量使用（每个标题最多1个）

---

# 今日市场数据

## 日期
{overview.date}

## 主要指数
{indices_placeholder}

{stats_block}

{sector_block}

## 市场新闻
{news_placeholder}

{data_no_indices_hint}

{self.strategy.to_prompt_block()}

---

# 输出格式模板（请严格按此格式输出）

## {overview.date} {market_label}大盘复盘

### 一、市场总结
（2-3句话概括今日市场整体表现，包括指数涨跌、成交量变化）

**市场环境研判（必填）：**
根据以下维度作出明确结论：
1. 量能：今日成交额与前日对比，是放量、缩量还是持平？
2. 人气：{sentiment_hint}
3. 综合判断：当前市场环境 **适合积极做多 / 谨慎操作 / 观望为主**，并给出一句理由。

### 二、指数点评
（{self.profile.prompt_index_hint}）

### 三、资金动向
（解读成交额流向的含义）

### 四、热点解读
（分析当日领涨领跌**行业板块**背后的逻辑和驱动因素；重点梳理今日**概念板块**涨幅榜前列的主题逻辑（如 AI、低空经济、新能源等热门概念），识别资金集中流入的主线概念；结合近多日板块领涨/领跌统计，分析主线板块连续性与轮动方向）

### 五、后市展望
（结合当前走势和新闻，给出明日市场预判）

### 六、风险提示
（需要关注的风险点）

### 七、策略计划
（给出进攻/均衡/防守结论，对应仓位建议，并给出一个触发失效条件；最后补充“建议仅供参考，不构成投资建议”。）

---

请直接输出复盘报告内容，不要输出其他说明文字。
"""

    def _generate_template_review(self, overview: MarketOverview, news: List) -> str:
        """使用模板生成复盘报告（无大模型时的备选方案）"""
        mood_code = self.profile.mood_index_code
        # 根据 mood_index_code 查找对应指数
        # cn: mood_code="000001"，idx.code 可能为 "sh000001"（以 mood_code 结尾）
        # us: mood_code="SPX"，idx.code 直接为 "SPX"
        mood_index = next(
            (idx for idx in overview.indices if idx.code == mood_code or idx.code.endswith(mood_code)),
            None,
        )
        if mood_index:
            if mood_index.change_pct > 1:
                market_mood = "强势上涨"
            elif mood_index.change_pct > 0:
                market_mood = "小幅上涨"
            elif mood_index.change_pct > -1:
                market_mood = "小幅下跌"
            else:
                market_mood = "明显下跌"
        else:
            market_mood = "震荡整理"

        # 指数行情（简洁格式）
        indices_text = ""
        for idx in overview.indices[:4]:
            direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
            indices_text += f"- **{idx.name}**: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n"

        # 板块信息
        top_text = "、".join([s["name"] for s in overview.top_sectors[:3]])
        bottom_text = "、".join([s["name"] for s in overview.bottom_sectors[:3]])

        # 按 region 决定是否包含涨跌统计和板块（美股无）
        stats_section = ""
        if self.profile.has_market_stats:
            stats_section = f"""
### 三、涨跌统计
| 指标 | 数值 |
|------|------|
| 上涨家数 | {overview.up_count} |
| 下跌家数 | {overview.down_count} |
| 涨停（含ST） | {overview.limit_up_count} |
| 涨停（非ST） | {overview.non_st_limit_up_count} |
| 跌停（含ST） | {overview.limit_down_count} |
| 跌停（非ST） | {overview.non_st_limit_down_count} |
| 两市成交额 | {overview.total_amount:.0f}亿 |
"""
        sector_section = ""
        if self.profile.has_sector_rankings and (top_text or bottom_text):
            sector_section = f"""
### 四、板块表现
- **领涨(涨幅)**: {top_text}
- **领跌(跌幅)**: {bottom_text}
"""
        # 涨停/跌停板块榜（模板报告中也展示）
        limit_section = ""
        if overview.sector_up_limit_ranking or overview.sector_down_limit_ranking:
            limit_lines = ["\n### 热点解读 · 板块涨停/跌停家数榜"]
            if overview.sector_up_limit_ranking:
                limit_lines.append("| 板块 | 涨停家数 | 板块涨跌幅 |")
                limit_lines.append("|------|---------|----------|")
                for s in overview.sector_up_limit_ranking:
                    pct = f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "N/A"
                    limit_lines.append(f"| {s['name']} | {s['limit_up_count']} | {pct} |")
            if overview.sector_down_limit_ranking:
                limit_lines.append("")
                limit_lines.append("| 板块 | 跌停家数 | 板块涨跌幅 |")
                limit_lines.append("|------|---------|----------|")
                for s in overview.sector_down_limit_ranking:
                    pct = f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "N/A"
                    limit_lines.append(f"| {s['name']} | {s['limit_down_count']} | {pct} |")
            limit_section = "\n".join(limit_lines)
        market_label = "A股" if self.region == "cn" else ("港股" if self.region == "hk" else "美股")
        strategy_summary = self.strategy.to_markdown_block()
        report = f"""## {overview.date} 大盘复盘

### 一、市场总结
今日{market_label}市场整体呈现**{market_mood}**态势。

### 二、主要指数
{indices_text}
{stats_section}
{sector_section}
{limit_section}
### 五、风险提示
市场有风险，投资需谨慎。以上数据仅供参考，不构成投资建议。

{strategy_summary}

---
*复盘时间: {datetime.now().strftime('%H:%M')}*
"""
        return report

    def run_daily_review(self) -> str:
        """
        执行每日大盘复盘流程

        Returns:
            复盘报告文本
        """
        logger.info("========== 开始大盘复盘分析 ==========")

        # 1. 获取市场概览
        overview = self.get_market_overview()

        # 2. 搜索市场新闻
        news = self.search_market_news()

        # 3. 生成复盘报告
        report = self.generate_market_review(overview, news)

        logger.info("========== 大盘复盘分析完成 ==========")

        return report


# 测试入口
if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    )

    analyzer = MarketAnalyzer()

    # 测试获取市场概览
    overview = analyzer.get_market_overview()
    print(f"\n=== 市场概览 ===")
    print(f"日期: {overview.date}")
    print(f"指数数量: {len(overview.indices)}")
    for idx in overview.indices:
        print(f"  {idx.name}: {idx.current:.2f} ({idx.change_pct:+.2f}%)")
    print(f"上涨: {overview.up_count} | 下跌: {overview.down_count}")
    print(f"成交额: {overview.total_amount:.0f}亿")

    # 测试生成模板报告
    report = analyzer._generate_template_review(overview, [])
    print(f"\n=== 复盘报告 ===")
    print(report)
