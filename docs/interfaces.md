# 模块输入输出契约 v1.0

## 实际测试业务模式补充

启动器增加`--workload-backend process`；业务控制器的路径和请求结构不变。Observation新增可选字段：`workload_backend`（synthetic/process，默认synthetic）、`response_codes`（本次3个实际HTTP状态码，无响应为0）、`business_pid`（进程ID或null）。旧模拟数据仍可解析。

Case的`label_source`新增`testbed_injector`，表示来自实际测试床的受控注入真值。控制台和演示器按观测后端自动选择来源。`simulated=true`表示整体仍是实验原型，不代表process模式中的时延是伪造值。

process模式中`applied=true`只表示动作函数执行完成，不能据此判定恢复；端侧必须继续检查实际观测。例如错误配置时执行连接池重置仍会返回503并验证失败。

所有POST/PUT主体均为JSON；拒绝未知字段。`schema_version`默认`1.0`，`simulated`只能为`true`。现阶段没有真实模式开关，避免误把替身当真实实验。FastAPI自动提供 `/docs` 与 `/openapi.json`。

## 边缘应用

浏览器打开边缘根路径 `/` 为中文交互界面。`GET /ui/status`读取全部固定节点状态，`POST /ui/command`执行按钮操作；不接受自定义目标URL。控制台为单操作者原型，操作串行，支持离线和部分失败反馈。模型与观测仍全部为模拟数据。

| 方法与路径 | 输入 | 输出 / 行为 |
|---|---|---|
| POST /diagnose | InferenceRequest：观测、初诊、可选案例 | 从边缘案例库检索，调用模型适配器，返回Plan |
| POST /resources | Resources：节点、档次、CPU、可用内存、带宽、RTT、边缘可达性 | accepted；覆盖该节点最新状态 |
| GET /resources | 无 | nodes资源快照 |
| POST /memory/cases | Case | 验证后收录；同ID同内容幂等，不同内容409 |
| POST /memory/search | Search：4维embedding、版本、top_k | hits：相似度及完整案例，阈值0.82 |
| GET /memory/snapshot | 无 | 最多100条案例；端侧手动sync拉取 |

收录条件：根因已确认、反馈成功、3个观测均属于同事件/节点/服务且健康、错误率≤0.05、时延≤500ms、方案置信度≥0.6、动作非none。边缘只能检查提交证据的一致性，当前无身份认证和可信遥测校验，不能防止恶意伪造反馈。

## 模型适配器

`POST /infer` 输入 `InferenceRequest`，输出 `Plan`。大小模型共用契约，通过 `MODEL_MODE`区分。当前实现不生成提示词、不加载权重，使用候选根因和匹配案例选择固定动作。

```json
{
  "observation": {
    "event_id":"e1", "node_id":"a", "service_id":"service-a",
    "healthy":false, "error_rate":1, "latency_ms":1500,
    "pool_usage":0.2, "logs":["process unavailable"]
  },
  "diagnosis": {
    "event_id":"e1", "root_cause":"service_down", "confidence":0.7,
    "embedding":[0,1,0,0], "model_version":0,
    "evidence":["process unavailable"]
  },
  "retrieved_cases":[]
}
```

输出示意（省略默认版本标记）：

```json
{
  "event_id":"e1", "node_id":"a", "service_id":"service-a",
  "mode":"edge", "root_cause":"service_down", "confidence":0.7,
  "action":"restart_service", "parameters":{}, "reason":"MOCK adapter"
}
```

## 端侧代理

| 方法与路径 | 输入 | 输出 / 行为 |
|---|---|---|
| POST /sync | 无 | 拉取全局模型、案例，上传资源；返回model和cached_cases |
| PUT /resources | Resources | 更新模拟资源并上报；不允许改节点ID和档次 |
| POST /run | RunRequest：可选force_mode | observation、diagnosis、plan、execution、feedback、case_candidate、used_case |
| POST /train | 无 | 用已加载版本构造模拟Update并上传；返回update和ack |
| GET /health | 无 | node_id、tier、model_version、status |

`/run`由外部触发一次采集，不是持续后台监测。低置信度且边缘不可达时返回503，不执行动作。B/C请求local返回409。实际模型服务故障返回503。端侧运行和同步串行化，避免同节点执行过程中模型变化。

`case_candidate`默认未确认根因，不能直接入库。演示器核对注入真值后，设置`root_cause_confirmed=true`、`label_source=synthetic_injector`再提交。该标签不反馈给诊断接口。

## 测试工作负载

| 方法与路径 | 输入 | 输出 / 行为 |
|---|---|---|
| POST /inject | Injection：fault | 切换模拟故障状态；仅外部演示器调用 |
| GET /observe?event_id=... | 事件ID | Observation，不提供故障真值标签 |
| POST /execute | Plan | applied、event_id；正确动作恢复状态，错误动作不恢复 |

故障枚举：healthy、service_down、config_error、pool_exhausted。
动作枚举：none、restart_service、restore_config、reset_pool。
只允许本服务本节点目标，参数当前必须为空；不执行shell命令。

服务控制平面 `/health`始终说明进程是否存活，业务健康看`/observe`，避免模拟业务故障导致控制程序不可调用。

## 联邦协调服务

| 方法与路径 | 输入 | 输出 / 行为 |
|---|---|---|
| GET /model | 无 | Model：version、4维parameters、adapter |
| POST /updates | Update | accepted、pending_nodes |
| POST /aggregate | 无 | model、weights、模拟说明；要求a/b/c都已提交 |

Update字段：node_id、base_version、sample_count、4维delta、4维label_histogram、quality。直方图非负且总和等于sample_count，浮点数不能为NaN/Infinity。

错误版本、同节点同轮冲突更新返回409；相同更新重试幂等；聚合后清空待处理更新。全局模型原子写文件，重启保留；未完成轮次仅在内存中，重启后需各端重新提交。下发采用端侧`/sync`主动拉取。

聚合计算：归一化标签熵D，输入的模拟质量Q，当前各增量平均方向与本地增量的余弦映射到[0,1]得到S；q=0.4D+0.35Q+0.25S，权重归一化n*q，全为零时均匀分配。新参数=旧参数+加权增量。

这是接口演示算法，尚未实现论文EWMA、探针质量、冷启动和压缩，也没有部署Flower。后续Flower适配层负责传输/轮次，替换此协调服务内部实现。

## 持久化和关联

- 案例：edge独立SQLite文件；模型：federation独立JSON文件。
- 端侧：独立事件日志；模型和案例缓存在内存，重启先sync。
- `event_id`串联观测、诊断、方案和反馈；`case_id`用于案例幂等。
- `model_version`控制训练轮次；`embedding_version`控制向量兼容性。
- 单worker运行；本阶段不要启动多个uvicorn worker，因为资源表及待聚合更新保存在进程内。
