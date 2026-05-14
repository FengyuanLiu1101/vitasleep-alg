"""
AL-04 身体电量评分：组分归一化 → 加权融合 → 睡眠间隔时间衰减。
"""

from __future__ import annotations

import math
from typing import Any

from baseline import BaselineModel
from normalizer import normalize

# z 偏离基线时线性折算系数（与业务共同校准；未暴露在 params 中以免与需求清单不一致）
_Z_PENALTY: float = 12.0


class BatteryCalculator:
    """
    根据用户基线与当前指标计算机体「电量」0~100 及各组分得分。

    步骤：
    1. 从 ``BaselineModel`` 取混合基线；对 resting_hr、hrv_rmssd、spo2、
       deep_sleep_ratio、active_minutes 逐个归一化；其中 HRV 通道为
       RHR 与 RMSSD 两路得分平均；SpO2 使用单侧低 penalization。
    2. 权重来自运行时 ``params``（与 ``params.TUNABLE_PARAMS`` 对齐）。
    3. 按 ``hours_since_last_sleep`` 做指数衰减（跨 24h 为尺度，``decay_rate`` 可调）。
    """

    def __init__(self, params: dict[str, Any], baseline_model: BaselineModel) -> None:
        """
        Args:
            params: 与 ``TUNABLE_PARAMS`` 同结构的字典（通常为服务内可改副本）。
            baseline_model: 已初始化的基线模型实例。
        """
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
        """
        解析单字段；若为 None 则使用基线均值兜底（z=0 中性）并记录缺失。

        Returns:
            tuple[float, bool]: (用于计算的浮点值, 是否原为缺失)。
        """
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
        计算机体电量score与明细。

        Args:
            user_id: 用户标识，用于查询个人基线。
            metrics: 可包含 ``resting_hr``、``hrv_rmssd``、``spo2``、
                ``deep_sleep_ratio``、``active_minutes``；缺失键或 null 将触发兜底。
            hours_since_last_sleep: 距上次睡醒/起床的小时数，越长衰减越大。

        Returns:
            dict: 含 ``battery``, ``raw_battery``, ``components``, ``decay_factor``,
            ``imputed_fields``, ``weights_used`` 等。
        """
        bl = self._baseline_model.get_baseline(user_id)
        bmetrics = bl["metrics"]

        imputed: list[str] = []

        def g(name: str) -> tuple[float, float, float]:
            """返回 (value, mean, std)。"""
            mean = float(bmetrics[name]["mean"])
            std = float(bmetrics[name]["std"])
            v, _ = self._pick(metrics.get(name), mean, was_missing=imputed, field_name=name)
            return v, mean, std

        v_ds, m_ds, s_ds = g("deep_sleep_ratio")
        sleep_score = normalize(v_ds, m_ds, s_ds, penalty_per_z=_Z_PENALTY)

        v_hr, m_hr, s_hr = g("resting_hr")
        v_rmsd, m_r, s_r = g("hrv_rmssd")
        hr_score = normalize(v_hr, m_hr, s_hr, penalty_per_z=_Z_PENALTY)
        hrv_score_channel = normalize(v_rmsd, m_r, s_r, penalty_per_z=_Z_PENALTY)
        hrv_score = (hr_score + hrv_score_channel) / 2.0

        v_spo2, m_o2, s_o2 = g("spo2")
        spo2_score = normalize(v_spo2, m_o2, s_o2, one_sided_low=True, penalty_per_z=_Z_PENALTY)

        v_act, m_act, s_act = g("active_minutes")
        activity_score = normalize(v_act, m_act, s_act, penalty_per_z=_Z_PENALTY)

        wmap = self._weights_vec()
        # 若权重和有数值误差，再归一
        wsum = sum(wmap.values())
        if wsum <= 0:
            wmap = {k: 0.25 for k in wmap}
            wsum = 1.0
        wnorm = {k: wmap[k] / wsum for k in wmap}

        raw_battery = (
            wnorm["sleep"] * sleep_score
            + wnorm["hrv"] * hrv_score
            + wnorm["spo2"] * spo2_score
            + wnorm["activity"] * activity_score
        )

        decay_rate = float(self._params["decay_rate"]["value"])
        t = max(0.0, float(hours_since_last_sleep))
        # 以「每 24 小时」为一个衰减单位，避免小时数过大时过度惩罚
        decay_factor = math.exp(-decay_rate * (t / 24.0))
        battery = float(max(0.0, min(100.0, raw_battery * decay_factor)))

        return {
            "user_id": str(user_id),
            "battery": battery,
            "raw_battery": float(max(0.0, min(100.0, raw_battery))),
            "decay_factor": float(decay_factor),
            "hours_since_last_sleep": t,
            "components": {
                "sleep": {"score": float(sleep_score), "metric": "deep_sleep_ratio"},
                "hrv": {
                    "score": float(hrv_score),
                    "detail": {"resting_hr": hr_score, "hrv_rmssd": hrv_score_channel},
                },
                "spo2": {"score": float(spo2_score)},
                "activity": {"score": float(activity_score)},
            },
            "weights_used": wnorm,
            "imputed_fields": list(imputed),
            "baseline_snapshot": {
                "days_in_window": bl["days_in_window"],
                "personal_weight": bl["personal_weight"],
            },
        }
