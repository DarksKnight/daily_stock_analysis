# -*- coding: utf-8 -*-
"""API tests for reading today's persisted market review."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.storage import DatabaseManager


@pytest.fixture(autouse=True)
def disable_auth():
    auth._auth_enabled = None
    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("src.auth.is_auth_enabled", return_value=False):
        yield
    auth._auth_enabled = None


@pytest.fixture
def client():
    temp_dir = tempfile.TemporaryDirectory()
    data_dir = Path(temp_dir.name)
    db_path = data_dir / "market_review_api.db"
    env_path = data_dir / ".env"
    env_path.write_text(
        "\n".join(
            [
                "ADMIN_AUTH_ENABLED=false",
                f"DATABASE_PATH={db_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    os.environ["ENV_FILE"] = str(env_path)
    os.environ["DATABASE_PATH"] = str(db_path)
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    app = create_app(static_dir=data_dir / "empty-static")

    try:
        yield TestClient(app), db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        temp_dir.cleanup()


def test_get_today_market_review_returns_latest_same_day_record(client):
    client_obj, db = client
    db.replace_market_review_history_for_date(
        date.today(),
        [
            {
                "region": "cn",
                "report_markdown": "# 今日A股复盘",
                "overview_json": "{}",
                "news_json": "[]",
            }
        ],
    )

    response = client_obj.get("/api/v1/market-review/today", params={"region": "cn"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["region"] == "cn"
    assert payload["report"] == "# 今日A股复盘"
    assert payload["trade_date"] == date.today().isoformat()
    assert payload["created_at"] is not None


def test_get_today_market_review_returns_null_report_when_missing(client):
    client_obj, _db = client

    response = client_obj.get("/api/v1/market-review/today", params={"region": "hk"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["region"] == "hk"
    assert payload["report"] is None
    assert payload["trade_date"] is None
    assert payload["created_at"] is None
