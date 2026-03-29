# -*- coding: utf-8 -*-
"""
===================================
大盘复盘接口 Schema
===================================
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

RegionType = Literal["cn", "hk", "us", "both", "all"]
TodayRegionType = Literal["cn", "hk"]


class MarketReviewRunRequest(BaseModel):
    region: RegionType = Field("cn", description="市场区域: cn=A股, hk=港股, us=美股, both=A股+美股, all=全部")


class MarketReviewTaskAccepted(BaseModel):
    task_id: str
    status: str = "pending"
    region: str
    created_at: str


class MarketReviewStatusResponse(BaseModel):
    task_id: str
    status: str  # pending / processing / completed / failed
    region: str
    report: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class MarketReviewTodayResponse(BaseModel):
    region: TodayRegionType
    trade_date: Optional[str] = None
    report: Optional[str] = None
    created_at: Optional[str] = None
