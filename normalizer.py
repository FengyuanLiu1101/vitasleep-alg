"""
指标归一化：将相对个人（或混合）基线的 z-score 映射为 0~100 分。

- 默认双侧惩罚：偏离基线越多分数越低。
- 血氧 ``spo2`` 等支持单侧惩罚：仅当低于基线时扣分，高于或等于基线视为满分方向不额外加分失控。
"""

from __future__ import annotations

import math
from typing import Final

# 避免除零
_MIN_STD: Final[float] = 1e-6


def normalize(
    value: float,
    mean: float,
    std: float,
    *,
    one_sided_low: bool = False,
    penalty_per_z: float = 12.0,
) -> float:
    """
    将单指标值按 z-score 转为 0~100 分。

    映射思想：在基线处接近 100 分；|z| 增大时线性扣分并钳位到 [0, 100]。
    单侧模式下仅当 ``value < mean`` 时使用 |z| 扣分（适用于 SpO2 过低有害、
    适度偏高一般不额外惩罚的业务假设）。

    Args:
        value: 当前观测值。
        mean: 基线均值（可能为人群兜底或与个人混合）。
        std: 基线标准差（过小会按内部下限夹紧）。
        one_sided_low: 为 True 时仅在低于基线时扣分。
        penalty_per_z: 每 1 个 z 单位扣除的分数。

    Returns:
        float: 区间 [0, 100] 内的得分。
    """
    sigma = float(std)
    if not math.isfinite(sigma) or sigma < _MIN_STD:
        sigma = _MIN_STD

    z = (float(value) - float(mean)) / sigma

    if one_sided_low:
        # SpO2：仅过低扣分
        if value >= mean:
            z_mag = 0.0
        else:
            z_mag = abs(z)
    else:
        z_mag = abs(z)

    raw = 100.0 - penalty_per_z * z_mag
    return float(max(0.0, min(100.0, raw)))
