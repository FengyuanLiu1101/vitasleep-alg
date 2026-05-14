"""
可调参数清单，供校准 Agent 与服务运行时读取、更新。

所有对外可调的标量、权重区间均集中在此定义；运行时可通过 main 的
``POST /params/update`` 覆盖内存中的副本，无需改代码。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# 各权重之和必须为 1；range 为单次校准/优化时允许的单项边界。
TUNABLE_PARAMS: dict[str, Any] = {
    "weights": {
        "sleep": {"value": 0.40, "range": [0.25, 0.55]},
        "hrv": {"value": 0.30, "range": [0.15, 0.45]},
        "spo2": {"value": 0.15, "range": [0.05, 0.25]},
        "activity": {"value": 0.15, "range": [0.05, 0.25]},
    },
    "decay_rate": {"value": 0.02, "range": [0.01, 0.04]},
    "baseline_window_days": {"value": 7, "range": [3, 14]},
}


def clone_tunable_params() -> dict[str, Any]:
    """
    返回 ``TUNABLE_PARAMS`` 的深拷贝，便于服务在内存中安全修改。

    Returns:
        dict: 与 ``TUNABLE_PARAMS`` 结构相同的嵌套字典副本。
    """
    return deepcopy(TUNABLE_PARAMS)
