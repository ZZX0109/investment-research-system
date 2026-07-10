"""
共享 fixtures：FastAPI TestClient + 内存 SQLite 数据库。

用法：将项目根目录加入 PYTHONPATH 后运行：
    cd /path/to/investment-research-system
    python -m pytest backend/tests/ -v
"""

from __future__ import annotations

import sqlite3
import os
import sys
from contextlib import closing
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# 用环境变量强制使用内存数据库
os.environ["INVESTMENT_RESEARCH_TEST_MODE"] = "1"


@pytest.fixture(scope="session")
def project_root() -> Path:
    return ROOT


@pytest.fixture(scope="function")
def test_db_path(tmp_path: Path) -> str:
    """每次测试使用独立的临时 SQLite 文件，确保测试隔离。"""
    db_file = tmp_path / "test_investment_research.sqlite3"
    return str(db_file)


@pytest.fixture(scope="function")
def app(test_db_path: str) -> Generator:
    """创建 FastAPI app 实例，注入测试数据库。"""
    import backend.app as app_module

    original_db = app_module.DB_PATH
    app_module.DB_PATH = Path(test_db_path)
    app_module.init_db()
    yield app_module.app
    app_module.DB_PATH = original_db


@pytest.fixture(scope="function")
def client(app) -> Generator[TestClient, None, None]:
    """返回 TestClient。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def db_conn(test_db_path: str):
    """直接读写测试数据库的 sqlite3 连接。"""
    import backend.app as app_module

    original_db = app_module.DB_PATH
    app_module.DB_PATH = Path(test_db_path)
    app_module.init_db()
    with closing(sqlite3.connect(test_db_path)) as conn:
        conn.row_factory = sqlite3.Row
        yield conn
    app_module.DB_PATH = original_db


@pytest.fixture(scope="function")
def auth_headers(client) -> dict[str, str]:
    """注册 + 登录一个测试用户，返回 Authorization header。"""
    resp = client.post(
        "/api/auth/register",
        json={"email": "tester@example.com", "password": "Test!2345"},
    )
    if resp.status_code != 200 and resp.status_code != 201:
        # 可能已有用户，尝试登录
        resp2 = client.post(
            "/api/auth/login",
            json={"email": "tester@example.com", "password": "Test!2345"},
        )
        token = resp2.json()["token"]
    else:
        token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def onboarded_user(client, auth_headers) -> dict[str, str]:
    """完成 onboarding 的用户，带持仓。"""
    client.post(
        "/api/onboarding",
        json={
            "preference": "balanced",
            "riskAnswers": {"maxDrawdown": "20%", "horizon": "1y"},
            "holdings": [
                {"symbol": "NVDA", "name": "NVIDIA", "market": "us", "sector": "AI 算力",
                 "shares": 50, "costPrice": 800.0},
                {"symbol": "TSLA", "name": "Tesla", "market": "us", "sector": "电动车",
                 "shares": 80, "costPrice": 240.0},
            ],
        },
        headers=auth_headers,
    )
    return auth_headers
