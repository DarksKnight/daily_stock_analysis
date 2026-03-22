# -*- coding: utf-8 -*-
"""
===================================
大盘复盘接口
===================================

职责：
1. POST /api/v1/market-review/run  - 触发大盘复盘分析（异步任务）
2. GET  /api/v1/market-review/status/{task_id} - 查询任务状态与报告结果
"""

import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.market_review import (
    MarketReviewRunRequest,
    MarketReviewStatusResponse,
    MarketReviewTaskAccepted,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# 简易内存任务存储（进程内有效，重启后清空）
# ---------------------------------------------------------------------------

_tasks: Dict[str, Dict[str, Any]] = {}
_tasks_lock = threading.Lock()


def _run_market_review_task(task_id: str, region: str) -> None:
    """在后台线程中执行大盘复盘，将结果写回 _tasks。"""
    with _tasks_lock:
        _tasks[task_id]["status"] = "processing"

    try:
        from src.config import get_config
        from src.core.market_review import run_market_review
        from src.notification import NotificationService

        config = get_config()

        notifier = NotificationService()

        # 搜索服务（可选）
        search_service = None
        if config.has_search_capability_enabled():
            from src.search_service import SearchService

            search_service = SearchService(
                bocha_keys=config.bocha_api_keys,
                tavily_keys=config.tavily_api_keys,
                brave_keys=config.brave_api_keys,
                serpapi_keys=config.serpapi_keys,
                minimax_keys=config.minimax_api_keys,
                searxng_base_urls=config.searxng_base_urls,
                searxng_public_instances_enabled=config.searxng_public_instances_enabled,
                news_max_age_days=config.news_max_age_days,
                news_strategy_profile=getattr(config, "news_strategy_profile", "short"),
            )

        # AI 分析器（可选）
        analyzer = None
        if config.gemini_api_key or config.openai_api_key:
            from src.analyzer import GeminiAnalyzer

            analyzer = GeminiAnalyzer(api_key=config.gemini_api_key)
            if not analyzer.is_available():
                logger.warning("[market-review API] AI 分析器不可用，将使用模板生成")
                analyzer = None

        report = run_market_review(
            notifier=notifier,
            analyzer=analyzer,
            search_service=search_service,
            send_notification=False,  # API 触发时不发送通知，避免重复推送
            override_region=region,
        )

        with _tasks_lock:
            _tasks[task_id]["status"] = "completed"
            _tasks[task_id]["report"] = report or ""
            _tasks[task_id]["completed_at"] = datetime.now().isoformat()

    except Exception as exc:
        logger.error("[market-review API] 任务 %s 失败: %s", task_id, exc, exc_info=True)
        with _tasks_lock:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["error"] = str(exc)
            _tasks[task_id]["completed_at"] = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=MarketReviewTaskAccepted,
    status_code=202,
    responses={
        202: {"description": "任务已提交，异步执行中"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="触发大盘复盘分析",
    description=(
        "提交大盘复盘分析任务，立即返回 task_id。\n\n"
        "通过 `GET /api/v1/market-review/status/{task_id}` 轮询进度，"
        "待 `status` 变为 `completed` 时，响应体中包含 `report`（Markdown 格式）。"
    ),
)
def run_market_review_api(request: MarketReviewRunRequest) -> MarketReviewTaskAccepted:
    """提交大盘复盘分析任务。"""
    task_id = uuid.uuid4().hex
    created_at = datetime.now().isoformat()

    with _tasks_lock:
        _tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "region": request.region,
            "report": None,
            "error": None,
            "created_at": created_at,
            "completed_at": None,
        }

    thread = threading.Thread(
        target=_run_market_review_task,
        args=(task_id, request.region),
        daemon=True,
    )
    thread.start()

    return MarketReviewTaskAccepted(
        task_id=task_id,
        status="pending",
        region=request.region,
        created_at=created_at,
    )


@router.get(
    "/status/{task_id}",
    response_model=MarketReviewStatusResponse,
    responses={
        200: {"description": "任务状态与报告内容"},
        404: {"description": "任务不存在", "model": ErrorResponse},
    },
    summary="查询大盘复盘任务状态",
    description=(
        "轮询大盘复盘任务状态。\n\n"
        "- `pending` / `processing`：仍在执行中，继续轮询\n"
        "- `completed`：已完成，`report` 字段含 Markdown 报告\n"
        "- `failed`：执行失败，`error` 字段含错误信息"
    ),
)
def get_market_review_status(task_id: str) -> MarketReviewStatusResponse:
    """查询大盘复盘任务状态与报告结果。"""
    with _tasks_lock:
        task = _tasks.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": "任务不存在或已过期"},
        )

    return MarketReviewStatusResponse(**task)
