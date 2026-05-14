# VitaSleep 算法服务对接文档

**面向：后端同学**
**服务负责人：算法线**
**版本：V2.0**
**基准日期：2026-05-14**

---

## 一、服务概览

算法服务基于 FastAPI 封装，语言无关，后端通过标准 HTTP 接口调用。
数据源已全面对齐 **Google Health Connect**，后端从 Health Connect 读取数据后，按本文规则转换字段后调用接口即可。

**启动方式：**
```bash
cd vitasleep/Alg
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

**交互式文档（启动后访问）：**
```
http://服务器IP:8001/docs
```

---

## 二、接口清单

| 接口 | 方法 | 功能（需求编号） | 典型调用时机 |
|------|------|----------|------------|
| `/calculate/battery` | POST | 机体电量（AL-04） | 每分钟或用户打开 App 时 |
| `/calculate/sleep` | POST | 睡眠质量（AL-05） | 用户早晨起床后调用一次 |
| `/calculate/cardio` | POST | 心血管健康指数（AL-06） | 每天调用一次 |
| `/calculate/fatigue` | POST | 实时疲劳评估（AL-08） | 与电量同频 |
| `/baseline/update` | POST | 更新用户历史基线（AL-07） | 每天调用一次（当天汇总） |
| `/baseline/{user_id}` | GET | 查询用户当前基线 | 按需查询 |
| `/params/update` | POST | 校准 Agent 更新权重 | 仅校准 Agent 触发 |
| `/params` | GET | 查询当前可调参数 | 按需查询 |

---

## 三、公共字段说明：MetricPayload

以下所有计算接口的 `metrics` 字段均使用同一结构，**所有字段均可为 `null`**，缺失时算法自动用用户基线均值兜底并降低置信度。

| 字段 | 类型 | Health Connect 数据源 | 单位 |
|------|------|----------------------|------|
| `resting_hr` | float \| null | `HeartRate`（静息） | bpm |
| `hrv_rmssd` | float \| null | `HeartRateVariabilityRmssd` | ms |
| `hrv_sdnn` | float \| null | `HeartRateVariabilitySdnn` | ms |
| `systolic` | float \| null | `BloodPressure.systolic` | mmHg |
| `diastolic` | float \| null | `BloodPressure.diastolic` | mmHg |
| `spo2` | float \| null | `OxygenSaturation` | % |
| `deep_sleep_minutes` | float \| null | `SleepStage` TYPE_DEEP 汇总 | 分钟 |
| `light_sleep_minutes` | float \| null | `SleepStage` TYPE_LIGHT 汇总 | 分钟 |
| `rem_sleep_minutes` | float \| null | `SleepStage` TYPE_REM 汇总 | 分钟 |
| `awake_minutes` | float \| null | `SleepStage` TYPE_AWAKE 汇总 | 分钟 |
| `steps` | float \| null | `Steps` | 步 |
| `active_calories` | float \| null | `ActiveCaloriesBurned` | kcal |
| `active_minutes` | float \| null | `ExerciseSession` 时长 | 分钟 |

> **⚠️ 重要：Health Connect 没有数据时字段传 `null`，不要用上次的值填充。** 算法依靠 `null` 来判断数据是否真实缺失并决定置信度扣减幅度。

---

## 四、核心接口详细说明

### 4.1 POST `/calculate/battery` — 机体电量（AL-04）

**请求体：**
```json
{
  "user_id": "uid_001",
  "hours_since_last_sleep": 8.0,
  "metrics": {
    "resting_hr": 62.0,
    "hrv_rmssd": 45.0,
    "hrv_sdnn": 58.0,
    "systolic": 118.0,
    "diastolic": 76.0,
    "spo2": 97.0,
    "deep_sleep_minutes": 90.0,
    "light_sleep_minutes": 200.0,
    "rem_sleep_minutes": 100.0,
    "awake_minutes": 25.0,
    "steps": 8000.0,
    "active_calories": 350.0,
    "active_minutes": 40.0
  }
}
```

| 字段 | 是否必填 | 说明 |
|------|----------|------|
| `user_id` | ✅ 必填 | 用户唯一标识 |
| `hours_since_last_sleep` | ❌ 可为 null | 距上次起床小时数；null 时以 8.0 兜底，置信度额外扣 0.1 |
| `metrics.*` | ❌ 均可为 null | 见第三节 |

**返回体：**
```json
{
  "user_id": "uid_001",
  "battery": 72.5,
  "raw_battery": 75.0,
  "decay_factor": 0.97,
  "hours_since_last_sleep": 8.0,
  "components": {
    "sleep": {
      "score": 85.0,
      "detail": {
        "total_sleep_hours": 6.58,
        "sleep_efficiency": 0.914,
        "deep_ratio": 0.218,
        "rem_ratio": 0.242,
        "duration_score": 82.0,
        "efficiency_score": 95.0,
        "deep_score": 88.0,
        "rem_score": 91.0
      }
    },
    "hrv": {
      "score": 70.0,
      "detail": {
        "resting_hr_score": 68.0,
        "hrv_rmssd_score": 72.0,
        "hrv_sdnn_score": 70.0,
        "bp_map_score": 70.0,
        "map_mmhg": 90.0
      }
    },
    "spo2": {"score": 90.0},
    "activity": {
      "score": 65.0,
      "detail": {
        "steps_score": 68.0,
        "active_calories_score": 62.0,
        "active_minutes_score": 65.0
      }
    }
  },
  "weights_used": {"sleep": 0.40, "hrv": 0.30, "spo2": 0.15, "activity": 0.15},
  "imputed_fields": [],
  "baseline_snapshot": {"days_in_window": 7, "personal_weight": 1.0},
  "confidence": 0.88
}
```

| 返回字段 | 说明 |
|---------|------|
| `battery` | 最终电量 0~100（含时间衰减） |
| `raw_battery` | 未衰减电量 |
| `decay_factor` | 时间衰减系数 0~1 |
| `imputed_fields` | 被兜底填充的字段名列表（空 = 数据完整） |
| `confidence` | 置信度 0~1，缺失越多、基线越短则越低 |

---

### 4.2 POST `/calculate/sleep` — 睡眠质量（AL-05）

**请求体：**
```json
{
  "user_id": "uid_001",
  "metrics": {
    "deep_sleep_minutes": 90.0,
    "light_sleep_minutes": 200.0,
    "rem_sleep_minutes": 100.0,
    "awake_minutes": 25.0
  }
}
```

> 仅需睡眠相关字段，其他字段传入不会报错（会被忽略）。

**返回体：**
```json
{
  "user_id": "uid_001",
  "sleep_score": 86.5,
  "detail": {
    "total_sleep_hours": 6.58,
    "sleep_efficiency": 0.914,
    "deep_ratio": 0.218,
    "rem_ratio": 0.242,
    "duration_score": 82.0,
    "efficiency_score": 95.0,
    "deep_score": 88.0,
    "rem_score": 91.0
  },
  "imputed_fields": [],
  "confidence": 0.80
}
```

**算法说明：**

| 维度 | 权重 | 理想范围 |
|------|------|---------|
| 总时长 | 30% | 7~9 小时 |
| 睡眠效率 | 30% | > 85% |
| 深睡比例 | 25% | 15%~25% |
| REM 比例 | 15% | 20%~25% |

---

### 4.3 POST `/calculate/cardio` — 心血管健康指数（AL-06）

**请求体：**
```json
{
  "user_id": "uid_001",
  "metrics": {
    "resting_hr": 62.0,
    "hrv_rmssd": 45.0,
    "hrv_sdnn": 58.0,
    "systolic": 118.0,
    "diastolic": 76.0
  }
}
```

**返回体：**
```json
{
  "user_id": "uid_001",
  "cardio_index": 76.0,
  "detail": {
    "hrv_composite": 72.0,
    "hrv_rmssd_score": 70.0,
    "hrv_sdnn_score": 74.0,
    "bp_composite": 80.0,
    "map_mmhg": 90.0,
    "pulse_pressure_mmhg": 42.0,
    "map_score": 83.0,
    "pulse_score": 75.0,
    "hr_score": 78.0
  },
  "imputed_fields": [],
  "confidence": 0.80
}
```

**算法说明：**

| 组件 | 权重 | 子指标 |
|------|------|--------|
| HRV 复合 | 40% | RMSSD（45%）+ SDNN（55%） |
| 血压复合 | 35% | MAP（60%）+ 脉压差（40%） |
| 静息心率 | 25% | 与个人基线双侧对比 |

> MAP（平均动脉压）= 舒张压 + (收缩压 - 舒张压) / 3，理想约 70~100 mmHg。

---

### 4.4 POST `/calculate/fatigue` — 实时疲劳评估（AL-08）

与 `/calculate/battery` 同一请求体结构，内部会先算电量再融合疲劳信号。

**请求体：** 同 4.1 节。

**返回体：**
```json
{
  "user_id": "uid_001",
  "fatigue_index": 32.5,
  "level": "moderate",
  "detail": {
    "hrv_suppression_signal": 0.42,
    "sleep_deficit_signal": 0.15,
    "time_pressure_signal": 0.30,
    "battery_deficit_signal": 0.28
  },
  "confidence": 0.88
}
```

| 返回字段 | 说明 |
|---------|------|
| `fatigue_index` | 疲劳指数 0~100，**越高越疲劳** |
| `level` | `low`(<25) / `moderate`(<50) / `high`(<75) / `severe`(≥75) |
| `detail.*_signal` | 各路信号强度 0~1，1 = 该维度最疲劳 |

**算法说明：**

| 信号 | 权重 | 含义 |
|------|------|------|
| HRV 抑制 | 35% | RMSSD 低于基线 → 交感神经主导 |
| 睡眠不足 | 30% | 睡眠质量得分越低越疲劳 |
| 时间压力 | 20% | 距起床时间越长，稳态睡眠压力越大 |
| 电量亏空 | 15% | 综合生理储备不足 |

---

### 4.5 POST `/baseline/update` — 更新用户基线（AL-07）

**调用时机：每天调用一次，传入当天汇总的日级指标。**

**请求体：**
```json
{
  "user_id": "uid_001",
  "records": [
    {
      "resting_hr": 62.0,
      "hrv_rmssd": 45.0,
      "hrv_sdnn": 58.0,
      "systolic": 118.0,
      "diastolic": 76.0,
      "spo2": 97.0,
      "deep_sleep_minutes": 90.0,
      "light_sleep_minutes": 200.0,
      "rem_sleep_minutes": 100.0,
      "awake_minutes": 25.0,
      "steps": 8000.0,
      "active_calories": 350.0,
      "active_minutes": 40.0
    }
  ]
}
```

`records` 支持传多条（如补历史数据时一次传 7 条）。字段均可为 null，有效字段才会计入基线。

**返回体：**
```json
{
  "user_id": "uid_001",
  "accepted_rows": 1,
  "window_days": 7,
  "total_stored": 5
}
```

---

### 4.6 POST `/params/update` — 校准 Agent 更新参数

**此接口仅供大模型校准 Agent 调用，后端不需要主动调用。**

```json
{
  "weights": {
    "sleep": {"value": 0.45},
    "hrv":   {"value": 0.25}
  },
  "decay_rate": 0.025
}
```

| 参数 | 默认值 | 合法范围 |
|------|--------|---------|
| `weights.sleep` | 0.40 | [0.25, 0.55] |
| `weights.hrv` | 0.30 | [0.15, 0.45] |
| `weights.spo2` | 0.15 | [0.05, 0.25] |
| `weights.activity` | 0.15 | [0.05, 0.25] |
| `decay_rate` | 0.02 | [0.01, 0.04] |
| `baseline_window_days` | 7 | [3, 14] |

四项权重之和必须为 1，服务端自动归一化。

---

## 五、Health Connect 字段转换规范

**后端从 Health Connect 读到数据后，按下表转换再调用算法接口：**

| 算法字段 | Health Connect 数据类型 | 转换规则 |
|---------|------------------------|---------|
| `resting_hr` | `HeartRate` | 当日最低心率均值（静息态） |
| `hrv_rmssd` | `HeartRateVariabilityRmssd` | 当日汇总值 |
| `hrv_sdnn` | `HeartRateVariabilitySdnn` | 当日汇总值 |
| `systolic` | `BloodPressure` | 当日测量均值，取 `.systolicPressure.inMillimetersOfMercury` |
| `diastolic` | `BloodPressure` | 当日测量均值，取 `.diastolicPressure.inMillimetersOfMercury` |
| `spo2` | `OxygenSaturation` | 当日均值，取 `.percentage` × 100 |
| `deep_sleep_minutes` | `SleepStage` | 过滤 `stage == STAGE_TYPE_DEEP`，汇总 duration 转分钟 |
| `light_sleep_minutes` | `SleepStage` | 过滤 `stage == STAGE_TYPE_LIGHT`，汇总 duration 转分钟 |
| `rem_sleep_minutes` | `SleepStage` | 过滤 `stage == STAGE_TYPE_REM`，汇总 duration 转分钟 |
| `awake_minutes` | `SleepStage` | 过滤 `stage == STAGE_TYPE_AWAKE`，汇总 duration 转分钟 |
| `steps` | `Steps` | 当日总步数 `.count` |
| `active_calories` | `ActiveCaloriesBurned` | 当日总消耗 `.inKilocalories` |
| `active_minutes` | `ExerciseSession` | 所有运动记录 duration 之和，转分钟 |
| `hours_since_last_sleep` | `SleepSession` | `当前时间 - 最近一条 SleepSession.endTime`，转小时 |

> **Health Connect 无数据时对应字段传 `null`，禁止用上次缓存值填充。**

---

## 六、典型调用流程

```
用户打开 App
    │
    ├─ 读取 Health Connect 数据（当日）
    │
    ├─ POST /calculate/battery     → 展示机体电量
    ├─ POST /calculate/fatigue     → 展示疲劳等级
    │
    └─ （早晨首次打开）
        ├─ POST /calculate/sleep   → 展示昨晚睡眠评分
        ├─ POST /calculate/cardio  → 展示心血管健康指数
        └─ POST /baseline/update   → 将昨日数据写入基线
```

---

## 七、错误码说明

| HTTP 状态码 | 含义 |
|------------|------|
| 200 | 正常返回 |
| 422 | 请求参数不合法（如权重超出范围、user_id 为空） |
| 500 | 算法内部错误 |

---

## 八、注意事项

1. **服务是内存状态**：基线数据存在服务内存中，服务重启后清空。后续需对接 `user_profiles` 持久化，待联调阶段对齐。
2. **调用超时**：建议设置 **3 秒**，算法计算通常在 100ms 内完成。
3. **并发**：当前单进程，高并发需后端做队列或多实例（V2.0 阶段暂不需要考虑）。
4. **冷启动**：新用户无历史基线时自动使用人群均值兜底，`confidence` 偏低属正常。
5. **LF/HF 暂不支持**：Health Connect 不提供原始 RR interval，频域 HRV（LF/HF）本期不实现。
