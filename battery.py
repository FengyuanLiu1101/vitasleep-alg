"""
AL-04 身体电量综合评分：四组分加权融合 → 睡眠间隔衰减。

组分：
  - sleep（AL-05）：deep/light/rem/awake 分钟数 → sleep_scorer
  - hrv  ：resting_hr + hrv_rmssd + hrv_sdnn + 血压 MAP 四路平均
  - spo2 ：单侧低惩罚归一化
  - activity：steps + active_calories + active_minutes 三路平均
"""

from __future__ import annotations

import math
from typing import Any

from baseline import BaselineModel
from normalizer import normalize
from sleep_scorer import compute_sleep_score

_Z_PENALTY: float = 12.0

# 血压 MAP 固定先验（与 cardio.py 保持一致）
_MAP_MEAN: float = 90.0
_MAP_STD:  float = 8.0


class BatteryCalculator:
    """
    根据用户基线与当前指标计算机体「电量」0~100 及各组分得分。

    步骤：
    1. 从 BaselineModel 取混合基线。
    2. 睡眠得分由 sleep_scorer（AL-05）计算，使用四分期时长。
    3. HRV 通道：resting_hr / hrv_rmssd / hrv_sdnn / 血压 MAP 四路平均。
    4. SpO2：单侧低惩罚。
    5. 活动：steps / active_calories / active_minutes 三路平均（步数与卡路里
       单侧低惩罚，active_minutes 双侧）。
    6. 按 hours_since_last_sleep 做指数衰减（以 24h 为尺度）。
    """

    def __init__(self, params: dict[str, Any], baseline_model: BaselineModel) -> None:
        self._params = params
        self._baseline_model = baseline_model

    def _weights_vec(self) -> dict[str, float]:
        w = self._params["weights"]
        return {k: float(w[k]["value"]) for k in ("sleep", "hrv", "spo2", "activity")}

    @staticmethod
    def _pick(
        value: Any,
        baseline_mean: float,
        *,
        was_missing: list[str],
        field_name: str,
    ) -> tuple[float, bool]:
        """None 时用基线均值兜底并记录缺失。"""
        if value is None:
            was_missing.append(field_name)
            return float(baseline_mean), True
        return float(value), False

    def calculate(
        self,
        user_id: str,
        metrics: dict[str, Any],
        hours_since_last_sleep: float,
    ) -> dict[str, Any]:
        """
        计算机体电量与明细。

        Args:
            user_id: 用户标识。
            metrics: 可包含所有 METRIC_KEYS 字段；缺失或 null 触发基线兜底。
            hours_since_last_sleep: 距上次起床小时数（已在调用方兜底为非 None）。

        Returns:
            dict：含 battery / raw_battery / components / decay_factor /
            imputed_fields / weights_used / baseline_snapshot。
        """
        bl = self._baseline_model.get_baseline(user_id)
        bm = bl["metrics"]

        imputed: list[str] = []

        def g(name: str) -> tuple[float, float, float]:
            """返回 (value, mean, std)，缺失时用均值兜底。"""
            mean = float(bm[name]["mean"])
            std  = float(bm[name]["std"])
            v, _ = self._pick(metrics.get(name), mean,
                              was_missing=imputed, field_name=name)
            return v, mean, std

        # ── 1. 睡眠组分（AL-05）────────────────────────────────────────────
        sleep_score, sleep_detail = compute_sleep_score(
            deep_minutes=metrics.get("deep_sleep_minutes"),
            light_minutes=metrics.get("light_sleep_minutes"),
            rem_minutes=metrics.get("rem_sleep_minutes"),
            awake_minutes=metrics.get("awake_minutes"),
            baseline_metrics=bm,
            imputed=imputed,
        )

        # ── 2. HRV / 心血管通道 ────────────────────────────────────────────
        v_hr,    m_hr,    s_hr    = g("resting_hr")
        v_rmssd, m_rmssd, s_rmssd = g("hrv_rmssd")
        v_sdnn,  m_sdnn,  s_sdnn  = g("hrv_sdnn")
        v_sys,   m_sys,   s_sys   = g("systolic")
        v_dia,   m_dia,   s_dia   = g("diastolic")

        hr_score    = normalize(v_hr,    m_hr,    s_hr,    penalty_per_z=_Z_PENALTY)
        rmssd_score = normalize(v_rmssd, m_rmssd, s_rmssd, penalty_per_z=_Z_PENALTY)
        sdnn_score  = normalize(v_sdnn,  m_sdnn,  s_sdnn,  penalty_per_z=_Z_PENALTY)

        map_val  = v_dia + (v_sys - v_dia) / 3.0
        bp_score = normalize(map_val, _MAP_MEAN, _MAP_STD, penalty_per_z=_Z_PENALTY)

        hrv_score = (hr_score + rmssd_score + sdnn_score + bp_score) / 4.0

        # ── 3. 血氧 ────────────────────────────────────────────────────────
        v_spo2, m_spo2, s_spo2 = g("spo2")
        spo2_score = normalize(v_spo2, m_spo2, s_spo2,
                               one_sided_low=True, penalty_per_z=_Z_PENALTY)

        # ── 4. 活动通道 ────────────────────────────────────────────────────
        v_steps, m_steps, s_steps = g("steps")
        v_cal,   m_cal,   s_cal   = g("active_calories")
        v_act,   m_act,   s_act   = g("active_minutes")

        steps_score = normalize(v_steps, m_steps, s_steps,
                                one_sided_low=True, penalty_per_z=_Z_PENALTY)
        cal_score   = normalize(v_cal,   m_cal,   s_cal,
                                one_sided_low=True, penalty_per_z=_Z_PENALTY)
        act_score   = normalize(v_act,   m_act,   s_act,   penalty_per_z=_Z_PENALTY)
        activity_score = (steps_score + cal_score + act_score) / 3.0

        # ── 5. 加权融合 ────────────────────────────────────────────────────
        wmap = self._weights_vec()
        wsum = sum(wmap.values())
        if wsum <= 0:
            wmap = {k: 0.25 for k in wmap}
            wsum = 1.0
        wnorm = {k: wmap[k] / wsum for k in wmap}

        raw_battery = (
            wnorm["sleep"]    * sleep_score
            + wnorm["hrv"]      * hrv_score
            + wnorm["spo2"]     * spo2_score
            + wnorm["activity"] * activity_score
        )

        # ── 6. 时间衰减 ────────────────────────────────────────────────────
        decay_rate   = float(self._params["decay_rate"]["value"])
        t            = max(0.0, float(hours_since_last_sleep))
        decay_factor = math.exp(-decay_rate * (t / 24.0))
        battery      = float(max(0.0, min(100.0, raw_battery * decay_factor)))

        return {
            "user_id":               str(user_id),
            "battery":               battery,
            "raw_battery":           float(max(0.0, min(100.0, raw_battery))),
            "decay_factor":          float(decay_factor),
            "hours_since_last_sleep": t,
            "components": {
                "sleep": {
                    "score":  float(sleep_score),
                    "detail": sleep_detail,
                },
                "hrv": {
                    "score": float(hrv_score),
                    "detail": {
                        "resting_hr_score":  round(hr_score,    1),
                        "hrv_rmssd_score":   round(rmssd_score, 1),
                        "hrv_sdnn_score":    round(sdnn_score,  1),
                        "bp_map_score":      round(bp_score,    1),
                        "map_mmhg":          round(map_val,     1),
                    },
                },
                "spo2": {"score": float(spo2_score)},
                "activity": {
                    "score": float(activity_score),
                    "detail": {
                        "steps_score":          round(steps_score, 1),
                        "active_calories_score": round(cal_score,   1),
                        "active_minutes_score": round(act_score,   1),
                    },
                },
            },
            "weights_used":    wnorm,
            "imputed_fields":  list(dict.fromkeys(imputed)),  # 去重保序
            "baseline_snapshot": {
                "days_in_window":  bl["days_in_window"],
                "personal_weight": bl["personal_weight"],
            },
        }
