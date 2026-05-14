# Vitasleep Algorithm Service

基于 Google Health Connect 生理指标的算法评分服务，使用 FastAPI 提供 REST 接口。
覆盖机体电量（AL-04）、睡眠分期质量（AL-05）、心血管健康指数（AL-06）、用户基线建模（AL-07）、实时疲劳评估（AL-08）。

## 算法模块

| 模块 | 端点 | 算法核心 |
|------|------|---------|
| AL-04 机体电量 | `POST /calculate/battery` | 四组分加权融合 + 时间指数衰减 |
| AL-05 睡眠质量 | `POST /calculate/sleep` | 时长30% + 效率30% + 深睡比25% + REM比15% |
| AL-06 心血管健康 | `POST /calculate/cardio` | HRV复合40% + 血压(MAP+脉压差)35% + 心率25% |
| AL-07 用户基线 | `POST /baseline/update` | 7天滚动窗口 + 人群冷启动兜底 |
| AL-08 疲劳评估 | `POST /calculate/fatigue` | HRV抑制35% + 睡眠不足30% + 时间压力20% + 电量亏空15% |

## 项目结构

```
.
├── main.py          # FastAPI 入口，路由与请求/响应模型
├── battery.py       # AL-04 机体电量计算
├── sleep_scorer.py  # AL-05 睡眠分期质量评分
├── cardio.py        # AL-06 心血管健康指数
├── fatigue.py       # AL-08 实时疲劳评估
├── baseline.py      # AL-07 混合基线模型（个人 + 人群）
├── normalizer.py    # 指标 z-score 归一化工具
├── optimizer.py     # 权重白盒优化（SLSQP）
├── params.py        # 可调参数定义与默认值
├── mock_data.py     # 模拟场景数据（演示/测试用）
└── requirements.txt
```

## 快速开始

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

启动后访问 http://localhost:8001/docs 查看交互式 API 文档。

## 输入字段（Health Connect 对齐）

所有计算接口共用同一 `MetricPayload`，**全部字段均可为 `null`**：

| 字段 | Health Connect 来源 | 单位 |
|------|-------------------|------|
| `resting_hr` | `HeartRate` | bpm |
| `hrv_rmssd` | `HeartRateVariabilityRmssd` | ms |
| `hrv_sdnn` | `HeartRateVariabilitySdnn` | ms |
| `systolic` / `diastolic` | `BloodPressure` | mmHg |
| `spo2` | `OxygenSaturation` | % |
| `deep/light/rem/awake_sleep_minutes` | `SleepStage` | 分钟 |
| `steps` | `Steps` | 步 |
| `active_calories` | `ActiveCaloriesBurned` | kcal |
| `active_minutes` | `ExerciseSession` | 分钟 |

## API 示例

### 机体电量
```json
POST /calculate/battery
{
  "user_id": "uid_001",
  "hours_since_last_sleep": 8.0,
  "metrics": {
    "resting_hr": 62, "hrv_rmssd": 45, "hrv_sdnn": 58,
    "systolic": 118, "diastolic": 76, "spo2": 97,
    "deep_sleep_minutes": 90, "light_sleep_minutes": 200,
    "rem_sleep_minutes": 100, "awake_minutes": 25,
    "steps": 8000, "active_calories": 350, "active_minutes": 40
  }
}
```

### 睡眠质量
```json
POST /calculate/sleep
{
  "user_id": "uid_001",
  "metrics": {
    "deep_sleep_minutes": 90, "light_sleep_minutes": 200,
    "rem_sleep_minutes": 100, "awake_minutes": 25
  }
}
```

### 心血管健康指数
```json
POST /calculate/cardio
{
  "user_id": "uid_001",
  "metrics": {
    "resting_hr": 62, "hrv_rmssd": 45, "hrv_sdnn": 58,
    "systolic": 118, "diastolic": 76
  }
}
```

### 疲劳评估
```json
POST /calculate/fatigue
{
  "user_id": "uid_001",
  "hours_since_last_sleep": 10.0,
  "metrics": { ... }
}
```
返回 `fatigue_index`（0~100）和 `level`（low / moderate / high / severe）。

## 可调参数

通过 `POST /params/update` 运行时调整，无需重启：

| 参数 | 默认值 | 合法区间 |
|------|--------|---------|
| `weights.sleep` | 0.40 | [0.25, 0.55] |
| `weights.hrv` | 0.30 | [0.15, 0.45] |
| `weights.spo2` | 0.15 | [0.05, 0.25] |
| `weights.activity` | 0.15 | [0.05, 0.25] |
| `decay_rate` | 0.02 | [0.01, 0.04] |
| `baseline_window_days` | 7 | [3, 14] |
