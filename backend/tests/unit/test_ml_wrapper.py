"""
运行已有 ML 测试的包装脚本。

已有 ML 测试（ml/tests/）使用简单的 run()+assert 模式，
此脚本提供向后兼容包装，使其能在 pytest 框架下运行。

文件：
    ml/tests/test_inference_contract.py     → test_ml_inference_contract
    ml/tests/test_feature_store.py          → test_ml_feature_store
    ml/tests/test_risk_distribution.py      → test_ml_risk_distribution
    ml/tests/test_point_in_time.py          → test_ml_point_in_time
    ml/tests/test_validation_metrics.py     → test_ml_validation_metrics
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ML_DIR = ROOT / "ml"
TESTS_DIR = ML_DIR / "tests"

# collect ML test modules
MODULES = [
    "test_inference_contract",
    "test_feature_store",
    "test_risk_distribution",
    "test_point_in_time",
    "test_validation_metrics",
]


@pytest.mark.ml
@pytest.mark.parametrize("module_name", MODULES)
def test_ml_module(module_name: str):
    """动态导入 ML 测试模块并执行其 run() 函数。"""
    if str(TESTS_DIR) not in sys.path:
        sys.path.insert(0, str(TESTS_DIR))
    mod = importlib.import_module(module_name)
    assert hasattr(mod, "run"), f"{module_name} 缺少 run() 函数"
    # 调用 run()，出错时会抛出异常
    mod.run()
