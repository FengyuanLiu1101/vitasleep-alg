"""
AL-05 睡眠质量评分。

输入：Health Connect SleepStage 各分期时长（分钟），输出 0~100 综合得分。

评分四维度：
  - 总时长（duration）   30%  理想 7~9 小时
  - 睡眠效率（efficiency）30%  total_sleep / (total_sleep + awake)，理想 > 85%
  - 深睡比例（deep_ratio）25%  理想 15%~25%
  - REM 比例（rem_ratio） 15%  理想 20%~25%
"""

from __future__ import annotations

from typing import Any

from normalizer import normalize

# 睡眠派生指标的人群基准（比例 / 小时均采用固定先验，不随分钟基线浮动）
_SLEEP_POP: dict[str, dict[str, float]] = {
    "total_hours": {"mean": 7.5,  "std": 1.0},
    "efficiency":  {"mean": 0.87, "std": 0.06},
    "deep_ratio":  {"mean": 0.20, "std": 0.06},
    "rem_ratio":   {"mean": 0.22, "std": 0.06},
}

_WEIGHTS = {"duration": 0.30, "efficiency": 0.30, "deep": 0.25, "rem": 0.15}
_Z_PENALTY: float = 14.0


def compute_sleep_score(
    deep_minutes: float | None,
    light_minutes: float | None,
    rem_minutes: float | None,
    awake_minutes: float | None,
    baseline_metrics: dict[str, Any],
    imputed: list[str],
) -> tuple[float, dict[str, Any]]:
    """
    计算综合睡眠质量得分 0~100。

    各分期时长均允许为 None；缺失时从用户/群体基线均值兜底并追加到 imputed。

    Args:
        deep_minutes: 深睡时长（分钟）。
        light_minutes: 浅睡时长（分钟）。
        rem_minutes: REM 时长（分钟）。
        awake_minutes: 睡眠期间清醒时长（分钟）。
        baseline_metrics: BaselineModel.get_baseline 返回的 metrics 字段。
        imputed: 被兜底的字段名列表（就地追加，与 battery 共享）。

    Returns:
        tuple[float, dict]: (sleep_score 0~100, 各子维度明细)。
    """
    def _pick(val: float | None, key: str) -> float:
        if val is None:
            imputed.append(key)
            return float(baseline_metrics[key]["mean"])
        return float(val)

    deep  = _pick(deep_minutes,  "deep_sleep_minutes")
    light = _pick(light_minutes, "light_sleep_minutes")
    rem   = _pick(rem_minutes,   "rem_sleep_minutes")
    awake = _pick(awake_minutes, "awake_minutes")

    total_sleep = max(deep + light + rem, 1.0)
    total_time  = total_sleep + max(awake, 0.0)

    total_hours = total_sleep / 60.0
    efficiency  = total_sleep / total_time
    deep_ratio  = deep / total_sleep
    rem_ratio   = rem  / total_sleep

    def _bl(key: str) -> tuple[float, float]:
        return _SLEEP_POP[key]["mean"], _SLEEP_POP[key]["std"]

    m, s = _bl("total_hours")
    duration_score   = normalize(total_hours, m, s, penalty_per_z=_Z_PENALTY)

    m, s = _bl("efficiency")
    efficiency_score = normalize(efficiency, m, s, one_sided_low=True, penalty_per_z=_Z_PENALTY)

    m, s = _bl("deep_ratio")
    deep_score       = normalize(deep_ratio, m, s, penalty_per_z=_Z_PENALTY)

    m, s = _bl("rem_ratio")
    rem_score        = normalize(rem_ratio,  m, s, penalty_per_z=_Z_PENALTY)

    score = (
        _WEIGHTS["duration"]   * duration_score
        + _WEIGHTS["efficiency"] * efficiency_score
        + _WEIGHTS["deep"]       * deep_score
        + _WEIGHTS["rem"]        * rem_score
    )

    return float(max(0.0, min(100.0, score))), {
        "total_sleep_hours":  round(total_hours, 2),
        "sleep_efficiency":   round(efficiency,  3),
        "deep_ratio":         round(deep_ratio,  3),
        "rem_ratio":          round(rem_ratio,   3),
        "duration_score":     round(duration_score,   1),
        "efficiency_score":   round(efficiency_score, 1),
        "deep_score":         round(deep_score,  1),
        "rem_score":          round(rem_score,   1),
    }
