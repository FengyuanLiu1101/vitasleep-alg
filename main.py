"""
FastAPI 统一入口：电池评分、基线维护、参数校准读写。

启动示例（已附在文件末尾注释）::

    uvicorn main:app --reload --port 8001
"""

from __future__ import annotations

import copy
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from baseline import BaselineModel, METRIC_KEYS
from battery import BatteryCalculator
from mock_data import seed_baseline_for_mock_users
from params import clone_tunable_params

# -----------------------------------------------------------------------------
# Pydantic 模型（请求 / 响应校验）
# -----------------------------------------------------------------------------


class MetricPayload(BaseModel):
    """
    用户当前五项指标；字段允许为 ``null``，将使用基线均值兜底并降低置信度。
    """

    resting_hr: Optional[float] = Field(None, description="静息心率 bpm")
    hrv_rmssd: Optional[float] = Field(None, description="HRV RMSSD ms")
    spo2: Optional[float] = Field(None, description="血氧 %")
    deep_sleep_ratio: Optional[float] = Field(None, description="深睡占比 0~1")
    active_minutes: Optional[float] = Field(None, description="活动分钟")

    model_config = {"extra": "ignore"}


class BatteryRequest(BaseModel):
    """``POST /calculate/battery`` 请求体。"""

    user_id: str = Field(..., min_length=1)
    hours_since_last_sleep: Optional[float] = Field(None, ge=0.0, le=240.0)
    metrics: MetricPayload

    model_config = {"extra": "ignore"}


class BatteryResponse(BaseModel):
    """电量计算结果 + 明细 + 置信度。"""

    user_id: str
    battery: float
    raw_battery: float
    decay_factor: float
    hours_since_last_sleep: float
    components: dict[str, Any]
    weights_used: dict[str, float]
    imputed_fields: list[str]
    baseline_snapshot: dict[str, Any]
    confidence: float = Field(..., ge=0.0, le=1.0, description="0~1，缺失越多 / 冷启动越低")


class DayRecord(BaseModel):
    """单日历史记录；允许部分字段缺失（该日可能不计入 accepted_rows）。"""

    resting_hr: Optional[float] = None
    hrv_rmssd: Optional[float] = None
    spo2: Optional[float] = None
    deep_sleep_ratio: Optional[float] = None
    active_minutes: Optional[float] = None

    model_config = {"extra": "ignore"}


class BaselineUpdateRequest(BaseModel):
    """``POST /baseline/update`` 请求体。"""

    user_id: str = Field(..., min_length=1)
    records: list[DayRecord] = Field(..., min_length=1)


class BaselineUpdateResponse(BaseModel):
    """基线写入结果摘要。"""

    user_id: str
    accepted_rows: int
    window_days: int
    total_stored: int


class MetricBaseline(BaseModel):
    mean: float
    std: float


class BaselineGetResponse(BaseModel):
    """``GET /baseline/{user_id}`` 返回。"""

    user_id: str
    metrics: dict[str, MetricBaseline]
    days_in_window: int
    personal_weight: float
    population_fallback: bool


class WeightEntryUpdate(BaseModel):
    value: float


class ParamsUpdateRequest(BaseModel):
    """
    部分更新可调参数；未出现字段保持原值。

    权重可同时或单独提交；服务端会在合法区间上**投影并归一**，使总和为 1。
    """

    weights: Optional[dict[str, WeightEntryUpdate]] = None
    decay_rate: Optional[float] = None
    baseline_window_days: Optional[int] = None

    model_config = {"extra": "ignore"}

    @field_validator("baseline_window_days")
    @classmethod
    def _win(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v < 1 or v > 30:
            raise ValueError("baseline_window_days must be in [1, 30] for API safety")
        return v


class ParamsResponse(BaseModel):
    """当前生效参数 + 合法区间（深拷贝）。"""

    params: dict[str, Any]


# -----------------------------------------------------------------------------
# 应用状态
# -----------------------------------------------------------------------------

baseline_model = BaselineModel(window_days=int(clone_tunable_params()["baseline_window_days"]["value"]))
runtime_params: dict[str, Any] = clone_tunable_params()


def _sync_window() -> None:
    """将 ``runtime_params`` 中的窗口长度同步到基线模型。"""
    w = int(runtime_params["baseline_window_days"]["value"])
    baseline_model.set_window_days(w)


def _clip_renormalize_weights(p: dict[str, Any]) -> None:
    """
    将 ``p['weights']`` 中四项权重限制在各 ``range`` 内并总和归一为 1。

    若可行域过窄导致无法完全满足，尽力逼近并在响应中由调用方检查。
    """
    keys = ("sleep", "hrv", "spo2", "activity")
    lowers = {k: float(p["weights"][k]["range"][0]) for k in keys}
    uppers = {k: float(p["weights"][k]["range"][1]) for k in keys}
    w = {k: float(p["weights"][k]["value"]) for k in keys}
    for _ in range(12):
        s = sum(w.values())
        if s <= 0:
            w = {k: (lowers[k] + uppers[k]) / 2.0 for k in keys}
        else:
            w = {k: w[k] / s for k in keys}
        ok = True
        for k in keys:
            if w[k] < lowers[k] - 1e-9 or w[k] > uppers[k] + 1e-9:
                ok = False
                w[k] = min(uppers[k], max(lowers[k], w[k]))
        if ok:
            break
    s = sum(w.values())
    w = {k: w[k] / s for k in keys}
    for k in keys:
        p["weights"][k]["value"] = float(w[k])


def _confidence(
    *,
    imputed: list[str],
    personal_weight: float,
    hours_since_last_sleep_missing: bool = False,
) -> float:
    """
    综合缺失 imputation 与个人基线占比估计置信度。

    Args:
        imputed: 被兜底填充的字段名列表。
        personal_weight: ``BaselineModel.get_baseline`` 返回的个人份额 ∈[0,1]。
        hours_since_last_sleep_missing: 若请求未传入 hours_since_last_sleep，额外扣 0.1。
    """
    penalty_missing = 0.14 * len(imputed)
    penalty_cold = 0.22 * (1.0 - float(personal_weight))
    penalty_no_sleep_time = 0.1 if hours_since_last_sleep_missing else 0.0
    c = 1.0 - penalty_missing - penalty_cold - penalty_no_sleep_time
    return float(max(0.0, min(1.0, c)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时可选灌入模拟用户基线，便于即刻调用演示接口。"""
    _sync_window()
    seed_baseline_for_mock_users(baseline_model)
    yield


app = FastAPI(title="Vitasleep Alg Service", version="1.0.0", lifespan=lifespan)


@app.post("/calculate/battery", response_model=BatteryResponse)
def calculate_battery(req: BatteryRequest) -> BatteryResponse:
    """
    根据最新指标与 Hours since sleep 计算机体电量。
    """
    calc = BatteryCalculator(runtime_params, baseline_model)
    metrics_dict = req.metrics.model_dump()
    hours = req.hours_since_last_sleep if req.hours_since_last_sleep is not None else 8.0
    raw = calc.calculate(req.user_id, metrics_dict, hours)

    pers = float(raw["baseline_snapshot"]["personal_weight"])
    conf = _confidence(
        imputed=list(raw["imputed_fields"]),
        personal_weight=pers,
        hours_since_last_sleep_missing=(req.hours_since_last_sleep is None),
    )

    return BatteryResponse(
        user_id=raw["user_id"],
        battery=raw["battery"],
        raw_battery=raw["raw_battery"],
        decay_factor=raw["decay_factor"],
        hours_since_last_sleep=raw["hours_since_last_sleep"],
        components=raw["components"],
        weights_used=raw["weights_used"],
        imputed_fields=raw["imputed_fields"],
        baseline_snapshot=raw["baseline_snapshot"],
        confidence=conf,
    )


@app.post("/baseline/update", response_model=BaselineUpdateResponse)
def baseline_update(req: BaselineUpdateRequest) -> BaselineUpdateResponse:
    """写入新的历史日数据以更新滚动基线。"""
    payloads = []
    for r in req.records:
        payloads.append({k: getattr(r, k) for k in METRIC_KEYS})
    info = baseline_model.update({"user_id": req.user_id, "records": payloads})
    return BaselineUpdateResponse(
        user_id=info["user_id"],
        accepted_rows=info["accepted_rows"],
        window_days=info["window_days"],
        total_stored=info["total_stored"],
    )


@app.get("/baseline/{user_id}", response_model=BaselineGetResponse)
def baseline_get(user_id: str) -> BaselineGetResponse:
    """查询当前混合基线（均值 / 标准差）。"""
    bl = baseline_model.get_baseline(user_id)
    metrics = {k: MetricBaseline(mean=v["mean"], std=v["std"]) for k, v in bl["metrics"].items()}
    return BaselineGetResponse(
        user_id=bl["user_id"],
        metrics=metrics,
        days_in_window=bl["days_in_window"],
        personal_weight=bl["personal_weight"],
        population_fallback=bl["population_fallback"],
    )


@app.post("/params/update", response_model=ParamsResponse)
def params_update(req: ParamsUpdateRequest) -> ParamsResponse:
    """
    校准 Agent 推送的参数增量；权重自动投影到合法区间并维持总和 1。
    """
    global runtime_params
    p = copy.deepcopy(runtime_params)

    if req.decay_rate is not None:
        lo, hi = p["decay_rate"]["range"]
        v = float(req.decay_rate)
        if v < lo or v > hi:
            raise HTTPException(status_code=422, detail=f"decay_rate out of range [{lo}, {hi}]")
        p["decay_rate"]["value"] = v

    if req.baseline_window_days is not None:
        lo, hi = p["baseline_window_days"]["range"]
        v = int(req.baseline_window_days)
        if v < int(lo) or v > int(hi):
            raise HTTPException(
                status_code=422,
                detail=f"baseline_window_days out of range [{int(lo)}, {int(hi)}]",
            )
        p["baseline_window_days"]["value"] = v

    if req.weights is not None and len(req.weights) > 0:
        for k, entry in req.weights.items():
            if k not in p["weights"]:
                raise HTTPException(status_code=422, detail=f"unknown weight key: {k}")
            lo, hi = p["weights"][k]["range"]
            val = float(entry.value)
            if val < lo or val > hi:
                raise HTTPException(status_code=422, detail=f"weight {k} out of range [{lo}, {hi}]")
            p["weights"][k]["value"] = val
        _clip_renormalize_weights(p)

    runtime_params = p
    _sync_window()
    return ParamsResponse(params=copy.deepcopy(runtime_params))


@app.get("/params", response_model=ParamsResponse)
def params_get() -> ParamsResponse:
    """返回全部可调参数当前值与合法区间。"""
    return ParamsResponse(params=copy.deepcopy(runtime_params))


# -----------------------------------------------------------------------------
# 本地启动（命令行）
# -----------------------------------------------------------------------------
# uvicorn main:app --reload --port 8001
