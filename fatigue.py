"""
AL-08 实时疲劳评估（Fatigue Index）。

输出 0~100，数值越高代表越疲劳。

四路信号融合：
  - HRV 抑制（35%）：RMSSD 低于个人基线 → 交感主导 → 疲劳
  - 睡眠不足（30%）：sleep_score 低 → 睡眠质量差 → 疲劳
  - 时间压力（20%）：hours_since_last_sleep 长 → 稳态睡眠压力积累
  - 电量亏空（15%）：battery 低 → 综合生理储备不足

数学设计：
  - HRV 抑制：z_rmssd = (rmssd - baseline_mean) / baseline_std
               signal = clip(0.5 - z_rmssd * 0.15, 0, 1)
               z 越负（RMSSD 越低于基线）→ signal 越接近 1（疲劳）
  - 时间压力：1 - exp(-0.045 * hours)
               8h → 0.30；16h → 0.51；24h → 0.66；符合睡眠稳态压力曲线
"""

from __future__ import annotations

import math


def compute_fatigue_index(
    hrv_rmssd: float | None,
    hrv_rmssd_baseline_mean: float,
    hrv_rmssd_baseline_std: float,
    sleep_score: float,
    battery: float,
    hours_since_last_sleep: float,
) -> tuple[float, dict[str, float]]:
    """
    计算疲劳指数 0~100（越高越疲劳）。

    Args:
        hrv_rmssd: 当前 HRV RMSSD ms；None 则视为中性（无法判断方向）。
        hrv_rmssd_baseline_mean: 用户/群体 RMSSD 基线均值。
        hrv_rmssd_baseline_std: RMSSD 基线标准差。
        sleep_score: 当日睡眠质量得分 0~100（来自 sleep_scorer）。
        battery: 机体电量 0~100（来自 battery 计算结果）。
        hours_since_last_sleep: 距上次起床的小时数。

    Returns:
        tuple[float, dict]: (fatigue_index 0~100, 各信号明细)。
    """
    # 1. HRV 抑制信号
    if hrv_rmssd is None:
        hrv_signal = 0.50  # 无数据 → 中性
    else:
        sigma = max(hrv_rmssd_baseline_std, 1e-6)
        z = (float(hrv_rmssd) - hrv_rmssd_baseline_mean) / sigma
        hrv_signal = float(max(0.0, min(1.0, 0.5 - z * 0.15)))

    # 2. 睡眠不足信号（sleep_score 100 → 0 疲劳；sleep_score 0 → 1 疲劳）
    sleep_signal = float(max(0.0, min(1.0, 1.0 - sleep_score / 100.0)))

    # 3. 时间压力信号（稳态睡眠压力曲线近似）
    t = max(0.0, float(hours_since_last_sleep))
    time_signal = float(1.0 - math.exp(-0.045 * t))

    # 4. 电量亏空信号
    battery_signal = float(max(0.0, min(1.0, 1.0 - battery / 100.0)))

    raw = (
        0.35 * hrv_signal
        + 0.30 * sleep_signal
        + 0.20 * time_signal
        + 0.15 * battery_signal
    )
    fatigue_index = float(max(0.0, min(100.0, raw * 100.0)))

    return fatigue_index, {
        "hrv_suppression_signal":  round(hrv_signal,     3),
        "sleep_deficit_signal":    round(sleep_signal,   3),
        "time_pressure_signal":    round(time_signal,    3),
        "battery_deficit_signal":  round(battery_signal, 3),
    }
