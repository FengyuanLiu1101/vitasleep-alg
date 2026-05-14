"""
模拟测试数据：多场景期望值 + 7 日基线历史，用于单测 / 演示 / 权重校准。

所有数值为演示用途，不代表医学结论。
"""

from __future__ import annotations

import random
from copy import deepcopy
from typing import Any

from baseline import POPULATION_MEAN, BaselineModel, METRIC_KEYS

# ---------------------------------------------------------------------------
# 至少 10 组典型场景（含用户基线建立所需的 user_id）
# expected_battery 取区间中点，供 optimizer 回归；演示时可对比 [low, high]。
# ---------------------------------------------------------------------------
MOCK_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "good_sleep_high_hrv",
        "label": "睡眠好、HRV 高",
        "user_id": "u_good_hrv",
        "expected_range": (85, 95),
        "hours_since_last_sleep": 8.0,
        "metrics": {
            "resting_hr": 52,
            "hrv_rmssd": 65,
            "spo2": 98,
            "deep_sleep_ratio": 0.30,
            "active_minutes": 42,
        },
    },
    {
        "id": "late_night_low_hrv",
        "label": "熬夜、HRV 低",
        "user_id": "u_late_low",
        "expected_range": (20, 35),
        "hours_since_last_sleep": 4.0,
        "metrics": {
            "resting_hr": 78,
            "hrv_rmssd": 18,
            "spo2": 95,
            "deep_sleep_ratio": 0.08,
            "active_minutes": 20,
        },
    },
    {
        "id": "overtraining_fatigue",
        "label": "运动过度疲劳",
        "user_id": "u_overtrain",
        "expected_range": (40, 55),
        "hours_since_last_sleep": 10.0,
        "metrics": {
            "resting_hr": 72,
            "hrv_rmssd": 28,
            "spo2": 96,
            "deep_sleep_ratio": 0.12,
            "active_minutes": 95,
        },
    },
    {
        "id": "normal_day",
        "label": "正常状态",
        "user_id": "u_normal",
        "expected_range": (60, 75),
        "hours_since_last_sleep": 9.0,
        "metrics": {
            "resting_hr": 62,
            "hrv_rmssd": 40,
            "spo2": 97,
            "deep_sleep_ratio": 0.21,
            "active_minutes": 40,
        },
    },
    {
        "id": "cold_start_population",
        "label": "新用户冷启动（无基线数据）",
        "user_id": "u_cold",
        "expected_range": (58, 72),
        "hours_since_last_sleep": 8.0,
        "metrics": {
            "resting_hr": 63,
            "hrv_rmssd": 41,
            "spo2": 97,
            "deep_sleep_ratio": 0.20,
            "active_minutes": 36,
        },
    },
    {
        "id": "mild_sleep_debt",
        "label": "轻度睡眠负债",
        "user_id": "u_sleep_debt",
        "expected_range": (45, 58),
        "hours_since_last_sleep": 11.0,
        "metrics": {
            "resting_hr": 66,
            "hrv_rmssd": 34,
            "spo2": 96.5,
            "deep_sleep_ratio": 0.15,
            "active_minutes": 52,
        },
    },
    {
        "id": "hypoxia_suspect",
        "label": "血氧偏低",
        "user_id": "u_low_spo2",
        "expected_range": (35, 50),
        "hours_since_last_sleep": 7.5,
        "metrics": {
            "resting_hr": 64,
            "hrv_rmssd": 36,
            "spo2": 92,
            "deep_sleep_ratio": 0.18,
            "active_minutes": 30,
        },
    },
    {
        "id": "sedentary_recovery",
        "label": "久坐、活动不足",
        "user_id": "u_sedentary",
        "expected_range": (50, 62),
        "hours_since_last_sleep": 14.0,
        "metrics": {
            "resting_hr": 60,
            "hrv_rmssd": 45,
            "spo2": 97,
            "deep_sleep_ratio": 0.20,
            "active_minutes": 8,
        },
    },
    {
        "id": "shift_work",
        "label": "轮班后节律紊乱",
        "user_id": "u_shift",
        "expected_range": (38, 52),
        "hours_since_last_sleep": 6.0,
        "metrics": {
            "resting_hr": 74,
            "hrv_rmssd": 24,
            "spo2": 96,
            "deep_sleep_ratio": 0.11,
            "active_minutes": 48,
        },
    },
    {
        "id": "elite_recovery",
        "label": "精英运动员恢复日",
        "user_id": "u_elite",
        "expected_range": (78, 88),
        "hours_since_last_sleep": 10.0,
        "metrics": {
            "resting_hr": 48,
            "hrv_rmssd": 72,
            "spo2": 98,
            "deep_sleep_ratio": 0.28,
            "active_minutes": 55,
        },
    },
    {
        "id": "partial_missing_metrics",
        "label": "部分指标缺失（演示兜底）",
        "user_id": "u_partial",
        "expected_range": (55, 70),
        "hours_since_last_sleep": 9.0,
        "metrics": {
            "resting_hr": None,
            "hrv_rmssd": 39,
            "spo2": 97,
            "deep_sleep_ratio": 0.19,
            "active_minutes": None,
        },
    },
]


def scenario_to_test_case(scenario: dict[str, Any]) -> dict[str, Any]:
    """
    将演示场景转为 ``optimizer.optimize_weights`` 需要的监督样本。

    Args:
        scenario: ``MOCK_SCENARIOS`` 中的元素。

    Returns:
        dict: 含 ``user_id, metrics, hours_since_last_sleep, expected_battery``。
    """
    lo, hi = scenario["expected_range"]
    return {
        "user_id": scenario["user_id"],
        "metrics": deepcopy(scenario["metrics"]),
        "hours_since_last_sleep": float(scenario["hours_since_last_sleep"]),
        "expected_battery": float(lo + hi) / 2.0,
    }


def build_optimizer_cases() -> list[dict[str, Any]]:
    """
    由全部内置场景生成优化用测试用例列表。

    Returns:
        list[dict]: 监督样本序列。
    """
    return [scenario_to_test_case(s) for s in MOCK_SCENARIOS]


def generate_7_day_history(
    user_id: str,
    *,
    scenario_bias: dict[str, float] | None = None,
    noise_scale: float = 0.03,
    seed: int | None = 42,
) -> list[dict[str, Any]]:
    """
    生成连续 7 天的模拟日级指标，用于基线建模单元测试或服务演示。

    默认以人群均值为中心，可加 ``scenario_bias`` 模拟「好睡用户 / 熬夜用户」等偏移。

    Args:
        user_id: 写入基线模型时使用的 ID（此处仅返回 records，不直接写入）。
        scenario_bias: 各 METRIC_KEY 的乘性或加性微调这里简化为**加性偏移**。
        noise_scale: 相对随机扰动强度。
        seed: 随机种子；``None`` 则非确定。

    Returns:
        list[dict]: 7 条日记录，字段与 ``BaselineModel.update`` 兼容。
    """
    if seed is not None:
        random.seed(seed)
    bias = scenario_bias or {}
    rows: list[dict[str, Any]] = []
    for day in range(7):
        row: dict[str, Any] = {"day_index": day}
        for k in METRIC_KEYS:
            base = float(POPULATION_MEAN[k])
            delta = float(bias.get(k, 0.0))
            noisy = base + delta
            noisy *= 1.0 + random.uniform(-noise_scale, noise_scale)
            # 边界夹紧，避免不合理样本
            if k == "deep_sleep_ratio":
                noisy = max(0.05, min(0.45, noisy))
            elif k == "spo2":
                noisy = max(88.0, min(100.0, noisy))
            elif k == "active_minutes":
                noisy = max(0.0, min(180.0, noisy))
            elif k == "resting_hr":
                noisy = max(40.0, min(100.0, noisy))
            elif k == "hrv_rmssd":
                noisy = max(8.0, min(120.0, noisy))
            row[k] = noisy
        rows.append(row)
    return rows


def seed_baseline_for_mock_users(model: Any) -> None:
    """
    将 ``MOCK_SCENARIOS`` 涉及的 user_id 批量灌入 7 日历史，便于端到端示例。

    Args:
        model: ``BaselineModel`` 实例。
    """
    if not isinstance(model, BaselineModel):
        raise TypeError("model must be BaselineModel")

    preset_biases: dict[str, dict[str, float]] = {
        "u_good_hrv": {"hrv_rmssd": 12, "deep_sleep_ratio": 0.04, "resting_hr": -6},
        "u_late_low": {"hrv_rmssd": -18, "deep_sleep_ratio": -0.08, "resting_hr": 10},
        "u_overtrain": {"active_minutes": 35, "hrv_rmssd": -10, "deep_sleep_ratio": -0.06},
        "u_normal": {},
        "u_cold": {},
        "u_sleep_debt": {"deep_sleep_ratio": -0.05, "hrv_rmssd": -6},
        "u_low_spo2": {"spo2": -4},
        "u_sedentary": {"active_minutes": -22},
        "u_shift": {"deep_sleep_ratio": -0.07, "hrv_rmssd": -12, "resting_hr": 8},
        "u_elite": {"hrv_rmssd": 22, "deep_sleep_ratio": 0.05, "resting_hr": -10},
        "u_partial": {},
    }

    # 明确保留「冷启动」演示账号，不写入任何历史
    skip_users = {"u_cold"}

    seen: set[str] = set()
    for s in MOCK_SCENARIOS:
        uid = str(s["user_id"])
        if uid in skip_users:
            continue
        if uid in seen:
            continue
        seen.add(uid)
        bias = preset_biases.get(uid, {})
        records = generate_7_day_history(uid, scenario_bias=bias, seed=hash(uid) % (2**31))
        model.update({"user_id": uid, "records": records})
