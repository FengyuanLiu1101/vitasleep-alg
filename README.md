# Vitasleep Algorithm Service

基于生理指标的「机体电量」评分算法服务，使用 FastAPI 提供 REST 接口。

## 功能概述

根据用户的五项生理指标与个人基线，计算 0~100 分的**机体电量（Battery Score）**，并随距上次睡眠的时间做指数衰减。

**评分组成：**

| 维度 | 指标 | 默认权重 |
|------|------|----------|
| 睡眠质量 | `deep_sleep_ratio` | 40% |
| 心率/HRV | `resting_hr` + `hrv_rmssd` | 30% |
| 血氧 | `spo2` | 15% |
| 活动量 | `active_minutes` | 15% |

- 所有指标均允许缺失（`null`），缺失时用个人基线均值兜底，并相应降低置信度
- `hours_since_last_sleep` 可选，缺省时以 8.0 小时兜底，置信度额外扣 0.1
- 基线采用「个人滚动窗口 + 群体兜底」混合策略，冷启动也可正常使用

## 项目结构

```
.
├── main.py          # FastAPI 入口，路由与请求/响应模型
├── battery.py       # 电量计算核心逻辑
├── baseline.py      # 混合基线模型（个人 + 群体）
├── normalizer.py    # 指标归一化
├── optimizer.py     # 参数校准工具
├── params.py        # 可调参数定义与默认值
├── mock_data.py     # 模拟用户数据（演示/测试用）
└── requirements.txt
```

## 快速开始

**安装依赖：**

```bash
pip install -r requirements.txt
```

**启动服务：**

```bash
uvicorn main:app --reload --port 8001
```

启动后访问 http://localhost:8001/docs 查看交互式 API 文档。

## API 接口

### `POST /calculate/battery` — 计算机体电量

```json
{
  "user_id": "user_001",
  "hours_since_last_sleep": 6.5,
  "metrics": {
    "resting_hr": 58.0,
    "hrv_rmssd": 42.0,
    "spo2": 97.5,
    "deep_sleep_ratio": 0.22,
    "active_minutes": 35.0
  }
}
```

响应包含 `battery`（衰减后电量）、`raw_battery`（衰减前）、`confidence`（置信度 0~1）、各组分得分等明细。

### `POST /baseline/update` — 写入历史数据更新基线

```json
{
  "user_id": "user_001",
  "records": [
    { "resting_hr": 60, "hrv_rmssd": 40, "spo2": 97, "deep_sleep_ratio": 0.2, "active_minutes": 30 }
  ]
}
```

### `GET /baseline/{user_id}` — 查询当前基线

### `POST /params/update` — 运行时调整权重与衰减参数

```json
{
  "weights": { "sleep": { "value": 0.45 } },
  "decay_rate": 0.025
}
```

权重自动归一化，无需重启服务生效。

### `GET /params` — 查询当前参数与合法区间

## 可调参数

| 参数 | 默认值 | 合法区间 |
|------|--------|----------|
| `weights.sleep` | 0.40 | [0.25, 0.55] |
| `weights.hrv` | 0.30 | [0.15, 0.45] |
| `weights.spo2` | 0.15 | [0.05, 0.25] |
| `weights.activity` | 0.15 | [0.05, 0.25] |
| `decay_rate` | 0.02 | [0.01, 0.04] |
| `baseline_window_days` | 7 | [3, 14] |
