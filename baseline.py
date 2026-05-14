"""
AL-07 用户基线建模：滚动窗口均值与标准差，冷启动人群兜底与渐进切换。

指标：resting_hr、hrv_rmssd、spo2、deep_sleep_ratio、active_minutes
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from copy import deepcopy
from typing import Any

# 冷启动内置人群统计（示例常量，可由运营/医学团队校准后替换）
POPULATION_MEAN: dict[str, float] = {
    "resting_hr": 62.0,
    "hrv_rmssd": 42.0,
    "spo2": 97.0,
    "deep_sleep_ratio": 0.22,
    "active_minutes": 38.0,
}

POPULATION_STD: dict[str, float] = {
    "resting_hr": 8.0,
    "hrv_rmssd": 14.0,
    "spo2": 1.2,
    "deep_sleep_ratio": 0.06,
    "active_minutes": 18.0,
}

METRIC_KEYS: tuple[str, ...] = (
    "resting_hr",
    "hrv_rmssd",
    "spo2",
    "deep_sleep_ratio",
    "active_minutes",
)


class BaselineModel:
    """
    按用户维护至多 ``window_days`` 天的日级样本，输出混合基线（人群 + 个人）。

    规则摘要：
    - 满 ``window_days`` 天后，均值/方差仅来自个人窗口。
    - 不足 ``window_days`` 时：用 ``n / window_days`` 对个人估计与人群统计做凸组合；
      若尚无个人数据则完全使用人群统计。
    - 标准差在样本量极小时向人群标准差收缩，避免分母过小。
    """

    def __init__(self, window_days: int = 7) -> None:
        """
        Args:
            window_days: 滚动窗口长度（天）。
        """
        self._window = max(1, int(window_days))
        # user_id -> deque[dict]，每项为单日指标字典
        self._history: dict[str, deque[dict[str, float]]] = defaultdict(
            lambda: deque(maxlen=self._window)
        )

    @property
    def window_days(self) -> int:
        """当前滚动窗口天数。"""
        return self._window

    def set_window_days(self, window_days: int) -> None:
        """
        运行时调整窗口长度并截断已有历史（保留最近 window_days 条）。

        Args:
            window_days: 新的窗口天数，至少为 1。
        """
        self._window = max(1, int(window_days))
        for uid, dq in self._history.items():
            new_dq: deque[dict[str, float]] = deque(maxlen=self._window)
            for row in dq:
                new_dq.append(row)
            self._history[uid] = new_dq

    @staticmethod
    def _row_valid(row: dict[str, Any]) -> dict[str, float] | None:
        """提取一行中可用的浮点指标；若缺少全部核心键则返回 None。"""
        out: dict[str, float] = {}
        for k in METRIC_KEYS:
            v = row.get(k)
            if v is None:
                continue
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
        return out if out else None

    @staticmethod
    def _mean_std(values: list[float]) -> tuple[float, float]:
        """样本均值与样本标准差（ddof=1）；单样本时返回 (x, 人群先验尺度由调用方混合)。"""
        n = len(values)
        if n == 0:
            return float("nan"), float("nan")
        m = sum(values) / n
        if n == 1:
            return m, 0.0
        var = sum((x - m) ** 2 for x in values) / (n - 1)
        return m, math.sqrt(var)

    def _blend(
        self,
        personal_m: float,
        personal_s: float,
        n: int,
        pop_m: float,
        pop_s: float,
    ) -> tuple[float, float]:
        """
        将个人估计与人群统计做凸组合；样本越少越接近人群。

        Args:
            personal_m: 个人窗口内均值。
            personal_s: 个人窗口内标准差（可能为 0）。
            n: 有效个人日样本数。
            pop_m: 人群均值。
            pop_s: 人群标准差。

        Returns:
            tuple[float, float]: (混合均值, 混合标准差)。
        """
        alpha = min(1.0, n / float(self._window))
        mean = alpha * personal_m + (1.0 - alpha) * pop_m
        # 方差层次化收缩：个人 std 与人群 std 混合，并对极小 std 保底
        p_s = personal_s if personal_s > 0 else pop_s
        std = alpha * p_s + (1.0 - alpha) * pop_s
        std = max(std, 1e-6)
        return mean, std

    def update(self, new_data: dict[str, Any]) -> dict[str, Any]:
        """
        增量写入用户日级（或多日）历史数据。

        Args:
            new_data: 支持两种形态：
                1) ``{"user_id": "u1", "records": [ {...}, ... ]}`` 每条为单日多指标；
                2) ``{"user_id": "u1", **metrics}`` 单日一条。

        Returns:
            dict: ``{"user_id", "accepted_rows", "window_days", "total_stored"}``。
        """
        user_id = str(new_data["user_id"])
        records: list[dict[str, Any]]
        if "records" in new_data:
            records = list(new_data["records"])
        else:
            row = {k: new_data.get(k) for k in METRIC_KEYS}
            records = [row]

        accepted = 0
        dq = self._history[user_id]
        for r in records:
            cleaned = self._row_valid(r)
            if cleaned is None:
                continue
            dq.append(cleaned)
            accepted += 1

        return {
            "user_id": user_id,
            "accepted_rows": accepted,
            "window_days": self._window,
            "total_stored": len(dq),
        }

    def get_baseline(self, user_id: str) -> dict[str, Any]:
        """
        返回指定用户当前基线（各指标 mean/std），含混合比例说明。

        Args:
            user_id: 用户标识。

        Returns:
            dict: 结构包含 ``user_id``, ``metrics``, ``days_in_window``,
            ``personal_weight``, ``population_fallback``.
        """
        uid = str(user_id)
        dq = self._history[uid]
        n = len(dq)
        metrics_out: dict[str, dict[str, float]] = {}

        if n == 0:
            personal_weight = 0.0
            for k in METRIC_KEYS:
                metrics_out[k] = {
                    "mean": POPULATION_MEAN[k],
                    "std": max(POPULATION_STD[k], 1e-6),
                }
            return {
                "user_id": uid,
                "metrics": metrics_out,
                "days_in_window": 0,
                "personal_weight": personal_weight,
                "population_fallback": True,
            }

        personal_weight = min(1.0, n / float(self._window))

        for k in METRIC_KEYS:
            vals = [row[k] for row in dq if k in row]
            pop_m, pop_s = POPULATION_MEAN[k], POPULATION_STD[k]
            if not vals:
                metrics_out[k] = {"mean": pop_m, "std": max(pop_s, 1e-6)}
                continue
            p_m, p_s = self._mean_std(vals)
            m, s = self._blend(p_m, p_s, len(vals), pop_m, pop_s)
            metrics_out[k] = {"mean": m, "std": max(s, 1e-6)}

        return {
            "user_id": uid,
            "metrics": metrics_out,
            "days_in_window": n,
            "personal_weight": personal_weight,
            "population_fallback": personal_weight < 1.0,
        }

    def export_user_history(self, user_id: str) -> list[dict[str, float]]:
        """
        导出某用户当前窗口内原始日记录（副本），便于测试。

        Args:
            user_id: 用户标识。

        Returns:
            list[dict]: 按时间从旧到新排列的指标行列表。
        """
        return [deepcopy(dict(x)) for x in self._history[str(user_id)]]
