# -*- coding: utf-8 -*-
"""
===================================
智能选股服务层
===================================

职责：
1. 对接东方财富"选股"接口（smart-tag）
2. 接收自然语言选股条件，返回结构化股票列表
"""

import logging
import random
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# 东财选股 API 地址映射
_EASTMONEY_SEARCH_URLS: Dict[str, str] = {
    "stock": "https://np-tjxg-g.eastmoney.com/api/smart-tag/stock/v3/pw/search-code",
    "bk": "https://np-tjxg-b.eastmoney.com/api/smart-tag/bkc/v3/pw/search-code",
    "etf": "https://np-tjxg-b.eastmoney.com/api/smart-tag/etf/v3/pw/search-code",
}

_DEFAULT_HEADERS = {
    "Origin": "https://xuangu.eastmoney.com",
    "Referer": "https://xuangu.eastmoney.com/",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:145.0) " "Gecko/20100101 Firefox/145.0"),
    "Content-Type": "application/json",
}


def _random_fingerprint() -> str:
    """生成随机 20 位数字指纹。首位 1-9，后 19 位 0-9。"""
    first = str(random.randint(1, 9))
    rest = "".join(str(random.randint(0, 9)) for _ in range(19))
    return first + rest


class SmartStockService:
    """
    智能选股服务

    使用东方财富自然语言选股接口，根据用户输入的自然语言条件筛选股票。

    示例条件：
    - "MA5MA10多头排列;非ST;市值大于100亿"
    - "量比大于2，非ST，换手率大于3%"
    - "今日涨幅前15的ETF"
    """

    def __init__(self, qgqp_b_id: Optional[str] = None, timeout: int = 30):
        """
        初始化智能选股服务

        Args:
            qgqp_b_id: 东财用户标识，可从浏览器 Cookie 中获取。
                       不提供时自动生成随机指纹（大多数情况下可用）。
            timeout:   HTTP 请求超时秒数，默认 30。
        """
        self._fingerprint = qgqp_b_id or _random_fingerprint()
        self._timeout = timeout

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def search_stock(self, keywords: str, page_size: int = 50) -> Dict[str, Any]:
        """
        按自然语言条件筛选 A 股个股。

        Args:
            keywords:  自然语言选股条件，例如 "MA5MA10多头排列;非ST;市值大于100亿"
            page_size: 内部请求条数，默认 50

        Returns:
            解析后的字典：
            {
                "total":   int,
                "columns": [{"key": ..., "title": ...}],
                "stocks":  [{"f12": "600519", ...}]
            }
        """
        return self._search(_EASTMONEY_SEARCH_URLS["stock"], keywords, page_size)

    def search_bk(self, keywords: str, page_size: int = 50) -> Dict[str, Any]:
        """按自然语言条件筛选板块。"""
        return self._search(_EASTMONEY_SEARCH_URLS["bk"], keywords, page_size)

    def search_etf(self, keywords: str, page_size: int = 50) -> Dict[str, Any]:
        """按自然语言条件筛选 ETF。"""
        return self._search(_EASTMONEY_SEARCH_URLS["etf"], keywords, page_size)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _search(self, url: str, keywords: str, page_size: int) -> Dict[str, Any]:
        """调用东财选股 API 并解析响应。"""
        payload = {
            "keyWord": keywords,
            "pageSize": page_size,
            "pageNo": 1,
            "fingerprint": self._fingerprint,
            "gids": [],
            "matchWord": "",
            "timestamp": str(int(time.time())),
            "shareToGuba": False,
            "requestId": "",
            "needCorrect": True,
            "removedConditionIdList": [],
            "xcId": "",
            "ownSelectAll": False,
            "dxInfo": [],
            "extraCondition": "",
        }

        headers = {**_DEFAULT_HEADERS, "Cookie": f"qgqp_b_id={self._fingerprint}"}

        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"东财选股 API 请求失败: {e}")
            raise RuntimeError(f"请求东财选股接口失败: {e}") from e

        raw: Dict[str, Any] = resp.json()
        logger.debug(f"东财选股 API 原始响应 code={raw.get('code')}")

        return self._parse_response(raw)

    def _parse_response(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析东财选股 API 响应，提取列头和数据行。

        原始响应结构：
        {
            "code": 100,
            "data": {
                "result": {
                    "columns": [{"key": ..., "title": ..., "dateMsg": ..., "unit": ...}],
                    "dataList": [{...}, ...],
                    "count": int
                }
            }
        }
        """
        code = str(raw.get("code"))
        msg = str(raw.get("msg") or raw.get("message") or "未知错误")
        if code not in {"100", "201"}:
            logger.warning(f"东财选股 API 返回非成功 code={code} msg={msg}")
            raise ValueError(f"东财选股接口返回错误（code={code}）：{msg}")

        if code == "201":
            logger.info(f"东财选股未命中结果，返回空列表: {msg}")

        data = raw.get("data") or {}
        result = data.get("result") or {}
        columns: List[Any] = result.get("columns") or []
        data_list: List[Any] = result.get("dataList") or []
        total: int = result.get("count", result.get("total", len(data_list)))

        # 构建列说明列表，同时收集所有有效 key
        col_info: List[Dict[str, str]] = []
        keys: List[str] = []
        for col in columns:
            key: str = col.get("key", "")
            if not key:
                continue
            title: str = str(col.get("title", key))
            date_msg: str = col.get("dateMsg", "")
            unit: str = col.get("unit", "")
            if date_msg:
                title = f"{title}[{date_msg}]"
            if unit:
                title = f"{title}({unit})"
            col_info.append({"key": key, "title": title})
            keys.append(key)

        # 将 dataList 转换为以原始英文 key 作为字典键的列表
        stocks: List[Dict[str, str]] = []
        for item in data_list:
            row: Dict[str, str] = {k: str(item.get(k, "")) for k in keys}
            stocks.append(row)

        return {
            "total": total,
            "columns": col_info,
            "stocks": stocks,
        }
