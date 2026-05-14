"""
FastAPI 统一入口：电池评分、睡眠质量、心血管健康、疲劳评估、基线维护、参数校准。

启动示例::

    uvicorn main:app --reload --port 8001

Health Connect 字段对应：
  resting_hr          ← HeartRate (resting)
  hrv_rmssd           ← HeartRateVariabilityRmssd
  hrv_sdnn            ← HeartRateVariabilitySdnn
  systolic/diastolic  ← BloodPressure
  spo2                ← OxygenSaturation
  deep/light/rem/awake_sleep_minutes ← SleepStage（各分期分钟数）
  steps               ← Steps
  active_calories     ← ActiveCaloriesBurned
  active_minutes      ← ExerciseSession 或自行折算
"""

from __future__ import annotations

import copy
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from baseline import BaselineModel, METRIC_KEYS
from battery import BatteryCalculator
from cardio import compute_cardio_index
from fatigue import compute_fatigue_index
from mock_data import seed_baseline_for_mock_users
from params import clone_tunable_params
from sleep_scorer import compute_sleep_score

# ---------------------------------------------------------------------------
# 公共指标载荷（所有算法端点共用）
# ---------------------------------------------------------------------------

_TOTAL_METRIC_FIELDS = 13  # MetricPayload 中可 imputed 的字段数


class MetricPayload(BaseModel):
    """
    用户当前全量生理指标（Health Connect 字段对齐）。
    所有字段允许为 null；缺失时各算法模块用基线均值兜底并降低置信度。
    """

    # 心率 / HRV
    resting_hr:    Optional[float] = Field(None, description="静息心率 bpm")
    hrv_rmssd:     Optional[float] = Field(None, description="HRV RMSSD ms（副交感）")
    hrv_sdnn:      Optional[float] = Field(None, description="HRV SDNN ms（总变异性）")
    # 血压
    systolic:      Optional[float] = Field(None, description="收缩压 mmHg")
    diastolic:     Optional[float] = Field(None, description="舒张压 mmHg")
    # 血氧
    spo2:          Optional[float] = Field(None, description="血氧饱和度 %")
    # 睡眠分期（Health Connect SleepStage，单位：分钟）
    deep_sleep_minutes:  Optional[float] = Field(None, description="深睡时长 min")
    light_sleep_minutes: Optional[float] = Field(None, description="浅睡时长 min")
    rem_sleep_minutes:   Optional[float] = Field(None, description="REM 时长 min")
    awake_minutes:       Optional[float] = Field(None, description="睡眠期间清醒时长 min")
    # 活动
    steps:          Optional[float] = Field(None, description="步数")
    active_calories: Optional[float] = Field(None, description="活动消耗卡路里 kcal")
    active_minutes: Optional[float] = Field(None, description="活动分钟数")

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class BatteryRequest(BaseModel):
    """POST /calculate/battery  &  POST /calculate/fatigue 请求体。"""

    user_id: str = Field(..., min_length=1)
    hours_since_last_sleep: Optional[float] = Field(None, ge=0.0, le=240.0,
        description="距上次起床小时数；null 时以 8.0 兜底，置信度额外扣 0.1")
    metrics: MetricPayload

    model_config = {"extra": "ignore"}


class MetricsOnlyRequest(BaseModel):
    """POST /calculate/sleep  &  POST /calculate/cardio 请求体（不需要时间字段）。"""

    user_id: str = Field(..., min_length=1)
    metrics: MetricPayload

    model_config = {"extra": "ignore"}


class DayRecord(BaseModel):
    """单日历史记录；字段可部分缺失。"""

    resting_hr:          Optional[float] = None
    hrv_rmssd:           Optional[float] = None
    hrv_sdnn:            Optional[float] = None
    systolic:            Optional[float] = None
    diastolic:           Optional[float] = None
    spo2:                Optional[float] = None
    deep_sleep_minutes:  Optional[float] = None
    light_sleep_minutes: Optional[float] = None
    rem_sleep_minutes:   Optional[float] = None
    awake_minutes:       Optional[float] = None
    steps:               Optional[float] = None
    active_calories:     Optional[float] = None
    active_minutes:      Optional[float] = None

    model_config = {"extra": "ignore"}


class BaselineUpdateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    records: list[DayRecord] = Field(..., min_length=1)


class WeightEntryUpdate(BaseModel):
    value: float


class ParamsUpdateRequest(BaseModel):
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
            raise ValueError("baseline_window_days must be in [1, 30]")
        return v


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------

class BatteryResponse(BaseModel):
    user_id: str
    battery: float
    raw_battery: float
    decay_factor: float
    hours_since_last_sleep: float
    components: dict[str, Any]
    weights_used: dict[str, float]
    imputed_fields: list[str]
    baseline_snapshot: dict[str, Any]
    confidence: float = Field(..., ge=0.0, le=1.0)


class SleepResponse(BaseModel):
    user_id: str
    sleep_score: float = Field(..., ge=0.0, le=100.0)
    detail: dict[str, Any]
    imputed_fields: list[str]
    confidence: float = Field(..., ge=0.0, le=1.0)


class CardioResponse(BaseModel):
    user_id: str
    cardio_index: float = Field(..., ge=0.0, le=100.0,
        description="心血管健康指数 0~100，越高越好")
    detail: dict[str, Any]
    imputed_fields: list[str]
    confidence: float = Field(..., ge=0.0, le=1.0)


class FatigueResponse(BaseModel):
    user_id: str
    fatigue_index: float = Field(..., ge=0.0, le=100.0,
        description="疲劳指数 0~100，越高越疲劳")
    level: str = Field(..., description="low / moderate / high / severe")
    detail: dict[str, float]
    confidence: float = Field(..., ge=0.0, le=1.0)


class MetricBaseline(BaseModel):
    mean: float
    std: float


class BaselineUpdateResponse(BaseModel):
    user_id: str
    accepted_rows: int
    window_days: int
    total_stored: int


class BaselineGetResponse(BaseModel):
    user_id: str
    metrics: dict[str, MetricBaseline]
    days_in_window: int
    personal_weight: float
    population_fallback: bool


class ParamsResponse(BaseModel):
    params: dict[str, Any]


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

baseline_model = BaselineModel(window_days=int(clone_tunable_params()["baseline_window_days"]["value"]))
runtime_params: dict[str, Any] = clone_tunable_params()


def _sync_window() -> None:
    baseline_model.set_window_days(int(runtime_params["baseline_window_days"]["value"]))


def _clip_renormalize_weights(p: dict[str, Any]) -> None:
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
    total_fields: int = _TOTAL_METRIC_FIELDS,
    hours_since_last_sleep_missing: bool = False,
) -> float:
    """
    置信度估算。

    最大字段惩罚上限固定为 0.70，按实际字段数均摊每字段权重，
    避免字段扩展后惩罚过猛。

    Args:
        imputed: 被兜底的字段名列表。
        personal_weight: 个人基线占比 ∈ [0, 1]。
        total_fields: 该端点涉及的可 imputed 字段总数（用于归一化惩罚力度）。
        hours_since_last_sleep_missing: hours 字段缺失时额外扣 0.1。
    """
    penalty_per_field = 0.70 / max(1, total_fields)
    penalty_missing   = penalty_per_field * len(imputed)
    penalty_cold      = 0.22 * (1.0 - float(personal_weight))
    penalty_no_time   = 0.10 if hours_since_last_sleep_missing else 0.0
    c = 1.0 - penalty_missing - penalty_cold - penalty_no_time
    return float(max(0.0, min(1.0, c)))


def _fatigue_level(index: float) -> str:
    if index < 25:
        return "low"
    if index < 50:
        return "moderate"
    if index < 75:
        return "high"
    return "severe"


# ---------------------------------------------------------------------------
# 应用生命周期
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _sync_window()
    seed_baseline_for_mock_users(baseline_model)
    yield


app = FastAPI(title="Vitasleep Alg Service", version="2.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# AL-04  机体电量
# ---------------------------------------------------------------------------

@app.post("/calculate/battery", response_model=BatteryResponse)
def calculate_battery(req: BatteryRequest) -> BatteryResponse:
    """根据全量生理指标计算机体电量（含睡眠分期与时间衰减）。"""
    calc   = BatteryCalculator(runtime_params, baseline_model)
    hours  = req.hours_since_last_sleep if req.hours_since_last_sleep is not None else 8.0
    raw    = calc.calculate(req.user_id, req.metrics.model_dump(), hours)

    pers   = float(raw["baseline_snapshot"]["personal_weight"])
    conf   = _confidence(
        imputed=list(raw["imputed_fields"]),
        personal_weight=pers,
        hours_since_last_sleep_missing=(req.hours_since_last_sleep is None),
    )

    return BatteryResponse(
        user_id                =raw["user_id"],
        battery                =raw["battery"],
        raw_battery            =raw["raw_battery"],
        decay_factor           =raw["decay_factor"],
        hours_since_last_sleep =raw["hours_since_last_sleep"],
        components             =raw["components"],
        weights_used           =raw["weights_used"],
        imputed_fields         =raw["imputed_fields"],
        baseline_snapshot      =raw["baseline_snapshot"],
        confidence             =conf,
    )


# ---------------------------------------------------------------------------
# AL-05  睡眠质量
# ---------------------------------------------------------------------------

@app.post("/calculate/sleep", response_model=SleepResponse)
def calculate_sleep(req: MetricsOnlyRequest) -> SleepResponse:
    """
    基于四分期时长（深睡/浅睡/REM/清醒）计算综合睡眠质量得分 0~100。
    数据来源：Health Connect SleepStage。
    """
    bl      = baseline_model.get_baseline(req.user_id)
    bm      = bl["metrics"]
    imputed: list[str] = []
    m       = req.metrics

    score, detail = compute_sleep_score(
        deep_minutes =m.deep_sleep_minutes,
        light_minutes=m.light_sleep_minutes,
        rem_minutes  =m.rem_sleep_minutes,
        awake_minutes=m.awake_minutes,
        baseline_metrics=bm,
        imputed=imputed,
    )

    conf = _confidence(
        imputed=imputed,
        personal_weight=float(bl["personal_weight"]),
        total_fields=4,
    )

    return SleepResponse(
        user_id       =req.user_id,
        sleep_score   =round(score, 1),
        detail        =detail,
        imputed_fields=imputed,
        confidence    =conf,
    )


# ---------------------------------------------------------------------------
# AL-06  心血管健康指数
# ---------------------------------------------------------------------------

@app.post("/calculate/cardio", response_model=CardioResponse)
def calculate_cardio(req: MetricsOnlyRequest) -> CardioResponse:
    """
    综合 HRV（RMSSD + SDNN）、血压（MAP + 脉压差）与静息心率，
    输出心血管健康指数（CHI）0~100。
    """
    bl      = baseline_model.get_baseline(req.user_id)
    bm      = bl["metrics"]
    imputed: list[str] = []
    m       = req.metrics

    chi, detail = compute_cardio_index(
        resting_hr=m.resting_hr,
        hrv_rmssd =m.hrv_rmssd,
        hrv_sdnn  =m.hrv_sdnn,
        systolic  =m.systolic,
        diastolic =m.diastolic,
        baseline_metrics=bm,
        imputed=imputed,
    )

    conf = _confidence(
        imputed=imputed,
        personal_weight=float(bl["personal_weight"]),
        total_fields=5,
    )

    return CardioResponse(
        user_id       =req.user_id,
        cardio_index  =round(chi, 1),
        detail        =detail,
        imputed_fields=imputed,
        confidence    =conf,
    )


# ---------------------------------------------------------------------------
# AL-08  实时疲劳评估
# ---------------------------------------------------------------------------

@app.post("/calculate/fatigue", response_model=FatigueResponse)
def calculate_fatigue(req: BatteryRequest) -> FatigueResponse:
    """
    融合 HRV 抑制、睡眠不足、时间压力与电量亏空，输出疲劳指数 0~100。
    内部先调用电量计算（AL-04）以获取睡眠得分与电量。
    """
    calc  = BatteryCalculator(runtime_params, baseline_model)
    hours = req.hours_since_last_sleep if req.hours_since_last_sleep is not None else 8.0
    raw   = calc.calculate(req.user_id, req.metrics.model_dump(), hours)

    bl  = baseline_model.get_baseline(req.user_id)
    bm  = bl["metrics"]

    fatigue_index, detail = compute_fatigue_index(
        hrv_rmssd               =req.metrics.hrv_rmssd,
        hrv_rmssd_baseline_mean =float(bm["hrv_rmssd"]["mean"]),
        hrv_rmssd_baseline_std  =float(bm["hrv_rmssd"]["std"]),
        sleep_score             =raw["components"]["sleep"]["score"],
        battery                 =raw["battery"],
        hours_since_last_sleep  =hours,
    )

    conf = _confidence(
        imputed=list(raw["imputed_fields"]),
        personal_weight=float(bl["personal_weight"]),
        hours_since_last_sleep_missing=(req.hours_since_last_sleep is None),
    )

    return FatigueResponse(
        user_id      =req.user_id,
        fatigue_index=round(fatigue_index, 1),
        level        =_fatigue_level(fatigue_index),
        detail       =detail,
        confidence   =conf,
    )


# ---------------------------------------------------------------------------
# 基线维护
# ---------------------------------------------------------------------------

@app.post("/baseline/update", response_model=BaselineUpdateResponse)
def baseline_update(req: BaselineUpdateRequest) -> BaselineUpdateResponse:
    """写入新的历史日数据以更新滚动基线。"""
    payloads = [{k: getattr(r, k) for k in METRIC_KEYS} for r in req.records]
    info = baseline_model.update({"user_id": req.user_id, "records": payloads})
    return BaselineUpdateResponse(
        user_id      =info["user_id"],
        accepted_rows=info["accepted_rows"],
        window_days  =info["window_days"],
        total_stored =info["total_stored"],
    )


@app.get("/baseline/{user_id}", response_model=BaselineGetResponse)
def baseline_get(user_id: str) -> BaselineGetResponse:
    """查询当前混合基线（均值 / 标准差）。"""
    bl      = baseline_model.get_baseline(user_id)
    metrics = {k: MetricBaseline(mean=v["mean"], std=v["std"])
               for k, v in bl["metrics"].items()}
    return BaselineGetResponse(
        user_id           =bl["user_id"],
        metrics           =metrics,
        days_in_window    =bl["days_in_window"],
        personal_weight   =bl["personal_weight"],
        population_fallback=bl["population_fallback"],
    )


# ---------------------------------------------------------------------------
# 参数校准
# ---------------------------------------------------------------------------

@app.post("/params/update", response_model=ParamsResponse)
def params_update(req: ParamsUpdateRequest) -> ParamsResponse:
    """校准 Agent 推送的参数增量；权重自动投影到合法区间并维持总和 1。"""
    global runtime_params
    p = copy.deepcopy(runtime_params)

    if req.decay_rate is not None:
        lo, hi = p["decay_rate"]["range"]
        v = float(req.decay_rate)
        if v < lo or v > hi:
            raise HTTPException(status_code=422,
                                detail=f"decay_rate out of range [{lo}, {hi}]")
        p["decay_rate"]["value"] = v

    if req.baseline_window_days is not None:
        lo, hi = p["baseline_window_days"]["range"]
        v = int(req.baseline_window_days)
        if v < int(lo) or v > int(hi):
            raise HTTPException(status_code=422,
                                detail=f"baseline_window_days out of range [{int(lo)}, {int(hi)}]")
        p["baseline_window_days"]["value"] = v

    if req.weights is not None and len(req.weights) > 0:
        for k, entry in req.weights.items():
            if k not in p["weights"]:
                raise HTTPException(status_code=422, detail=f"unknown weight key: {k}")
            lo, hi = p["weights"][k]["range"]
            val = float(entry.value)
            if val < lo or val > hi:
                raise HTTPException(status_code=422,
                                    detail=f"weight {k} out of range [{lo}, {hi}]")
            p["weights"][k]["value"] = val
        _clip_renormalize_weights(p)

    runtime_params = p
    _sync_window()
    return ParamsResponse(params=copy.deepcopy(runtime_params))


@app.get("/params", response_model=ParamsResponse)
def params_get() -> ParamsResponse:
    """返回全部可调参数当前值与合法区间。"""
    return ParamsResponse(params=copy.deepcopy(runtime_params))


# ---------------------------------------------------------------------------
# uvicorn main:app --reload --port 8001
# ---------------------------------------------------------------------------
