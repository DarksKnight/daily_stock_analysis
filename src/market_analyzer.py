# -*- coding: utf-8 -*-
"""
===================================
大盘复盘分析模块（支持 A 股 / 港股 / 美股）
===================================

职责：
1. 获取大盘指数数据（上证、深证、创业板 / 港股 / 美股）
2. 搜索市场新闻形成复盘情报
3. 使用大模型生成每日大盘复盘报告
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.config import get_config
from src.search_service import SearchService
from src.core.market_profile import get_profile, MarketProfile
from src.core.market_strategy import get_market_strategy_blueprint
from data_provider.base import DataFetcherManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt directory (relative to this file: src/../prompts/)
# ---------------------------------------------------------------------------
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_review_prompt_template(region: str) -> str:
    """从 prompts/ 目录加载大盘复盘 Prompt 模板文件。

    Args:
        region: 'cn' / 'hk' => market_review_cn.md; 'us' => market_review_us.md

    Returns:
        带有 {placeholder} 占位符的模板字符串（找不到文件时抛出 FileNotFoundError）
    """
    filename = "market_review_us.md" if region == "us" else "market_review_cn.md"
    filepath = _PROMPTS_DIR / filename
    if filepath.exists():
        content = filepath.read_text(encoding="utf-8")
        logger.debug(f"[MarketAnalyzer] 已加载复盘 Prompt 模板: {filepath}")
        return content
    raise FileNotFoundError(f"大盘复盘 Prompt 模板文件不存在: {filepath}。" "请确保 prompts/ 目录下包含模板文件。")


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
    # 主要指数（A股 / 美股 / 港股主指数）
    indices: List[MarketIndex] = field(default_factory=list)
    # 港股主要指数（仅 cn 区域，辅助 A 股复盘参考）
    hk_indices: List[MarketIndex] = field(default_factory=list)
    # 涨跌家数统计
    up_count: int = 0  # 上涨家数
    down_count: int = 0  # 下跌家数
    flat_count: int = 0  # 平盘家数
    limit_up_count: int = 0  # 涨停家数（含ST，主板±10%/创业板科创板±20%）
    limit_down_count: int = 0  # 跌停家数（含ST）
    non_st_limit_up_count: int = 0  # 非ST涨停家数（主流资金情绪核心指标）
    non_st_limit_down_count: int = 0  # 非ST跌停家数
    total_amount: float = 0.0  # 两市成交额（亿元）
    # 成交额历史对比
    prev_total_amount: float = 0.0  # 前一交易日成交额（亿元），0 表示无历史数据
    prev_review_date: str = ""  # 前一交易日日期字符串
    amount_ratio: float = 0.0  # 今日/前日成交额比值，0 表示无法计算
    volume_status: str = ""  # 放量 / 缩量 / 平量 / ""（无历史数据）
    # 涨跌家数判断
    rise_fall_status: str = ""  # 涨多跌少 / 跌多涨少 / 涨跌持平
    # 综合市场环境判断
    market_condition: str = ""  # 综合判断文字
    can_buy: bool = False  # True=市场环境偏好，可以考虑买入

    # 行业板块涨幅榜（展示用 top 5，全量用于存储）
    top_sectors: List[Dict] = field(default_factory=list)  # 行业涨幅前5（展示/摘要）
    bottom_sectors: List[Dict] = field(default_factory=list)  # 行业跌幅前5（展示/摘要）
    all_top_sectors: List[Dict] = field(default_factory=list)  # 全量领涨板块（用于历史存储）
    all_bottom_sectors: List[Dict] = field(default_factory=list)  # 全量领跌板块（用于历史存储）

    # 板块涨停/跌停数量排行（热点解读核心数据）
    top_sectors_by_limit_up: List[Dict] = field(default_factory=list)  # 涨停数量 Top10
    top_sectors_by_limit_down: List[Dict] = field(default_factory=list)  # 跌停数量 Top10

    # 概念板块排行（热点解读补充维度）
    top_concept_sectors: List[Dict] = field(default_factory=list)  # 概念领涨 TOP10
    bottom_concept_sectors: List[Dict] = field(default_factory=list)  # 概念领跌 TOP10
    top_concept_by_limit_up: List[Dict] = field(default_factory=list)  # 概念按涨停数量 TOP10


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
        self._last_overview: Optional[MarketOverview] = None
        self._last_news: List[Dict[str, Any]] = []

    def get_market_overview(self) -> MarketOverview:
        """
        获取市场概览数据

        Returns:
            MarketOverview: 市场概览数据对象
        """
        today = datetime.now().strftime("%Y-%m-%d")
        overview = MarketOverview(date=today)

        # 1. 获取主要指数行情（按 region 切换 A 股/美股/港股）
        overview.indices = self._get_main_indices()

        # 2. 获取港股主要指数作为 A 股复盘辅助参考（仅 cn 区域）
        if self.region == "cn":
            overview.hk_indices = self._get_hk_indices()

        # 3. 获取涨跌统计（A 股有，美股/港股无等效数据）
        if self.profile.has_market_stats:
            self._get_market_statistics(overview)

        # 4. 获取板块涨跌榜（含行业和概念，以及涨停/跌停排行；A 股独有）
        if self.profile.has_sector_rankings:
            self._get_sector_rankings(overview)

        return overview

    def _get_main_indices(self) -> List[MarketIndex]:
        """获取主要指数实时行情（不含港股参考，港股通过 _get_hk_indices 单独获取）"""
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

            if not indices:
                logger.warning("[大盘] 所有行情数据源失败，将依赖新闻搜索进行分析")
            else:
                logger.info(f"[大盘] 获取到 {len(indices)} 个指数行情")

        except Exception as e:
            logger.error(f"[大盘] 获取指数行情失败: {e}")

        return indices

    def _get_hk_indices(self) -> List[MarketIndex]:
        """获取港股主要指数行情（恒生指数、恒生科技指数），作为 A 股复盘辅助参考。"""
        _HK_INCLUDE = frozenset({"HSI", "HSTECH"})
        indices = []
        try:
            logger.info("[大盘] 获取港股主要指数行情（辅助A股复盘）...")
            data_list = self.data_manager.get_main_indices(region="hk")
            if data_list:
                for item in data_list:
                    if item.get("code") not in _HK_INCLUDE:
                        continue
                    indices.append(
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
            if indices:
                logger.info(f"[大盘] 获取到 {len(indices)} 个港股参考指数: {[i.name for i in indices]}")
            else:
                logger.info("[大盘] 港股参考指数暂不可用（不影响A股复盘）")
        except Exception as e:
            logger.warning(f"[大盘] 获取港股参考指数失败（非致命）: {e}")
        return indices

    def _get_market_statistics(self, overview: MarketOverview):
        """获取市场涨跌统计，并计算成交额对比、涨跌家数判断和综合市场环境。"""
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

                # 保存当日统计 & 读取前日成交额
                self._save_and_load_market_daily_stats(overview)

                # 计算成交额对比（放量/缩量/平量）
                self._compute_volume_comparison(overview)

                # 计算涨跌家数判断
                self._compute_rise_fall_status(overview)

                # 综合市场环境判断
                self._compute_market_condition(overview)

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
                overview.prev_review_date = str(prev.get("trade_date", ""))
                logger.info(
                    "[大盘] 前一交易日(%s)成交额: %.0f亿，今日: %.0f亿",
                    overview.prev_review_date,
                    overview.prev_total_amount,
                    overview.total_amount,
                )
        except Exception as exc:
            logger.warning("[大盘] 市场统计历史对比失败: %s", exc)

    def _compute_volume_comparison(self, overview: MarketOverview) -> None:
        """根据前日成交额计算成交额比值和放量/缩量状态。"""
        if overview.total_amount <= 0 or overview.prev_total_amount <= 0:
            return
        overview.amount_ratio = overview.total_amount / overview.prev_total_amount
        if overview.amount_ratio >= 1.1:
            overview.volume_status = "放量"
        elif overview.amount_ratio <= 0.9:
            overview.volume_status = "缩量"
        else:
            overview.volume_status = "平量"
        logger.info(
            "[大盘] 成交额比较: 今日=%.0f亿 前日(%s)=%.0f亿 比值=%.2f → %s",
            overview.total_amount,
            overview.prev_review_date,
            overview.prev_total_amount,
            overview.amount_ratio,
            overview.volume_status,
        )

    def _compute_rise_fall_status(self, overview: MarketOverview) -> None:
        """根据涨跌家数计算涨多跌少 / 跌多涨少 / 涨跌持平。"""
        if overview.up_count == 0 and overview.down_count == 0:
            overview.rise_fall_status = ""
            return
        if overview.up_count > overview.down_count:
            overview.rise_fall_status = "涨多跌少"
        elif overview.up_count < overview.down_count:
            overview.rise_fall_status = "跌多涨少"
        else:
            overview.rise_fall_status = "涨跌持平"

    def _compute_market_condition(self, overview: MarketOverview) -> None:
        """
        根据量能状态和涨跌家数，综合判断市场环境并设置 can_buy 标志。

        判断矩阵（与 demo-agent 一致）：
          放量 + 涨多跌少 → 市场偏强，可关注买入机会  ✅
          放量 + 跌多涨少 → 放量下跌，市场偏弱         ❌
          放量 + 涨跌持平 → 放量震荡，方向不明，谨慎   ⚠️
          缩量 + 涨多跌少 → 缩量上涨，注意分歧，谨慎追高 ⚠️
          缩量 + 跌多涨少 → 缩量下跌，市场偏弱         ❌
          缩量 + 涨跌持平 → 缩量盘整，观望             ⚠️
          平量 + 涨多跌少 → 稳量上涨，可适当关注       ⚠️✅
          平量 + 跌多涨少 → 稳量下跌，谨慎             ⚠️
          平量 + 涨跌持平 → 量价平稳，观望为主         ⚠️
          无历史数据     → 简单按涨跌家数判断
        """
        vol = overview.volume_status
        rf = overview.rise_fall_status

        if not vol:
            # 无历史数据，仅按涨跌家数做简单判断
            if rf == "涨多跌少":
                overview.market_condition = "个股涨多跌少，市场偏积极，可适当关注买入机会"
                overview.can_buy = True
            elif rf == "跌多涨少":
                overview.market_condition = "个股跌多涨少，市场偏弱，建议观望"
                overview.can_buy = False
            else:
                overview.market_condition = "市场整体平衡，建议观望"
                overview.can_buy = False
            return

        condition_map = {
            ("放量", "涨多跌少"): ("放量上涨，个股涨多跌少，市场偏强，可关注买入机会", True),
            ("放量", "跌多涨少"): ("放量下跌，个股跌多涨少，市场偏弱，不建议买入", False),
            ("放量", "涨跌持平"): ("放量震荡，方向不明，谨慎操作", False),
            ("缩量", "涨多跌少"): ("缩量上涨，注意分歧，谨慎追高", False),
            ("缩量", "跌多涨少"): ("缩量下跌，市场偏弱，不建议买入", False),
            ("缩量", "涨跌持平"): ("缩量盘整，持观望态度", False),
            ("平量", "涨多跌少"): ("稳量上涨，个股涨多跌少，市场尚可，可适当关注买入机会", True),
            ("平量", "跌多涨少"): ("稳量下跌，个股跌多涨少，谨慎操作", False),
            ("平量", "涨跌持平"): ("量价平稳，市场分歧，观望为主", False),
        }

        key = (vol, rf) if rf else (vol, "涨跌持平")
        result = condition_map.get(key)
        if result:
            overview.market_condition = result[0]
            overview.can_buy = result[1]
        else:
            overview.market_condition = f"{vol}，市场整体平衡，建议观望"
            overview.can_buy = False

        buy_label = "✅ 可以考虑买入" if overview.can_buy else "❌ 建议观望/不买入"
        logger.info("[大盘] 市场环境: %s → %s", overview.market_condition, buy_label)

    # 统计性虚拟板块：并非真实投资主题，从概念涨跌榜中过滤
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

    @staticmethod
    def _has_sector_limit_fields(sectors: List[Dict]) -> bool:
        """判断板块列表是否已包含涨停/跌停统计字段。"""
        return any(
            "limit_up_count" in sector or "limit_down_count" in sector
            for sector in (sectors or [])
        )

    @staticmethod
    def _enrich_sector_rankings(sectors: List[Dict], stats_by_name: Dict[str, Dict]) -> List[Dict]:
        """按板块名称补齐排行结果中的涨跌停统计字段，保留原有排序。"""
        enriched: List[Dict] = []
        for sector in sectors or []:
            item = dict(sector)
            name = str(item.get("name", "")).strip()
            if name and name in stats_by_name:
                stats = stats_by_name[name]
                for key in (
                    "change_pct",
                    "limit_up_count",
                    "limit_down_count",
                    "up_count",
                    "down_count",
                ):
                    if key not in item or item.get(key) is None:
                        item[key] = stats.get(key)
            enriched.append(item)
        return enriched

    @staticmethod
    def _merge_unique_sectors(*sector_lists: List[Dict]) -> List[Dict]:
        """按板块名称去重合并多个列表，优先保留先出现的数据。"""
        merged: Dict[str, Dict] = {}
        ordered: List[Dict] = []

        for sector_list in sector_lists:
            for sector in sector_list or []:
                name = str(sector.get("name", "")).strip()
                if not name:
                    continue

                existing = merged.get(name)
                if existing is None:
                    existing = dict(sector)
                    existing["name"] = name
                    merged[name] = existing
                    ordered.append(existing)
                    continue

                for key, value in sector.items():
                    if key == "name" or value is None or value == "":
                        continue
                    if key not in existing or existing.get(key) is None:
                        existing[key] = value

        return ordered

    def _get_recent_sector_limit_trade_dates(self, lookback_days: int = 7) -> List[str]:
        """生成近几日的候选交易日期，供板块涨跌停统计回看使用。"""
        base_date = datetime.now().date()
        return [(base_date - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(lookback_days)]

    def _load_sector_limit_stats_with_fallback(self) -> List[Dict]:
        """获取最近可用的板块涨跌停统计，兼容周末/非交易日回看。"""
        for trade_date in self._get_recent_sector_limit_trade_dates():
            try:
                stats = self.data_manager.get_sector_limit_stats(trade_date=trade_date)
            except Exception as exc:
                logger.warning("[大盘] 获取 %s 的板块涨跌停统计失败: %s", trade_date, exc)
                continue

            if stats:
                logger.info("[大盘] 使用 %s 的板块涨跌停统计补齐行业排行", trade_date)
                return stats

        return []

    def _populate_sector_limit_rankings(self, overview: MarketOverview, all_sectors: List[Dict]) -> None:
        """根据板块涨跌停统计生成 Top10 排名。"""
        if not self._has_sector_limit_fields(all_sectors):
            logger.info("[大盘] 涨停/跌停数量字段不可用，跳过按涨跌停排名")
            return

        overview.top_sectors_by_limit_up = sorted(
            [s for s in all_sectors if (s.get("limit_up_count") or 0) > 0],
            key=lambda x: (-(x.get("limit_up_count") or 0), -(x.get("change_pct") or 0)),
        )[:10]
        overview.top_sectors_by_limit_down = sorted(
            [s for s in all_sectors if (s.get("limit_down_count") or 0) > 0],
            key=lambda x: (-(x.get("limit_down_count") or 0), x.get("change_pct") or 0),
        )[:10]

        if overview.top_sectors_by_limit_up:
            logger.info(
                "[大盘] 涨停板块Top10: %s",
                [(s["name"], s.get("limit_up_count", 0)) for s in overview.top_sectors_by_limit_up],
            )
        else:
            logger.info("[大盘] 当前板块涨停统计可用，但无涨停板块")

        if overview.top_sectors_by_limit_down:
            logger.info(
                "[大盘] 跌停板块Top10: %s",
                [(s["name"], s.get("limit_down_count", 0)) for s in overview.top_sectors_by_limit_down],
            )
        else:
            logger.info("[大盘] 当前板块跌停统计可用，但无跌停板块")

    def _get_sector_rankings(self, overview: MarketOverview) -> None:
        """
        获取行业板块涨跌榜、概念板块涨跌榜，以及涨停/跌停数量排行。

        一次性获取全量行业板块数据，从中计算：
        - top_sectors / bottom_sectors（展示用 Top5）
        - all_top_sectors / all_bottom_sectors（全量，用于历史存储）
        - top_sectors_by_limit_up / top_sectors_by_limit_down（按涨停/跌停数量 Top10）
        同时获取概念板块及其涨停排行。
        """
        # ---- 行业板块 ----
        try:
            logger.info("[大盘] 获取行业板块涨跌榜（全量）...")
            all_top, all_bottom = self.data_manager.get_sector_rankings(1000)

            if all_top or all_bottom:
                overview.all_top_sectors = all_top or []
                overview.all_bottom_sectors = all_bottom or []
                overview.top_sectors = overview.all_top_sectors[:5]
                overview.bottom_sectors = overview.all_bottom_sectors[:5]

                logger.info(
                    "[大盘] 领涨板块(展示): %s，全量 %d 个",
                    [s["name"] for s in overview.top_sectors],
                    len(overview.all_top_sectors),
                )
                logger.info(
                    "[大盘] 领跌板块(展示): %s，全量 %d 个",
                    [s["name"] for s in overview.bottom_sectors],
                    len(overview.all_bottom_sectors),
                )

                all_sectors = self._merge_unique_sectors(overview.all_top_sectors, overview.all_bottom_sectors)
                if not self._has_sector_limit_fields(all_sectors):
                    limit_stats = self._load_sector_limit_stats_with_fallback()
                    if limit_stats:
                        stats_by_name = {
                            str(s.get("name", "")).strip(): s
                            for s in limit_stats
                            if s.get("name")
                        }
                        overview.all_top_sectors = self._enrich_sector_rankings(overview.all_top_sectors, stats_by_name)
                        overview.all_bottom_sectors = self._enrich_sector_rankings(
                            overview.all_bottom_sectors,
                            stats_by_name,
                        )
                        overview.top_sectors = overview.all_top_sectors[:5]
                        overview.bottom_sectors = overview.all_bottom_sectors[:5]
                        all_sectors = self._merge_unique_sectors(
                            overview.all_top_sectors,
                            overview.all_bottom_sectors,
                            limit_stats,
                        )

                self._populate_sector_limit_rankings(overview, all_sectors)

                # 保存当日全量板块快照到 DB
                self._save_sector_snapshot(overview)

        except Exception as e:
            logger.error("[大盘] 获取行业板块涨跌榜失败: %s", e)

        # ---- 概念板块 ----
        try:
            logger.info("[大盘] 获取概念板块涨跌榜...")
            concept_result = self.data_manager.get_concept_sector_rankings(20)
            if concept_result:
                all_top_c, all_bottom_c = concept_result
                all_top_c = [s for s in (all_top_c or []) if s.get("name") not in self._CONCEPT_EXCLUDE]
                all_bottom_c = [s for s in (all_bottom_c or []) if s.get("name") not in self._CONCEPT_EXCLUDE]
                overview.top_concept_sectors = all_top_c[:10]
                overview.bottom_concept_sectors = all_bottom_c[:10]

                # 概念板块按涨停数量排行
                has_c_limit = any(s.get("limit_up_count", 0) > 0 for s in all_top_c)
                if has_c_limit:
                    overview.top_concept_by_limit_up = sorted(
                        [s for s in all_top_c if s.get("limit_up_count", 0) > 0],
                        key=lambda x: (-x.get("limit_up_count", 0), -x.get("change_pct", 0)),
                    )[:10]

                logger.info("[大盘] 领涨概念TOP10: %s", [s["name"] for s in overview.top_concept_sectors[:5]])
        except Exception as e:
            logger.warning("[大盘] 获取概念板块涨跌榜失败（非致命）: %s", e)

    def _save_sector_snapshot(self, overview: MarketOverview) -> None:
        """保存当日行业板块快照到数据库（用于多日热点趋势统计）。"""
        try:
            from datetime import date as _date
            from src.storage import get_db

            db = get_db()
            db.save_sector_snapshot(
                trade_date=_date.today(),
                region=self.region,
                top_sectors=overview.top_sectors,
                bottom_sectors=overview.bottom_sectors,
            )
        except Exception as exc:
            logger.warning("[大盘] 板块快照存库失败（非致命）: %s", exc)

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

    def _fetch_hotspot_stats(self, days: int = 5) -> dict:
        """
        从数据库获取多日板块热点趋势统计（非致命）。

        Args:
            days: 分析窗口（交易日数）

        Returns:
            热点统计 dict，失败时返回空 dict
        """
        try:
            from src.repositories.market_review_repo import MarketReviewRepository

            repo = MarketReviewRepository()
            stats = repo.get_sector_hotspot_stats(days=days, region=self.region)
            if stats.get("days_analyzed", 0) > 0:
                logger.info(
                    "[大盘] 热点趋势: 分析近 %d 个交易日，领涨板块 %d 个，领跌板块 %d 个",
                    stats["days_analyzed"],
                    len(stats["top_sectors"]),
                    len(stats["bottom_sectors"]),
                )
            return stats
        except Exception as e:
            logger.warning("[大盘] 获取热点趋势统计失败（非致命）: %s", e)
            return {}

    def _build_hotspot_trend_block(self, hotspot_stats: dict, days: int = 5) -> str:
        """
        构建多日板块热点趋势注入块。

        Args:
            hotspot_stats: _fetch_hotspot_stats() 的返回值
            days: 显示用的窗口天数

        Returns:
            Markdown 块字符串，无数据时返回空字符串
        """
        if not hotspot_stats or hotspot_stats.get("days_analyzed", 0) == 0:
            return ""

        analyzed = hotspot_stats["days_analyzed"]
        dates = hotspot_stats.get("dates", [])
        top_sectors = hotspot_stats.get("top_sectors", [])
        bottom_sectors = hotspot_stats.get("bottom_sectors", [])

        if not top_sectors and not bottom_sectors:
            return ""

        date_range = ""
        if dates:
            date_range = f"（{dates[-1]} ~ {dates[0]}）"

        lines = [f"> 📊 近{analyzed}日热点追踪{date_range}"]

        if top_sectors:
            parts = [f"**{s['name']}**({s['days']}天)" for s in top_sectors[:5]]
            lines.append(f"> 🏆 领涨频次: {' | '.join(parts)}")

        if bottom_sectors:
            parts = [f"**{s['name']}**({s['days']}天)" for s in bottom_sectors[:5]]
            lines.append(f"> 📉 领跌频次: {' | '.join(parts)}")

        return "\n".join(lines)

    def generate_market_review(self, overview: MarketOverview, news: List) -> str:
        """
        使用大模型生成大盘复盘报告

        Args:
            overview: 市场概览数据
            news: 市场新闻列表 (SearchResult 对象列表)

        Returns:
            大盘复盘报告文本
        """
        # 预取多日热点趋势（非致命，失败返回空 dict）
        hotspot_stats = self._fetch_hotspot_stats(days=5)

        if not self.analyzer or not self.analyzer.is_available():
            logger.warning("[大盘] AI分析器未配置或不可用，使用模板生成报告")
            return self._generate_template_review(overview, news, hotspot_stats=hotspot_stats)

        # 构建 Prompt（从外部模板文件加载）
        prompt = self._build_review_prompt(overview, news, hotspot_stats=hotspot_stats)

        try:
            logger.info("[大盘] 调用大模型生成复盘报告...")
            review = self.analyzer.generate_text(prompt, max_tokens=2048, temperature=0.7)
            review = review.strip() if review else None

            if review:
                logger.info("[大盘] 复盘报告生成成功，长度: %d 字符", len(review))
                return self._inject_data_into_review(review, overview, hotspot_stats=hotspot_stats)
            else:
                logger.warning("[大盘] 大模型返回为空，使用模板报告")
                return self._generate_template_review(overview, news, hotspot_stats=hotspot_stats)
        except Exception as e:
            logger.error("[大盘] 大模型生成复盘报告失败: %s", e)
            return self._generate_template_review(overview, news, hotspot_stats=hotspot_stats)

    def _inject_data_into_review(
        self,
        review: str,
        overview: MarketOverview,
        hotspot_stats: Optional[Dict] = None,
    ) -> str:
        """将结构化数据表格注入 LLM 生成的各章节。"""
        stats_block = self._build_stats_block(overview)
        indices_block = self._build_indices_block(overview)
        sector_block = self._build_sector_block(overview, hotspot_stats=hotspot_stats)

        if stats_block:
            review = self._insert_after_section(review, r"###\s*[一1]、?市场总结", stats_block)
        if indices_block:
            review = self._insert_after_section(review, r"###\s*[二2]、?指数点评", indices_block)
        if sector_block:
            review = self._insert_after_section(review, r"###\s*[四4]、?热点解读", sector_block)

        return review

    @staticmethod
    def _insert_after_section(text: str, heading_pattern: str, block: str) -> str:
        """在指定 Markdown 小节末尾（下一个 ### 标题之前）插入数据块。"""
        import re

        match = re.search(heading_pattern, text)
        if not match:
            return text
        start = match.end()
        next_heading = re.search(r"\n###\s", text[start:])
        if next_heading:
            insert_pos = start + next_heading.start()
        else:
            insert_pos = len(text)
        return text[:insert_pos].rstrip() + "\n\n" + block + "\n\n" + text[insert_pos:].lstrip("\n")

    def _build_stats_block(self, overview: MarketOverview) -> str:
        """构建市场统计摘要块（成交额、涨跌家数、涨停、量能状态、市场环境判断、港股参考）。"""
        has_stats = overview.up_count or overview.down_count or overview.total_amount
        if not has_stats:
            return ""

        lines = []

        # 主行：涨跌家数 + 涨停 + 成交额
        lines.append(
            f"> 📈 上涨 **{overview.up_count}** 家 / 下跌 **{overview.down_count}** 家 / "
            f"平盘 **{overview.flat_count}** 家 | "
            f"涨停 **{overview.limit_up_count}**（非ST **{overview.non_st_limit_up_count}**）/ "
            f"跌停 **{overview.limit_down_count}**（非ST **{overview.non_st_limit_down_count}**）| "
            f"成交额 **{overview.total_amount:.0f}** 亿"
        )

        # 成交额对比行（有历史数据时）
        if overview.volume_status and overview.prev_total_amount > 0:
            pct_change = (overview.amount_ratio - 1) * 100
            sign = "+" if pct_change >= 0 else ""
            vol_emoji = {"放量": "🔥", "缩量": "📉", "平量": "📊"}.get(overview.volume_status, "📊")
            lines.append(
                f"> {vol_emoji} 较前日({overview.prev_review_date})成交额 "
                f"**{overview.prev_total_amount:.0f}** 亿，"
                f"变化 **{sign}{pct_change:.1f}%**，属于**{overview.volume_status}**"
            )

        # 涨跌家数判断行
        if overview.rise_fall_status:
            rf_emoji = (
                "🟢"
                if overview.rise_fall_status == "涨多跌少"
                else ("🔴" if overview.rise_fall_status == "跌多涨少" else "⚪")
            )
            lines.append(f"> {rf_emoji} 个股表现：**{overview.rise_fall_status}**")

        # 综合市场环境判断行
        if overview.market_condition:
            buy_tag = "✅ **可以考虑买入**" if overview.can_buy else "❌ **建议观望/不买入**"
            lines.append(f"> 🏦 市场环境：{overview.market_condition} → {buy_tag}")

        # 港股参考（仅 A 股区域）
        if overview.hk_indices:
            lines.append("")
            lines.append("> 🇭🇰 **港股外围参考**")
            for idx in overview.hk_indices:
                arrow = "🔴" if idx.change_pct < 0 else "🟢" if idx.change_pct > 0 else "⚪"
                lines.append(f"> {arrow} {idx.name}: **{idx.current:.2f}** ({idx.change_pct:+.2f}%)")

        return "\n".join(lines)

    def _build_indices_block(self, overview: MarketOverview) -> str:
        """构建指数行情表格（不含振幅），港股附加为辅助参考块。"""
        if not overview.indices and not overview.hk_indices:
            return ""
        lines = []
        if overview.indices:
            lines += ["| 指数 | 最新 | 涨跌幅 | 成交额(亿) |", "|------|------|--------|-----------|"]
            for idx in overview.indices:
                arrow = "🔴" if idx.change_pct < 0 else "🟢" if idx.change_pct > 0 else "⚪"
                amount_raw = idx.amount or 0.0
                if amount_raw == 0.0:
                    amount_str = "N/A"
                elif amount_raw > 1e6:
                    amount_str = f"{amount_raw / 1e8:.0f}"
                else:
                    amount_str = f"{amount_raw:.0f}"
                lines.append(f"| {idx.name} | {idx.current:.2f} | {arrow} {idx.change_pct:+.2f}% | {amount_str} |")
        if overview.hk_indices:
            if lines:
                lines.append("")
            lines.append("> 🇭🇰 **港股参考（辅助A股复盘）**")
            for idx in overview.hk_indices:
                arrow = "🔴" if idx.change_pct < 0 else "🟢" if idx.change_pct > 0 else "⚪"
                lines.append(f"> {arrow} {idx.name}: **{idx.current:.2f}** ({idx.change_pct:+.2f}%)")
        return "\n".join(lines)

    def _build_sector_block(
        self,
        overview: MarketOverview,
        hotspot_stats: Optional[Dict] = None,
    ) -> str:
        """构建板块排行块（行业涨停榜、概念热点、多日趋势）。"""
        has_data = (
            overview.top_sectors_by_limit_up
            or overview.top_sectors_by_limit_down
            or overview.top_concept_sectors
            or overview.bottom_concept_sectors
            or overview.top_concept_by_limit_up
        )
        if not has_data:
            return ""
        lines = []

        # 行业板块 TOP10（按涨停数量）
        if overview.top_sectors_by_limit_up:
            lines.append("")
            lines.append("> 🚀 **行业板块 TOP10（按涨停数量）**")
            lines.append("> | 排名 | 板块 | 涨停数 | 涨跌幅 |")
            lines.append("> |------|------|--------|--------|")
            for rank, s in enumerate(overview.top_sectors_by_limit_up, 1):
                lines.append(f"> | {rank} | {s['name']} | {s.get('limit_up_count', 0)} | {s['change_pct']:+.2f}% |")

        # 行业板块 TOP10（按跌停数量）
        if overview.top_sectors_by_limit_down:
            lines.append("")
            lines.append("> 🧊 **行业板块 TOP10（按跌停数量）**")
            lines.append("> | 排名 | 板块 | 跌停数 | 涨跌幅 |")
            lines.append("> |------|------|--------|--------|")
            for rank, s in enumerate(overview.top_sectors_by_limit_down, 1):
                lines.append(f"> | {rank} | {s['name']} | {s.get('limit_down_count', 0)} | {s['change_pct']:+.2f}% |")

        # 近1日热点追踪（概念板块）
        if overview.top_concept_sectors or overview.bottom_concept_sectors:
            lines.append("")
            lines.append("> 📊 **近1日热点追踪（概念板块）**")
            if overview.top_concept_sectors:
                parts = [f"**{s['name']}**({s['change_pct']:+.2f}%)" for s in overview.top_concept_sectors[:10]]
                lines.append(f"> 🏆 领涨 TOP10: {' | '.join(parts)}")
            if overview.bottom_concept_sectors:
                parts = [f"**{s['name']}**({s['change_pct']:+.2f}%)" for s in overview.bottom_concept_sectors[:10]]
                lines.append(f"> 📉 领跌 TOP10: {' | '.join(parts)}")

        # 概念板块 TOP10（按涨停数量）
        if overview.top_concept_by_limit_up:
            lines.append("")
            lines.append("> 🌟 **概念板块 TOP10（按涨停数量）**")
            lines.append("> | 排名 | 概念 | 涨停数 | 涨跌幅 |")
            lines.append("> |------|------|--------|--------|")
            for rank, s in enumerate(overview.top_concept_by_limit_up, 1):
                lines.append(f"> | {rank} | {s['name']} | {s.get('limit_up_count', 0)} | {s['change_pct']:+.2f}% |")

        # 多日热点趋势（来自 DB 历史记录）
        if hotspot_stats:
            hotspot_block = self._build_hotspot_trend_block(hotspot_stats)
            if hotspot_block:
                lines.append("")
                lines.append(hotspot_block)

        return "\n".join(lines)

    def _build_review_prompt(
        self,
        overview: MarketOverview,
        news: List,
        hotspot_stats: Optional[Dict] = None,
    ) -> str:
        """从外部模板文件加载 Prompt，并将动态数据注入占位符。"""
        # 指数行情文本（简洁格式）
        indices_text = ""
        for idx in overview.indices:
            direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
            indices_text += f"- {idx.name}: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n"

        # 港股指数文本（仅 A 股区域）
        hk_indices_text = ""
        if overview.hk_indices:
            for idx in overview.hk_indices:
                direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
                hk_indices_text += f"- {idx.name}: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n"

        # 涨停/跌停板块文本
        def _fmt_limit_rows(sectors: List[Dict], count_key: str, label: str) -> str:
            if not sectors:
                return "暂无数据"
            rows = [
                f"  {rank}. {s['name']}（{label}{s.get(count_key, 0)}家，涨跌幅{s['change_pct']:+.2f}%）"
                for rank, s in enumerate(sectors, 1)
            ]
            return "\n".join(rows)

        limit_up_text = _fmt_limit_rows(overview.top_sectors_by_limit_up, "limit_up_count", "涨停")
        limit_down_text = _fmt_limit_rows(overview.top_sectors_by_limit_down, "limit_down_count", "跌停")

        # 概念板块文本
        concept_up_text = (
            "\n".join(
                f"  {rank}. {s['name']}（涨跌幅{s['change_pct']:+.2f}%）"
                for rank, s in enumerate(overview.top_concept_sectors[:10], 1)
            )
            or "暂无数据"
        )
        concept_down_text = (
            "\n".join(
                f"  {rank}. {s['name']}（涨跌幅{s['change_pct']:+.2f}%）"
                for rank, s in enumerate(overview.bottom_concept_sectors[:10], 1)
            )
            or ""
        )
        concept_limit_text = (
            "\n".join(
                f"  {rank}. {s['name']}（涨停{s.get('limit_up_count', 0)}家，涨跌幅{s['change_pct']:+.2f}%）"
                for rank, s in enumerate(overview.top_concept_by_limit_up, 1)
            )
            or ""
        )

        # 多日热点趋势文本
        hotspot_trend_text = self._build_hotspot_trend_block(hotspot_stats or {}) if hotspot_stats else ""

        # 新闻
        news_text = ""
        for i, n in enumerate(news[:6], 1):
            if hasattr(n, "title"):
                title = n.title[:50] if n.title else ""
                snippet = n.snippet[:100] if n.snippet else ""
            else:
                title = n.get("title", "")[:50]
                snippet = n.get("snippet", "")[:100]
            news_text += f"{i}. {title}\n   {snippet}\n"

        # ---- 构建 stats_block 和 sector_block 注入模板 ----
        stats_block = ""
        sector_block = ""

        if self.region == "us":
            if self.profile.has_market_stats:
                stats_block = (
                    f"## Market Overview\n"
                    f"- Up: {overview.up_count} | Down: {overview.down_count} | Flat: {overview.flat_count}\n"
                    f"- Non-ST limit up: {overview.non_st_limit_up_count} | "
                    f"Non-ST limit down: {overview.non_st_limit_down_count}\n"
                    f"- Total volume (CNY bn): {overview.total_amount:.0f}"
                )
            else:
                stats_block = "## Market Overview\n(US market has no equivalent advance/decline stats.)"

            if self.profile.has_sector_rankings:
                hotspot_us = f"\nMulti-Day Trend (~5 days):\n{hotspot_trend_text}" if hotspot_trend_text else ""
                top_text = ", ".join([f"{s['name']}({s['change_pct']:+.2f}%)" for s in overview.top_sectors[:3]])
                bot_text = ", ".join([f"{s['name']}({s['change_pct']:+.2f}%)" for s in overview.bottom_sectors[:3]])
                sector_block = (
                    f"## Sector Performance\n"
                    f"Leading: {top_text or 'N/A'}\n"
                    f"Lagging: {bot_text or 'N/A'}"
                    f"{hotspot_us}"
                )
            else:
                sector_block = "## Sector Performance\n(US sector data not available.)"
        else:
            # A 股 / 港股
            if self.profile.has_market_stats:
                # 成交额与前日对比描述
                if overview.volume_status and overview.prev_total_amount > 0:
                    pct = (overview.amount_ratio - 1) * 100
                    sign = "+" if pct >= 0 else ""
                    vol_desc = (
                        f"\n- 与前日({overview.prev_review_date})成交额 {overview.prev_total_amount:.0f} 亿相比，"
                        f"变化 {sign}{pct:.1f}%，属于**{overview.volume_status}**"
                    )
                else:
                    vol_desc = ""
                rf_desc = f"\n- 个股涨跌表现：{overview.rise_fall_status}" if overview.rise_fall_status else ""
                cond_desc = ""
                if overview.market_condition:
                    buy_label = "✅ 可以考虑买入" if overview.can_buy else "❌ 建议观望/不买入"
                    cond_desc = f"\n- **市场环境综合判断：{overview.market_condition} → {buy_label}**"
                # ST涨停行（数据可用时才显示）
                st_count = overview.limit_up_count - overview.non_st_limit_up_count
                st_down_count = overview.limit_down_count - overview.non_st_limit_down_count
                st_line = ""
                if st_count > 0 or st_down_count > 0:
                    st_line = (
                        f"\n- ST类涨停: {st_count} 家 | ST类跌停: {st_down_count} 家"
                        f"（ST股±5%限制，ST涨停↑情绪参考）"
                    )
                stats_block = (
                    f"## 市场概况\n"
                    f"- 上涨: {overview.up_count} 家 | 下跌: {overview.down_count} 家 | 平盘: {overview.flat_count} 家\n"
                    f"- 非ST涨停: {overview.non_st_limit_up_count} 家 | 非ST跌停: {overview.non_st_limit_down_count} 家"
                    f"（主板±10%/创业板科创板±20%）{st_line}\n"
                    f"- 两市成交额: {overview.total_amount:.0f} 亿元"
                    f"{vol_desc}{rf_desc}{cond_desc}"
                )
            else:
                stats_block = (
                    "## 市场概况\n（港股暂无涨跌家数等统计）"
                    if self.region == "hk"
                    else "## 市场概况\n（美股暂无涨跌家数等统计）"
                )

            if self.profile.has_sector_rankings:
                concept_block = ""
                if concept_up_text or concept_down_text:
                    parts = ["\n## 近1日热点追踪（概念板块）"]
                    if concept_up_text:
                        parts.append(f"领涨频次TOP10:\n{concept_up_text}")
                    if concept_down_text:
                        parts.append(f"领跌频次TOP10:\n{concept_down_text}")
                    if concept_limit_text:
                        parts.append(f"概念板块按涨停数量TOP10:\n{concept_limit_text}")
                    if hotspot_trend_text:
                        parts.append(f"单日热门主题追踪（概念板块）:\n{hotspot_trend_text}")
                    concept_block = "\n".join(parts)
                limit_up_block = (
                    f"\n\n## 行业板块TOP10（按涨停数量）\n{limit_up_text}" if overview.top_sectors_by_limit_up else ""
                )
                limit_down_block = (
                    f"\n\n## 行业板块TOP10（按跌停数量）\n{limit_down_text}"
                    if overview.top_sectors_by_limit_down
                    else ""
                )
                sector_block = f"## 行业板块表现{limit_up_block}{limit_down_block}{concept_block}"
            else:
                sector_block = (
                    "## 板块表现\n（港股暂无板块行业数据）"
                    if self.region == "hk"
                    else "## 板块表现\n（美股暂无板块涨跌数据）"
                )

        # 占位符替换
        indices_placeholder = indices_text or (
            "No index data (API error)" if self.region == "us" else "暂无指数数据（接口异常）"
        )
        hk_placeholder = hk_indices_text or "暂无港股指数数据"
        news_placeholder = news_text or ("No relevant news" if self.region == "us" else "暂无相关新闻")
        data_missing_hint = (
            (
                "Note: Market data fetch failed. Rely mainly on [Market News] for qualitative analysis. "
                "Do not invent index levels."
                if self.region == "us"
                else "注意：由于行情数据获取失败，请主要根据【市场新闻】进行定性分析和总结，不要编造具体的指数点位。"
            )
            if not indices_text
            else ""
        )

        # 加载外部模板并替换占位符
        try:
            template = _load_review_prompt_template(self.region)
        except FileNotFoundError as e:
            logger.warning("[大盘] Prompt 模板文件缺失，回退到内联 Prompt: %s", e)
            template = self._build_fallback_prompt(overview)
            return template

        result = (
            template.replace("{date}", overview.date)
            .replace("{indices}", indices_placeholder)
            .replace("{stats_block}", stats_block)
            .replace("{sector_block}", sector_block)
            .replace("{news}", news_placeholder)
            .replace("{data_missing_hint}", data_missing_hint)
        )
        # A/H 区域额外占位符
        if self.region != "us":
            result = (
                result.replace("{hk_indices}", hk_placeholder)
                .replace("{volume_status}", overview.volume_status or "成交量情况")
                .replace("{rise_fall_status}", overview.rise_fall_status or "涨跌情况")
                .replace("{index_hint}", self.profile.prompt_index_hint)
            )
        # 策略模块（如模板包含 {strategy_block}）
        result = result.replace("{strategy_block}", self.strategy.to_prompt_block())
        return result

    def _build_fallback_prompt(self, overview: MarketOverview) -> str:
        """Prompt 模板文件缺失时的兜底内联 Prompt（简版）。"""
        market_label = {"cn": "A股", "hk": "港股", "us": "美股"}.get(self.region, "大盘")
        return (
            f"你是专业市场分析师，请根据以下数据生成{market_label}大盘复盘报告（纯Markdown格式）：\n\n"
            f"日期：{overview.date}\n"
            f"主要指数：{', '.join(f'{i.name}{i.change_pct:+.2f}%' for i in overview.indices)}\n"
            f"请输出包含市场总结、指数点评、资金动向、热点解读、后市展望、风险提示的完整复盘报告。"
        )

    def _generate_template_review(
        self,
        overview: MarketOverview,
        news: List,
        hotspot_stats: Optional[Dict] = None,
    ) -> str:
        """使用模板生成复盘报告（无大模型时的备选方案）"""
        mood_code = self.profile.mood_index_code
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

        # 港股简要描述（仅 A 股区域）
        hk_summary = ""
        if self.region == "cn" and overview.hk_indices:
            hk_parts = [
                f"{idx.name} {'↑' if idx.change_pct > 0 else '↓' if idx.change_pct < 0 else '-'}{abs(idx.change_pct):.2f}%"
                for idx in overview.hk_indices
            ]
            all_up = all(i.change_pct >= 0 for i in overview.hk_indices)
            all_down = all(i.change_pct < 0 for i in overview.hk_indices)
            sentiment = (
                "偏暖，对A股情绪形成一定支撑"
                if all_up
                else ("偏弱，对A股情绪形成拖累" if all_down else "涨跌不一，对A股情绪影响有限")
            )
            hk_summary = f"港股方面，{' / '.join(hk_parts)}，外围环境{sentiment}。"

        # 板块信息
        top_text = "、".join([s["name"] for s in overview.top_sectors[:3]])
        bottom_text = "、".join([s["name"] for s in overview.bottom_sectors[:3]])

        # 涨跌统计（A 股有，美股/港股无）
        stats_section = ""
        if self.profile.has_market_stats:
            # 成交额对比行
            vol_line = ""
            if overview.volume_status and overview.prev_total_amount > 0:
                pct = (overview.amount_ratio - 1) * 100
                sign = "+" if pct >= 0 else ""
                vol_line = (
                    f"\n| 成交额对比 | 今日 {overview.total_amount:.0f}亿 vs "
                    f"前日({overview.prev_review_date}) {overview.prev_total_amount:.0f}亿，"
                    f"变化 {sign}{pct:.1f}%（{overview.volume_status}） |"
                )
            rf_line = f"\n| 个股涨跌 | **{overview.rise_fall_status}** |" if overview.rise_fall_status else ""
            condition_line = ""
            if overview.market_condition:
                buy_tag = "✅ 可以考虑买入" if overview.can_buy else "❌ 建议观望/不买入"
                condition_line = f"\n| 市场环境判断 | {overview.market_condition} → **{buy_tag}** |"
            stats_section = (
                f"\n### 三、涨跌统计\n"
                f"| 指标 | 数值 |\n|------|------|\n"
                f"| 上涨家数 | {overview.up_count} |\n"
                f"| 下跌家数 | {overview.down_count} |\n"
                f"| 非ST涨停 | {overview.non_st_limit_up_count} |\n"
                f"| 非ST跌停 | {overview.non_st_limit_down_count} |\n"
                f"| 两市成交额 | {overview.total_amount:.0f}亿 |"
                f"{vol_line}{rf_line}{condition_line}\n"
            )

        # 板块表现（A 股有）
        sector_section = ""
        if self.profile.has_sector_rankings:
            # 板块涨停/跌停家数榜
            limit_up_rows = ""
            if overview.top_sectors_by_limit_up:
                rows = "\n".join(
                    f"| {rank} | {s['name']} | {s.get('limit_up_count', 0)} | {s['change_pct']:+.2f}% |"
                    for rank, s in enumerate(overview.top_sectors_by_limit_up, 1)
                )
                limit_up_rows = (
                    "\n\n#### 行业板块 TOP10（按涨停数量）\n"
                    "| 排名 | 板块 | 涨停数 | 涨跌幅 |\n|------|------|--------|--------|\n"
                    f"{rows}"
                )
            limit_down_rows = ""
            if overview.top_sectors_by_limit_down:
                rows = "\n".join(
                    f"| {rank} | {s['name']} | {s.get('limit_down_count', 0)} | {s['change_pct']:+.2f}% |"
                    for rank, s in enumerate(overview.top_sectors_by_limit_down, 1)
                )
                limit_down_rows = (
                    "\n\n#### 行业板块 TOP10（按跌停数量）\n"
                    "| 排名 | 板块 | 跌停数 | 涨跌幅 |\n|------|------|--------|--------|\n"
                    f"{rows}"
                )
            # 概念板块
            concept_up = ""
            if overview.top_concept_sectors:
                parts = [f"**{s['name']}**({s['change_pct']:+.2f}%)" for s in overview.top_concept_sectors[:10]]
                concept_up = f"- **近1日领涨概念 TOP10**: {' | '.join(parts)}"
            concept_down = ""
            if overview.bottom_concept_sectors:
                parts = [f"**{s['name']}**({s['change_pct']:+.2f}%)" for s in overview.bottom_concept_sectors[:10]]
                concept_down = f"- **近1日领跌概念 TOP10**: {' | '.join(parts)}"
            concept_limit = ""
            if overview.top_concept_by_limit_up:
                rows = "\n".join(
                    f"| {rank} | {s['name']} | {s.get('limit_up_count', 0)} | {s['change_pct']:+.2f}% |"
                    for rank, s in enumerate(overview.top_concept_by_limit_up, 1)
                )
                concept_limit = (
                    "\n\n#### 概念板块 TOP10（按涨停数量）\n"
                    "| 排名 | 概念 | 涨停数 | 涨跌幅 |\n|------|------|--------|--------|\n"
                    f"{rows}"
                )
            sector_section = (
                f"\n### 四、热点解读\n"
                f"📊 **近1日热点追踪（概念板块）**\n"
                f"{concept_up}\n{concept_down}"
                f"{limit_up_rows}{limit_down_rows}{concept_limit}\n"
            )

        market_label = "A股" if self.region == "cn" else ("港股" if self.region == "hk" else "美股")
        strategy_summary = self.strategy.to_markdown_block()

        # 市场环境一句话总结
        condition_summary = ""
        if overview.market_condition:
            buy_tag = "✅ **可以考虑买入**" if overview.can_buy else "❌ **建议观望/不买入**"
            condition_summary = (
                f"{overview.rise_fall_status}，成交额{overview.volume_status or '情况未知'}，"
                f"{overview.market_condition}，{buy_tag}。"
            )

        report = (
            f"## {overview.date} 大盘复盘\n\n"
            f"### 一、市场总结\n"
            f"今日{market_label}市场整体呈现**{market_mood}**态势。"
            f"{' ' + condition_summary if condition_summary else ''}"
            f"{' ' + hk_summary if hk_summary else ''}\n\n"
            f"### 二、主要指数\n{indices_text}"
            f"{stats_section}"
            f"{sector_section}"
            f"\n### 五、风险提示\n市场有风险，投资需谨慎。以上数据仅供参考，不构成投资建议。\n\n"
            f"{strategy_summary}\n\n"
            f"---\n*复盘时间: {datetime.now().strftime('%H:%M')}*\n"
        )
        return report

    def run_daily_review(self) -> str:
        """
        执行每日大盘复盘完整流程

        Returns:
            复盘报告文本
        """
        logger.info("========== 开始大盘复盘分析 ==========")

        overview = self.get_market_overview()
        news = self.search_market_news()
        report = self.generate_market_review(overview, news)

        # 将 overview 挂载到实例，供外部（如 market_review.py）持久化时读取
        self._last_overview = overview
        self._last_news = list(news or [])

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

    overview = analyzer.get_market_overview()
    print(f"\n=== 市场概览 ===")
    print(f"日期: {overview.date}")
    print(f"指数数量: {len(overview.indices)}")
    for idx in overview.indices:
        print(f"  {idx.name}: {idx.current:.2f} ({idx.change_pct:+.2f}%)")
    print(f"港股参考: {len(overview.hk_indices)} 个")
    print(f"上涨: {overview.up_count} | 下跌: {overview.down_count}")
    print(f"成交额: {overview.total_amount:.0f}亿 | 量能: {overview.volume_status}")
    print(f"市场环境: {overview.market_condition}")

    report = analyzer._generate_template_review(overview, [])
    print(f"\n=== 复盘报告 ===")
    print(report)
