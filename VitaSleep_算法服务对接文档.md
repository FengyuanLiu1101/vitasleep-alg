# VitaSleep 算法服务对接文档

**面向：后端同学**
**服务负责人：算法线**
**版本：V1.0**
**基准日期：2026-05-14**

---

## 一、服务概览

算法服务基于 FastAPI 封装，语言无关，后端通过标准 HTTP 接口调用。

**启动方式：**
```bash
cd vitasleep/Alg
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

**接口文档页面（启动后访问）：**
```
http://服务器IP:8001/docs
```

---

## 二、接口清单

| 接口 | 方法 | 功能 | 调用时机 |
|------|------|------|----------|
| `/calculate/battery` | POST | 计算身体电量 | 每分钟调用一次 |
| `/baseline/update` | POST | 更新用户历史基线 | 每天调用一次（用当天汇总数据） |
| `/baseline/{user_id}` | GET | 查询用户当前基线 | 按需查询 |
| `/params/update` | POST | 校准Agent更新权重参数 | 仅校准Agent触发时调用 |
| `/params` | GET | 查询当前可调参数 | 按需查询 |

---

## 三、核心接口详细说明

### 3.1 POST `/calculate/battery` — 计算身体电量

**请求体：**
```json
{
  "user_id": "用户唯一ID",
  "hours_since_last_sleep": 8.0,
  "metrics": {
    "resting_hr": 62.0,
    "hrv_rmssd": 45.0,
    "spo2": 97.0,
    "deep_sleep_ratio": 0.21,
    "active_minutes": 40.0
  }
}
```

**字段说明：**

| 字段 | 类型 | 是否必填 | 说明 |
|------|------|----------|------|
| `user_id` | string | ✅ 必填 | 用户唯一标识 |
| `hours_since_last_sleep` | float | ❌ 可为null | 距上次睡眠结束的小时数；null时内部用8.0兜底，置信度-0.1 |
| `metrics.resting_hr` | float | ❌ 可为null | 静息心率 bpm；null时用用户基线均值兜底 |
| `metrics.hrv_rmssd` | float | ❌ 可为null | HRV RMSSD ms；null时用用户基线均值兜底 |
| `metrics.spo2` | float | ❌ 可为null | 血氧饱和度 %；null时用用户基线均值兜底 |
| `metrics.deep_sleep_ratio` | float | ❌ 可为null | 深睡占总睡眠比例 0~1；null时用用户基线均值兜底 |
| `metrics.active_minutes` | float | ❌ 可为null | 当天累计活动分钟数；null时用用户基线均值兜底 |

**⚠️ 重要：缺失字段请传 `null`，不要用旧值填充。** 算法需要知道哪些数据是真实缺失的，才能正确降低置信度。

**返回体：**
```json
{
  "user_id": "用户ID",
  "battery": 72.5,
  "raw_battery": 75.0,
  "decay_factor": 0.97,
  "hours_since_last_sleep": 8.0,
  "components": {
    "sleep": {"score": 80.0, "metric": "deep_sleep_ratio"},
    "hrv": {
      "score": 70.0,
      "detail": {"resting_hr": 65.0, "hrv_rmssd": 75.0}
    },
    "spo2": {"score": 90.0},
    "activity": {"score": 60.0}
  },
  "weights_used": {
    "sleep": 0.40,
    "hrv": 0.30,
    "spo2": 0.15,
    "activity": 0.15
  },
  "imputed_fields": [],
  "baseline_snapshot": {
    "days_in_window": 7,
    "personal_weight": 1.0
  },
  "confidence": 0.85
}
```

**返回字段说明：**

| 字段 | 说明 |
|------|------|
| `battery` | 最终电量值 0~100（含时间衰减） |
| `raw_battery` | 未衰减的原始电量 0~100 |
| `decay_factor` | 时间衰减系数 0~1 |
| `imputed_fields` | 被兜底填充的字段列表（空数组=数据完整） |
| `confidence` | 置信度 0~1，数据缺失越多越低 |

**存入 `health_metrics` 表时建议的 `valid_until`：**

```
battery       → 当前时间 + 1分钟
```

---

### 3.2 POST `/baseline/update` — 更新用户基线

**调用时机：每天调用一次，传入当天汇总的日级指标。**

**请求体：**
```json
{
  "user_id": "用户ID",
  "records": [
    {
      "resting_hr": 62.0,
      "hrv_rmssd": 45.0,
      "spo2": 97.0,
      "deep_sleep_ratio": 0.21,
      "active_minutes": 40.0
    }
  ]
}
```

`records` 支持传多条（比如补历史数据时一次传7条）。字段均可为 null，有效字段会被算入基线。

**返回体：**
```json
{
  "user_id": "用户ID",
  "accepted_rows": 1,
  "window_days": 7,
  "total_stored": 5
}
```

---

### 3.3 POST `/params/update` — 校准Agent更新参数

**此接口仅供大模型校准Agent调用，后端不需要主动调用。**

**请求体示例（部分更新，未传字段保持不变）：**
```json
{
  "weights": {
    "sleep": {"value": 0.45},
    "hrv": {"value": 0.25}
  },
  "decay_rate": 0.025
}
```

**可调参数范围：**

| 参数 | 当前默认值 | 合法范围 | 说明 |
|------|-----------|----------|------|
| `weights.sleep` | 0.40 | 0.25 ~ 0.55 | 睡眠在电量中的权重 |
| `weights.hrv` | 0.30 | 0.15 ~ 0.45 | HRV在电量中的权重 |
| `weights.spo2` | 0.15 | 0.05 ~ 0.25 | 血氧在电量中的权重 |
| `weights.activity` | 0.15 | 0.05 ~ 0.25 | 活动量在电量中的权重 |
| `decay_rate` | 0.02 | 0.01 ~ 0.04 | 时间衰减速率 |
| `baseline_window_days` | 7 | 3 ~ 14 | 基线建模滚动窗口天数 |

**注意：四项权重之和必须为1，服务端会自动归一化处理。**

---

## 四、Google Health API 数据转换规范

**后端从 Google Health API 拿到数据后，需按以下规则转换后再调用算法接口：**

| 算法入参字段 | Google API 数据源 | 转换规则 |
|-------------|-----------------|----------|
| `resting_hr` | `dailyRestingHeartRate` | 直接使用当日静息心率值 |
| `hrv_rmssd` | `dailyHeartRateVariability` | 直接使用当日HRV汇总值 |
| `spo2` | `dailyOxygenSaturation` | 使用当日均值 |
| `deep_sleep_ratio` | `sleep` 分期数据 | 深睡时长 / 总睡眠时长，结果为0~1 |
| `active_minutes` | `activeZoneMinutes` | 当天累计值 |
| `hours_since_last_sleep` | `sleep` 数据 | 当前时间 - 上次睡眠结束时间，单位小时 |

**Google API 没有数据时，对应字段传 `null`，不要用上一次的值填充。**

---

## 五、错误码说明

| HTTP状态码 | 含义 |
|-----------|------|
| 200 | 正常返回 |
| 422 | 请求参数不合法（如权重超出范围） |
| 500 | 算法内部错误 |

---

## 六、注意事项

1. **服务是无状态的**：基线数据存在服务内存中，服务重启后基线清空。后续需要对接 `user_profiles` 持久化，待联调阶段对齐。
2. **调用超时**：建议设置超时时间为 **3秒**，算法计算通常在100ms内完成。
3. **并发**：当前为单进程，高并发场景需要后端做队列或多实例部署（V1.0暂不需要考虑）。
4. **新用户冷启动**：没有历史基线时自动使用人群均值兜底，`confidence` 会偏低，属于正常现象。
