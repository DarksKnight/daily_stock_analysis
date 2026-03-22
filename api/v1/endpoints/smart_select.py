# -*- coding: utf-8 -*-
"""
===================================
智能选股接口
===================================

职责：
1. POST /api/v1/smart-select/stocks  - 按自然语言条件筛选 A 股个股
2. POST /api/v1/smart-select/bk      - 按自然语言条件筛选板块
3. POST /api/v1/smart-select/etf     - 按自然语言条件筛选 ETF

特性：
- 传入自然语言选股条件（如 "MA5MA10多头排列;非ST;市值大于100亿"）
- 对接东方财富 smart-tag 接口进行实时筛选
- 返回带有字段标题的股票列表
"""

import logging
from typing import Union

from fastapi import APIRouter, HTTPException

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.smart_select import SmartSelectRequest, SmartSelectResponse
from src.config import get_config
from src.services.smart_stock_service import SmartStockService

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_service(qgqp_b_id_override: Union[str, None]) -> SmartStockService:
    """
    构建 SmartStockService 实例。

    优先级：
    1. 请求体中显式传入的 qgqp_b_id
    2. 环境变量 EASTMONEY_QGQP_B_ID
    3. 自动生成随机指纹
    """
    cfg = get_config()
    qgqp_b_id = qgqp_b_id_override or cfg.eastmoney_qgqp_b_id or None
    return SmartStockService(qgqp_b_id=qgqp_b_id)


@router.post(
    "/stocks",
    response_model=SmartSelectResponse,
    responses={
        200: {"description": "筛选成功，返回股票列表"},
        400: {"description": "选股条件为空或参数错误", "model": ErrorResponse},
        502: {"description": "东财接口调用失败", "model": ErrorResponse},
    },
    summary="智能选股（个股）",
    description=(
        "传入自然语言选股条件，调用东方财富选股接口，返回符合条件的 A 股个股列表。\n\n"
        "**条件示例**：\n"
        "- `MA5MA10多头排列;非ST;市值大于100亿;领涨板块四天内领涨两次以上`\n"
        "- `量比大于2，换手率大于3%，非ST，非创业板`\n"
        "- `今日涨幅大于3%;MACD金叉;市值50亿到300亿`\n\n"
        "多个条件可用 `;` 或 `,` 或中文标点分隔。"
    ),
)
def smart_select_stocks(request: SmartSelectRequest) -> SmartSelectResponse:
    """按自然语言条件筛选 A 股个股。"""
    return _do_select(request, market_type="stock")


@router.post(
    "/bk",
    response_model=SmartSelectResponse,
    responses={
        200: {"description": "筛选成功，返回板块列表"},
        400: {"description": "选股条件为空或参数错误", "model": ErrorResponse},
        502: {"description": "东财接口调用失败", "model": ErrorResponse},
    },
    summary="智能选股（板块）",
    description="传入自然语言条件，筛选符合条件的板块/概念。\n\n**条件示例**：`今日涨幅前5的概念板块`",
)
def smart_select_bk(request: SmartSelectRequest) -> SmartSelectResponse:
    """按自然语言条件筛选板块。"""
    return _do_select(request, market_type="bk")


@router.post(
    "/etf",
    response_model=SmartSelectResponse,
    responses={
        200: {"description": "筛选成功，返回 ETF 列表"},
        400: {"description": "选股条件为空或参数错误", "model": ErrorResponse},
        502: {"description": "东财接口调用失败", "model": ErrorResponse},
    },
    summary="智能选股（ETF）",
    description="传入自然语言条件，筛选符合条件的 ETF。\n\n**条件示例**：`今日涨幅前15的ETF`",
)
def smart_select_etf(request: SmartSelectRequest) -> SmartSelectResponse:
    """按自然语言条件筛选 ETF。"""
    return _do_select(request, market_type="etf")


# ------------------------------------------------------------------
# 通用处理逻辑
# ------------------------------------------------------------------


def _do_select(request: SmartSelectRequest, market_type: str) -> SmartSelectResponse:
    """统一选股处理逻辑。"""
    keywords = (request.keywords or "").strip()
    if not keywords:
        raise HTTPException(
            status_code=400,
            detail={"error": "validation_error", "message": "keywords 不能为空"},
        )

    service = _get_service(request.qgqp_b_id)

    try:
        if market_type == "stock":
            result = service.search_stock(keywords)
        elif market_type == "bk":
            result = service.search_bk(keywords)
        else:  # etf
            result = service.search_etf(keywords)
    except ValueError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "upstream_error", "message": str(e)},
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "request_failed", "message": str(e)},
        )

    return SmartSelectResponse(
        keywords=keywords,
        market_type=market_type,
        total=result["total"],
        columns=result["columns"],
        stocks=result["stocks"],
    )
