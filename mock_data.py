"""
模拟测试数据：多场景期望值 + 7 日基线历史，用于单测 / 演示 / 权重校准。

所有数值为演示用途，不代表医学结论。
睡眠字段已迁移至 Health Connect 分期格式（分钟数）。
"""

from __future__ import annotations

import random
from copy import deepcopy
from typing import Any

from baseline import POPULATION_MEAN, BaselineModel, METRIC_KEYS

# ---------------------------------------------------------------------------
# 典型场景（指标已对齐 Health Connect 字段）
# expected_battery 取区间中点，供 optimizer 回归。
# ---------------------------------------------------------------------------
MOCK_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "good_sleep_high_hrv",
        "label": "睡眠好、HRV 高",
        "user_id": "u_good_hrv",
        "expected_range": (85, 95),
        "hours_since_last_sleep": 8.0,
        "metrics": {
            "resting_hr": 52, "hrv_rmssd": 65, "hrv_sdnn": 82,
            "systolic": 112, "diastolic": 72,
            "spo2": 98,
            "deep_sleep_minutes": 120, "light_sleep_minutes": 195,
            "rem_sleep_minutes": 105, "awake_minutes": 15,
            "steps": 9500, "active_calories": 380, "active_minutes": 42,
        },
    },
    {
        "id": "late_night_low_hrv",
        "label": "熬夜、HRV 低",
        "user_id": "u_late_low",
        "expected_range": (20, 35),
        "hours_since_last_sleep": 4.0,
        "metrics": {
            "resting_hr": 78, "hrv_rmssd": 18, "hrv_sdnn": 24,
            "systolic": 128, "diastolic": 82,
            "spo2": 95,
            "deep_sleep_minutes": 35, "light_sleep_minutes": 155,
            "rem_sleep_minutes": 50, "awake_minutes": 60,
            "steps": 4200, "active_calories": 180, "active_minutes": 20,
        },
    },
    {
        "id": "overtraining_fatigue",
        "label": "运动过度疲劳",
        "user_id": "u_overtrain",
        "expected_range": (40, 55),
        "hours_since_last_sleep": 10.0,
        "metrics": {
            "resting_hr": 72, "hrv_rmssd": 28, "hrv_sdnn": 38,
            "systolic": 122, "diastolic": 78,
            "spo2": 96,
            "deep_sleep_minutes": 55, "light_sleep_minutes": 185,
            "rem_sleep_minutes": 80, "awake_minutes": 30,
            "steps": 14000, "active_calories": 680, "active_minutes": 95,
        },
    },
    {
        "id": "normal_day",
        "label": "正常状态",
        "user_id": "u_normal",
        "expected_range": (60, 75),
        "hours_since_last_sleep": 9.0,
        "metrics": {
            "resting_hr": 62, "hrv_rmssd": 40, "hrv_sdnn": 52,
            "systolic": 118, "diastolic": 76,
            "spo2": 97,
            "deep_sleep_minutes": 88, "light_sleep_minutes": 198,
            "rem_sleep_minutes": 98, "awake_minutes": 22,
            "steps": 8200, "active_calories": 340, "active_minutes": 40,
        },
    },
    {
        "id": "cold_start_population",
        "label": "新用户冷启动（无基线数据）",
        "user_id": "u_cold",
        "expected_range": (58, 72),
        "hours_since_last_sleep": 8.0,
        "metrics": {
            "resting_hr": 63, "hrv_rmssd": 41, "hrv_sdnn": 54,
            "systolic": 119, "diastolic": 77,
            "spo2": 97,
            "deep_sleep_minutes": 86, "light_sleep_minutes": 196,
            "rem_sleep_minutes": 96, "awake_minutes": 22,
            "steps": 7800, "active_calories": 330, "active_minutes": 36,
        },
    },
    {
        "id": "mild_sleep_debt",
        "label": "轻度睡眠负债",
        "user_id": "u_sleep_debt",
        "expected_range": (45, 58),
        "hours_since_last_sleep": 11.0,
        "metrics": {
            "resting_hr": 66, "hrv_rmssd": 34, "hrv_sdnn": 44,
            "systolic": 120, "diastolic": 78,
            "spo2": 96.5,
            "deep_sleep_minutes": 65, "light_sleep_minutes": 175,
            "rem_sleep_minutes": 75, "awake_minutes": 40,
            "steps": 9000, "active_calories": 410, "active_minutes": 52,
        },
    },
    {
        "id": "hypoxia_suspect",
        "label": "血氧偏低",
        "user_id": "u_low_spo2",
        "expected_range": (35, 50),
        "hours_since_last_sleep": 7.5,
        "metrics": {
            "resting_hr": 64, "hrv_rmssd": 36, "hrv_sdnn": 46,
            "systolic": 116, "diastolic": 74,
            "spo2": 92,
            "deep_sleep_minutes": 78, "light_sleep_minutes": 190,
            "rem_sleep_minutes": 85, "awake_minutes": 28,
            "steps": 6500, "active_calories": 280, "active_minutes": 30,
        },
    },
    {
        "id": "sedentary_recovery",
        "label": "久坐、活动不足",
        "user_id": "u_sedentary",
        "expected_range": (50, 62),
        "hours_since_last_sleep": 14.0,
        "metrics": {
            "resting_hr": 60, "hrv_rmssd": 45, "hrv_sdnn": 58,
            "systolic": 115, "diastolic": 73,
            "spo2": 97,
            "deep_sleep_minutes": 86, "light_sleep_minutes": 200,
            "rem_sleep_minutes": 95, "awake_minutes": 20,
            "steps": 1800, "active_calories": 95, "active_minutes": 8,
        },
    },
    {
        "id": "shift_work",
        "label": "轮班后节律紊乱",
        "user_id": "u_shift",
        "expected_range": (38, 52),
        "hours_since_last_sleep": 6.0,
        "metrics": {
            "resting_hr": 74, "hrv_rmssd": 24, "hrv_sdnn": 32,
            "systolic": 126, "diastolic": 80,
            "spo2": 96,
            "deep_sleep_minutes": 48, "light_sleep_minutes": 162,
            "rem_sleep_minutes": 55, "awake_minutes": 55,
            "steps": 10500, "active_calories": 460, "active_minutes": 48,
        },
    },
    {
        "id": "elite_recovery",
        "label": "精英运动员恢复日",
        "user_id": "u_elite",
        "expected_range": (78, 88),
        "hours_since_last_sleep": 10.0,
        "metrics": {
            "resting_hr": 48, "hrv_rmssd": 72, "hrv_sdnn": 92,
            "systolic": 108, "diastolic": 68,
            "spo2": 98,
            "deep_sleep_minutes": 130, "light_sleep_minutes": 192,
            "rem_sleep_minutes": 108, "awake_minutes": 12,
            "steps": 11000, "active_calories": 520, "active_minutes": 55,
        },
    },
    {
        "id": "partial_missing_metrics",
        "label": "部分指标缺失（演示兜底）",
        "user_id": "u_partial",
        "expected_range": (55, 70),
        "hours_since_last_sleep": 9.0,
        "metrics": {
            "resting_hr": None, "hrv_rmssd": 39, "hrv_sdnn": None,
            "systolic": None, "diastolic": None,
            "spo2": 97,
            "deep_sleep_minutes": None, "light_sleep_minutes": 200,
            "rem_sleep_minutes": 95, "awake_minutes": None,
            "steps": None, "active_calories": None, "active_minutes": 38,
        },
    },
]


def scenario_to_test_case(scenario: dict[str, Any]) -> dict[str, Any]:
    lo, hi = scenario["expected_range"]
    return {
        "user_id":               scenario["user_id"],
        "metrics":               deepcopy(scenario["metrics"]),
        "hours_since_last_sleep": float(scenario["hours_since_last_sleep"]),
        "expected_battery":      float(lo + hi) / 2.0,
    }


def build_optimizer_cases() -> list[dict[str, Any]]:
    return [scenario_to_test_case(s) for s in MOCK_SCENARIOS]


def generate_7_day_history(
    user_id: str,
    *,
    scenario_bias: dict[str, float] | None = None,
    noise_scale: float = 0.03,
    seed: int | None = 42,
) -> list[dict[str, Any]]:
    """生成连续 7 天的模拟日级指标，用于基线建模测试或服务演示。"""
    if seed is not None:
        random.seed(seed)
    bias = scenario_bias or {}
    rows: list[dict[str, Any]] = []

    # 各字段合理取值区间
    _clamp: dict[str, tuple[float, float]] = {
        "resting_hr":          (40.0, 100.0),
        "hrv_rmssd":           (8.0,  120.0),
        "hrv_sdnn":            (10.0, 150.0),
        "systolic":            (85.0, 160.0),
        "diastolic":           (50.0, 105.0),
        "spo2":                (88.0, 100.0),
        "deep_sleep_minutes":  (10.0, 180.0),
        "light_sleep_minutes": (60.0, 360.0),
        "rem_sleep_minutes":   (10.0, 180.0),
        "awake_minutes":       (0.0,  120.0),
        "steps":               (0.0, 30000.0),
        "active_calories":     (0.0,  1500.0),
        "active_minutes":      (0.0,   300.0),
    }

    for day in range(7):
        row: dict[str, Any] = {"day_index": day}
        for k in METRIC_KEYS:
            base  = float(POPULATION_MEAN[k])
            delta = float(bias.get(k, 0.0))
            noisy = (base + delta) * (1.0 + random.uniform(-noise_scale, noise_scale))
            lo, hi = _clamp.get(k, (0.0, 1e9))
            row[k] = max(lo, min(hi, noisy))
        rows.append(row)
    return rows


def seed_baseline_for_mock_users(model: Any) -> None:
    """将 MOCK_SCENARIOS 涉及的 user_id 批量灌入 7 日历史。"""
    if not isinstance(model, BaselineModel):
        raise TypeError("model must be BaselineModel")

    preset_biases: dict[str, dict[str, float]] = {
        "u_good_hrv":    {"hrv_rmssd": 12, "hrv_sdnn": 16,
                          "deep_sleep_minutes": 25, "resting_hr": -6},
        "u_late_low":    {"hrv_rmssd": -18, "hrv_sdnn": -22,
                          "deep_sleep_minutes": -40, "resting_hr": 10,
                          "awake_minutes": 30},
        "u_overtrain":   {"active_minutes": 40, "steps": 4000,
                          "hrv_rmssd": -10, "deep_sleep_minutes": -25},
        "u_normal":      {},
        "u_sleep_debt":  {"deep_sleep_minutes": -20, "hrv_rmssd": -6,
                          "awake_minutes": 15},
        "u_low_spo2":    {"spo2": -4},
        "u_sedentary":   {"active_minutes": -25, "steps": -5000,
                          "active_calories": -220},
        "u_shift":       {"deep_sleep_minutes": -30, "hrv_rmssd": -12,
                          "resting_hr": 8, "awake_minutes": 25},
        "u_elite":       {"hrv_rmssd": 22, "hrv_sdnn": 28,
                          "deep_sleep_minutes": 35, "resting_hr": -10},
        "u_partial":     {},
    }

    skip_users = {"u_cold"}
    seen: set[str] = set()

    for s in MOCK_SCENARIOS:
        uid = str(s["user_id"])
        if uid in skip_users or uid in seen:
            continue
        seen.add(uid)
        bias    = preset_biases.get(uid, {})
        records = generate_7_day_history(uid, scenario_bias=bias,
                                         seed=hash(uid) % (2 ** 31))
        model.update({"user_id": uid, "records": records})
