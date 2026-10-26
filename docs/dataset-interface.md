# 可替换数据集接口

标准Schema由 `/ui/dataset-schema` 返回。导入接口转发到指定端，训练数据存放在该端。在线遥测只来自独立采集器，导入或生成样本不会覆盖实时监控。

## JSON结构

顶层：`dataset_id`（字母、数字、短横线、下划线，最多64字符）、`source`（内部溯源字段）、`description`（可选）、`records`（最多1000事件）。数据集ID不可覆盖，变更请使用新ID。`source`由准备器填写；外部文件使用`external`。界面的数据集列表不展示来源列。

事件：`event_id`、`label`、`split`（train/validation/test）、`series`。同一事件只能出现一次，防止跨分区泄漏。所有数值必须有限；未定义字段会拒绝。测试集不会参与梯度训练或验证F1。

每个时间点的12个字段：

| 字段 | 单位/范围 |
|---|---|
| availability | 业务健康比例0～1 |
| error_rate | 请求错误比例0～1 |
| latency_ms | 请求时延ms |
| pool_usage | 连接池占用0～1 |
| worker_usage | 工作线程占用0～1 |
| worker_wait_ms | 线程等待ms |
| db_wait_ms | 数据库连接等待ms |
| dependency_ms | 下游依赖耗时ms |
| dependency_error_rate | 下游错误比例0～1 |
| config_error_rate | 配置校验操作失败比例0～1 |
| cpu_usage | 业务进程CPU比例0～1 |
| rss_mb | 业务进程常驻内存MB |

可选`timestamp`是Unix时间，不进入模型特征。每事件最多20个时点；不足20点使用掩码，而不是伪造有效采样。

## CSV映射

每行一个时点，包含event_id、label、split和12个指标。相同事件连续或不连续均可，转换器按文件顺序分组；请事先按事件和采样时间排序。大于20点需在上游切成有明确标签的窗口，转换器不会静默丢弃数据。

映射文件示例：

```json
{"columns":{"latency_ms":"latency_seconds","error_rate":"error_pct"},"labels":{"db_pool_full":"pool_exhausted"},"scales":{"latency_ms":1000,"error_rate":0.01}}
```

未映射字段使用标准列名。命令：

```
.venv\Scripts\python.exe -m scripts.import_dataset input.csv --mapping mapping.json --dataset-id external-v1 --output converted.json
```

加`--upload a --url http://127.0.0.1:15000`导入到A端。可先只转换，通过校验后在网页选择JSON文件导入。

## 训练与推理隔离

导入记录的label只由离线训练/评估使用。在线`/run`不接受label或fault字段；编码函数仅读取12项指标白名单。日志文字、注入开关、恢复动作、数据集ID均不进入特征。API负向测试验证了更换日志关键词和添加额外指标不会改变神经模型输出。

后续更换数据集主要修改字段、单位和标签映射。若需要增加论文其余故障类别，应扩展分类头、标签字典、联邦直方图维度和处置动作；不能仅改中文名称。


## 样本配置与独立评估（2026-09-10）

生成请求增加 `profile`：`balanced`（类别均衡）、`non_iid`（节点分布差异，默认）、`transition`（故障过渡窗口），`per_class` 范围3–30。生成事件含不同故障起点、相关波动，较大样本集分别保留约20%验证和20%测试。

`POST /ui/datasets/{node}/evaluate` 使用所选数据集的测试分区评估当前模型，返回 `model_version`、`model_sha256`、`test_count`、`accuracy`、`macro_f1`、`confusion_matrix`、`events` 与 `stored_at`。混淆矩阵行为真实标签、列为分类头预测；评估不写模型、不将测试成绩上报为联邦训练质量。完整评估保存到端侧 `evaluations/*.json`，操作日志也可查输入输出。
