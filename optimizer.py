"""
白盒权重优化：在约束下最小化预测电量与目标电量的 MSE。

``scipy.optimize.minimize`` 使用 SLSQP：各权重有上下界且总和为 1。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Sequence

import numpy as np
from scipy.optimize import minimize

from baseline import BaselineModel
from battery import BatteryCalculator
from params import clone_tunable_params


def optimize_weights(
    test_cases: Sequence[dict[str, Any]],
    baseline_model: BaselineModel,
    tunable_params: dict[str, Any] | None = None,
) -> dict[str, float]:
    """
    根据多组 ``(输入指标, 期望电量)`` 拟合四组分权重。

    Args:
        test_cases: 序列元素须包含键：
            ``user_id`` (str), ``metrics`` (dict),
            ``hours_since_last_sleep`` (float), ``expected_battery`` (float)。
        baseline_model: 已与各 ``user_id`` 对齐、含历史窗口的基线模型。
        tunable_params: 可选参数蓝图；默认 ``clone_tunable_params()``，
            优化过程只改写其中 ``weights[*].value``，其它（如 decay）保持不动。

    Returns:
        dict: 键 ``sleep, hrv, spo2, activity`` 的最优权重（非负、满足 range、
        数值归一后总和为 1）。
    """
    params_base = deepcopy(tunable_params) if tunable_params is not None else clone_tunable_params()
    wr = {k: (float(v["range"][0]), float(v["range"][1])) for k, v in params_base["weights"].items()}

    bounds = [wr["sleep"], wr["hrv"], wr["spo2"], wr["activity"]]
    lows = np.array([b[0] for b in bounds], dtype=float)
    highs = np.array([b[1] for b in bounds], dtype=float)

    x0 = np.array(
        [
            float(params_base["weights"]["sleep"]["value"]),
            float(params_base["weights"]["hrv"]["value"]),
            float(params_base["weights"]["spo2"]["value"]),
            float(params_base["weights"]["activity"]["value"]),
        ],
        dtype=float,
    )
    # 投影到可行域（框 + 和为 1 的近似）
    x0 = np.clip(x0, lows, highs)
    if x0.sum() <= 0:
        x0 = np.array([0.25, 0.25, 0.25, 0.25])
    x0 = x0 / x0.sum()
    x0 = np.clip(x0, lows, highs)
    x0 = x0 / x0.sum()

    cases = list(test_cases)
    if not cases:
        return {
            "sleep": float(x0[0]),
            "hrv": float(x0[1]),
            "spo2": float(x0[2]),
            "activity": float(x0[3]),
        }

    def objective(vec: np.ndarray) -> float:
        x = np.clip(vec.astype(float), lows, highs)
        s = float(np.sum(x))
        if s <= 0:
            return 1e12
        x = x / s
        p = deepcopy(params_base)
        p["weights"]["sleep"]["value"] = float(x[0])
        p["weights"]["hrv"]["value"] = float(x[1])
        p["weights"]["spo2"]["value"] = float(x[2])
        p["weights"]["activity"]["value"] = float(x[3])

        calc = BatteryCalculator(p, baseline_model)
        errs: list[float] = []
        for c in cases:
            pred = calc.calculate(
                str(c["user_id"]),
                dict(c["metrics"]),
                float(c["hours_since_last_sleep"]),
            )["battery"]
            e = float(pred) - float(c["expected_battery"])
            errs.append(e * e)
        return float(np.mean(errs))

    cons = ({"type": "eq", "fun": lambda v: float(np.sum(v)) - 1.0},)

    res = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=cons,
        options={"ftol": 1e-9, "maxiter": 800},
    )

    x = np.clip(np.asarray(res.x, dtype=float), lows, highs)
    s = float(np.sum(x))
    if s <= 0:
        x = np.ones(4) / 4.0
    else:
        x = x / s

    return {
        "sleep": float(x[0]),
        "hrv": float(x[1]),
        "spo2": float(x[2]),
        "activity": float(x[3]),
    }
