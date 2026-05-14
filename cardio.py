"""
AL-06 心血管健康指数（Cardiovascular Health Index，CHI）。

整合 HRV（RMSSD + SDNN）、血压（MAP + 脉压差）与静息心率，输出 0~100 分。

维度权重：
  - HRV 复合（RMSSD 45% + SDNN 55%）: 占 CHI 40%
  - 血压复合（MAP 60% + 脉压差 40%）: 占 CHI 35%
  - 静息心率                          : 占 CHI 25%

血压衍生指标：
  - MAP（平均动脉压）= diastolic + (systolic - diastolic) / 3
    理想约 70~100 mmHg，人群中心 90，std 8
  - 脉压差 = systolic - diastolic
    理想 30~50 mmHg，人群中心 42，std 10；过窄或过宽均为风险
"""

from __future__ import annotations

from typing import Any

from normalizer import normalize

_Z_PENALTY: float = 12.0

# 血压衍生指标的固定人群先验（不走个人基线）
_BP_POP = {
    "map":   {"mean": 90.0, "std": 8.0},
    "pulse": {"mean": 42.0, "std": 10.0},
}


def compute_cardio_index(
    resting_hr: float | None,
    hrv_rmssd: float | None,
    hrv_sdnn: float | None,
    systolic: float | None,
    diastolic: float | None,
    baseline_metrics: dict[str, Any],
    imputed: list[str],
) -> tuple[float, dict[str, Any]]:
    """
    计算心血管健康指数（CHI）0~100。

    所有输入字段允许为 None，缺失时用用户/群体基线均值兜底。

    Args:
        resting_hr: 静息心率 bpm。
        hrv_rmssd: HRV RMSSD ms（副交感活性指标）。
        hrv_sdnn: HRV SDNN ms（总体变异性）。
        systolic: 收缩压 mmHg。
        diastolic: 舒张压 mmHg。
        baseline_metrics: BaselineModel.get_baseline 返回的 metrics 字段。
        imputed: 缺失字段名（就地追加）。

    Returns:
        tuple[float, dict]: (chi 0~100, 各组件明细)。
    """
    def _pick(val: float | None, key: str) -> float:
        if val is None:
            imputed.append(key)
            return float(baseline_metrics[key]["mean"])
        return float(val)

    hr    = _pick(resting_hr, "resting_hr")
    rmssd = _pick(hrv_rmssd,  "hrv_rmssd")
    sdnn  = _pick(hrv_sdnn,   "hrv_sdnn")
    sys_  = _pick(systolic,   "systolic")
    dia_  = _pick(diastolic,  "diastolic")

    bl = baseline_metrics

    # --- HRV 复合（个人基线归一化）---
    rmssd_score = normalize(rmssd, bl["hrv_rmssd"]["mean"], bl["hrv_rmssd"]["std"],
                            penalty_per_z=_Z_PENALTY)
    sdnn_score  = normalize(sdnn,  bl["hrv_sdnn"]["mean"],  bl["hrv_sdnn"]["std"],
                            penalty_per_z=_Z_PENALTY)
    hrv_score   = 0.45 * rmssd_score + 0.55 * sdnn_score

    # --- 血压复合（固定人群先验）---
    map_val        = dia_ + (sys_ - dia_) / 3.0
    pulse_pressure = sys_ - dia_

    map_score   = normalize(map_val,        _BP_POP["map"]["mean"],   _BP_POP["map"]["std"],
                            penalty_per_z=_Z_PENALTY)
    pulse_score = normalize(pulse_pressure, _BP_POP["pulse"]["mean"], _BP_POP["pulse"]["std"],
                            penalty_per_z=_Z_PENALTY)
    bp_score    = 0.60 * map_score + 0.40 * pulse_score

    # --- 静息心率（双侧：过高为心脏负担，过低可能异常）---
    hr_score = normalize(hr, bl["resting_hr"]["mean"], bl["resting_hr"]["std"],
                         penalty_per_z=_Z_PENALTY)

    chi = 0.40 * hrv_score + 0.35 * bp_score + 0.25 * hr_score

    return float(max(0.0, min(100.0, chi))), {
        "hrv_composite":        round(hrv_score,        1),
        "hrv_rmssd_score":      round(rmssd_score,      1),
        "hrv_sdnn_score":       round(sdnn_score,       1),
        "bp_composite":         round(bp_score,         1),
        "map_mmhg":             round(map_val,          1),
        "pulse_pressure_mmhg":  round(pulse_pressure,   1),
        "map_score":            round(map_score,        1),
        "pulse_score":          round(pulse_score,      1),
        "hr_score":             round(hr_score,         1),
    }
