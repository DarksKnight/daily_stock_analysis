# -*- coding: utf-8 -*-
"""
===================================
智能选股相关模型
===================================

职责：
1. 定义智能选股请求参数模型
2. 定义智能选股响应模型
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SmartSelectRequest(BaseModel):
    """智能选股请求参数"""

    keywords: str = Field(
        ...,
        description=(
            "自然语言选股条件，多个条件用 ; 或中文标点分隔。"
            "例：MA5MA10多头排列;非ST;市值大于100亿;领涨板块四天内领涨两次以上"
        ),
        examples=[
            "MA5MA10多头排列;非ST;市值大于100亿;领涨板块四天内领涨两次以上",
            "量比大于2，基本面优秀，非ST，换手率大于3%",
            "今日涨幅大于3%;换手率大于5%;市值50亿到300亿;MACD金叉",
        ],
    )
    market_type: str = Field(
        "stock",
        description="市场类型：stock（个股，默认）、bk（板块）、etf（ETF）",
        pattern="^(stock|bk|etf)$",
    )
    qgqp_b_id: Optional[str] = Field(
        None,
        description=(
            "东财用户标识（qgqp_b_id），可从浏览器访问东财网站时抓取 Cookie 获得。"
            "不填则使用服务器端配置或自动生成随机指纹。"
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "keywords": "MA5MA10多头排列;非ST;市值大于100亿;领涨板块四天内领涨两次以上",
                "market_type": "stock",
            }
        }
    }


class SmartSelectResponse(BaseModel):
    """智能选股响应"""

    keywords: str = Field(..., description="原始选股条件")
    market_type: str = Field(..., description="市场类型")
    total: int = Field(..., description="符合条件的总数量")
    columns: List[Dict[str, str]] = Field(
        default_factory=list,
        description="数据列说明列表，每项包含 key（英文字段名）和 title（中文显示标题）",
    )
    stocks: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="筛选出的股票/板块/ETF 列表，每项以原始英文 key 为字段名",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "keywords": "MA5MA10多头排列;非ST;市值大于100亿;领涨板块四天内领涨两次以上",
                "market_type": "stock",
                "total": 156,
                "columns": [
                    {"key": "f12", "title": "股票代码"},
                    {"key": "f14", "title": "股票名称"},
                    {"key": "f2", "title": "最新价(元)"},
                    {"key": "f3", "title": "涨跌幅(%)"},
                ],
                "stocks": [
                    {
                        "f12": "600519",
                        "f14": "贵州茅台",
                        "f2": "1800.00",
                        "f3": "1.23",
                    }
                ],
            }
        }
    }
