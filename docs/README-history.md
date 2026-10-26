> 百炼模型、私有密钥文件、自部署接口和真机显示：[模型API与密钥说明](docs/模型API与密钥说明.md)。

> **新版 16 节点入口：双击 `start-cluster.cmd`；停止使用 `stop-cluster.cmd`。完整教程见 [本地部署教程.md](本地部署教程.md)。下面保留旧版说明，勿与新版同时启动。**

# FedHELM 可运行框架原型

**完整启动、停止、故障验证、模型更新与存储说明：[启动说明.md](启动说明.md)。**

## 当前论文流程版（2026-09-10）

关键模块、公式对应、已实现流程与仿真差异见 [论文模块与算法对应](docs/论文模块与算法对应.md)。新增三类样本配置和独立测试集评估，可直接在数据集管理页面操作。

双击 `start-paper.cmd`，打开 http://127.0.0.1:15000。三端已准备时序数据并完成 Transformer 训练、Top50% INT8 上传、贡献度聚合与同步；新增数据集管理、实时指标和算法运行页面。SLM/LLM 保留可替换的仿真接口。本机运行方式为隔离业务进程，Kubernetes 尚未完成部署验证。

## 自动监控与独立故障注入页

现在首页是系统总览，`/inject`是独立故障注入页，原工作台移到`/lab`。启动后后台自动巡检，注入后自动选择模型、修复、验证并记录时间线；支持暂停，默认不自动训练。操作和边界见[自动监控说明](docs/automatic-monitor.md)。

## 历史阶段：Kubernetes与真实轻量模型训练

**本机当前：真实训练及真实业务故障闭环已通过，Kubernetes部署仍受Docker启动/镜像网络问题阻塞。** 双击`start-training.cmd`可体验已验证的本地真实训练版（当前入口已升级为15000端口，旧配置仅作历史记录）。

Kubernetes部署入口是`start-k8s.cmd`，仅在部署成功后使用`open-k8s.cmd`打开 http://127.0.0.1:13000/ 。完整说明见[docs/kubernetes.md](docs/kubernetes.md)，实际测试状态见[docs/validation.md](docs/validation.md)。

- 大小语言模型继续保留替身，等待后续接入API。
- 轻量模型支持PyTorch实际训练、验证及参数增量聚合。
- Kubernetes模式使用专用kind集群，边缘服务与A/B/C工作节点通过标签调度。
- 故障注入实际影响测试Deployment、业务配置和连接池，具体范围见部署文档。
- 使用UI的“全端同步 → 采集训练数据 → 全端训练 → 聚合更新 → 全端同步”操作。

下面保留的纯模拟和本地进程模式用于兼容调试，不能代表Kubernetes模式的训练状态。代码会通过`training_backend`和`workload_backend`明确区分。

## 新增：实际业务测试床

双击 `start-testbed.cmd`，启动独立HTTP业务进程版本并自动打开控制台。会选择空闲端口组，已有旧版平台不会被关闭。保留原 `start-platform.cmd` 的纯模拟模式用于接口调试。

在实际业务模式下：

- 服务停止：真正关闭该节点自己的业务子进程；重启创建新PID。
- 配置错误：修改该测试业务的config.json，实际订单HTTP接口返回503；恢复配置后恢复查询。
- 连接池耗尽：占住4个SQLite连接，订单请求等待后返回503；释放连接后恢复。
- 每次观测实际发起3次HTTP请求；`response_codes`、`latency_ms`和`business_pid`来自实测。响应码0代表未收到HTTP响应。
- 业务控制器始终独立运行，业务故障不会阻止执行修复。父控制器退出时，业务子进程通过管道关闭信号退出。

完整验证命令：

```powershell
.\.venv\Scripts\python.exe -m scripts.local --demo --workload-backend process --base-port 11000 --data-dir runtime/process-check
```

容器部署配置（配置已校验，尚未验证Docker实际运行）：

```powershell
docker compose -f compose.yaml -f compose.process.yaml up --build --wait
```

这仍是受控测试床，不是论文12服务平台。**模型仍为替身、训练仍为测试增量、资源数据仍为模拟值。** `simulated=true`继续标记整体实验性质；`workload_backend=process`明确区分实际业务观测与合成观测。成功标签来源为`testbed_injector`。反馈仍是短窗口演示，未实现论文5分钟SLO。

以下原框架说明中的“模拟工作负载”指默认`synthetic`模式；使用`process`模式时以上说明优先。

这份实现先确定边缘、端侧、测试服务的输入输出，并通过 HTTP 跑通闭环。**尚未部署真实模型，尚未进行神经网络训练，也没有复现论文实验效果。** 所有核心数据结构包含 `schema_version: "1.0"` 和 `simulated: true`。

## 已实现

- 边缘应用：诊断转发、SQLite 成功案例库、相似检索、案例下发、资源上报。
- 联邦协调服务：接收带版本的模拟参数增量，完成贡献度加权聚合，持久化并提供新模型。
- A/B/C 端侧：采集测试观测、轻量替身诊断、路由、调用语言模型替身、执行、连续观测验证、同步模型和案例。
- 大小语言模型 HTTP 替身：统一输入输出，可在后续替换真实推理后端。
- 三个独立测试服务：用状态模拟服务停止、配置错误、连接池耗尽；不会操作真实业务。
- 端到端演示与异常接口测试。

## 本地启动（不需要 Docker / GPU）

当前工作区已经配置好环境：Windows可直接双击 `run-demo.cmd` 跑完整演示，或双击 `start-platform.cmd` 持续启动平台。无需重新创建虚拟环境或安装依赖。演示结束后窗口保留结果，按任意键关闭。

### 中文可视化控制台

双击 `start-platform.cmd` 后会自动打开控制台。默认 http://127.0.0.1:8000/ ；启动器会优先复用8000/9000/10000上已运行且全部服务在线的新版控制台。如果旧版占用端口，会选择空闲端口组，具体地址显示在窗口中。不会关闭已有进程。启动失败时窗口保留错误，不再闪退。

新启动平台时请保留窗口，Ctrl+C停止服务；复用现有平台时，该次窗口按任意键关闭不影响原平台。

控制台显示边缘模块、A/B/C管理进程与业务状态、模拟网络、模型版本、共享案例和操作记录。无需手写JSON：

1. 点击“全端同步”初始化模型与案例。
2. 在任意端节点选择故障，点击“注入所选故障”。
3. 选择诊断方式，点击“执行诊断 → 处置 → 验证”。
4. 查看恢复结果，点击“提交成功案例”。控制台核对本次注入真值后提交。
5. 点击“全端模拟训练 → 聚合更新 → 全端同步”，观察模型版本变化。

还可设置正常网络、高延迟、边缘不可达条件。失败提示会保留，完整JSON可展开。案例只接受本次控制台注入、诊断后的候选；不要同时用外部脚本修改同一节点的测试故障。页面记录为会话级，重启边缘应用会清空待提交候选及控制台真值，SQLite案例仍保留。

所有模块的 `/docs` 功能标题和说明已改成中文；编程字段名保留英文，便于稳定调用。离线契约同步导出到 `docs/openapi/`。

仅在新机器首次安装时创建环境。需要 Python 3.12，以下命令在仓库根目录执行，CMD和PowerShell均可；只复制代码框里的命令，不复制三个反引号和语言标记。Windows已安装Python启动器时：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m scripts.local --demo
```

`--demo` 会启动10个独立进程，执行三条诊断路径、案例收录与复用、一次聚合与同步，再自动停止自己启动的进程。结果在 `runtime/demo-report.json`，服务日志在 `runtime/local/`。可重复执行，模型版本继续递增。

持续运行供手动查看：

```powershell
.\.venv\Scripts\python.exe -m scripts.local
```

在另一个终端演示：

```powershell
.\.venv\Scripts\python.exe -m scripts.demo
```

Linux 将上述 Python 路径替换为 `.venv/bin/python`。按 Ctrl+C 停止启动器及其子进程。端口占用时使用 `--base-port 9000`；启动器演示会自动使用新端口，单独演示需设置 `BASE_PORT=9000`。

### Windows：Python版本或SSL错误

本机默认 `python` 指向 `D:\soft\anaconda\python.exe`（3.8.5），不适用于本项目。不要用它再次运行 `python -m venv .venv`，否则会覆盖项目解释器，出现SSL模块无法加载及依赖版本不兼容。

本机恢复环境的CMD命令（其他机器需使用其自己的Python 3.12路径）：

```bat
"C:\Users\28120\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m venv .venv
.venv\Scripts\python.exe -m pip check
run-demo.cmd
```

PowerShell运行上面第一行时，需要在引号路径前加 `&`。若依赖缺失，再用项目解释器安装 `requirements.lock.txt`。不需要关闭SSL校验。

| 服务 | 默认地址 |
|---|---|
| 边缘应用 / API文档 | http://127.0.0.1:8000/docs |
| 联邦服务 / API文档 | http://127.0.0.1:8001/docs |
| 边缘语言模型替身 | http://127.0.0.1:8002/docs |
| A端语言模型替身 | http://127.0.0.1:8003/docs |
| A/B/C端 | http://127.0.0.1:8101/docs、8102/docs、8103/docs |
| A/B/C测试服务 | http://127.0.0.1:8201/docs、8202/docs、8203/docs |

每个服务还提供 `/openapi.json`，JSON字段以 `fedhelm/contracts.py` 和OpenAPI为准。

## Docker Compose

先停止占用同一端口的本地启动器，确保 Docker 引擎已启动：

```powershell
docker compose up --build --wait
.\.venv\Scripts\python.exe -m scripts.demo
docker compose down
```

端侧、边缘数据库和模型使用独立命名卷。`down`保留卷。测试服务故障状态在进程内，重启后恢复正常。Compose配置包含不同端侧CPU/内存限额，仅供框架调试，不声称等价于论文硬件；模拟资源状态仍通过接口注入，没有自动读取这些限额。

## 手动运行一次

1. 在A端 `/sync` 拉取初始模型和案例。
2. 在对应测试服务 `/inject` 提交 `{"fault":"service_down"}`。
3. 在A端 `/run` 提交 `{}`，或 `{"force_mode":"local"}`。
4. 查看输出中的 `plan`、`execution`、`feedback` 和 `case_candidate`。
5. 成功案例仍需确认根因才可提交边缘 `/memory/cases`。演示脚本持有注入真值，负责核对标签并提交；端侧诊断不读取注入真值。

`force_mode`仅用于逐条验证模型接口。默认路由为简化规则：低置信度升级边缘；A级内存允许且RTT高时走本地；其他情况走轻量路径。没有实现论文完整EWMA代价优化。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scripts.local --demo --base-port 9000 --data-dir runtime/check
docker compose config --quiet
```

负向测试覆盖不允许的动作、错误目标、错误动作不恢复、虚假成功反馈、未确认标签、重复案例、错误事件关联、聚合缺节点、过期及冲突增量。

## 模拟与真实的边界

| 项目 | 当前实现 | 后续替换 |
|---|---|---|
| 进程间通信、类型校验 | 真实 HTTP / Pydantic | 保留 |
| 案例存储、检索 | 真实 SQLite / 余弦检索 | 可换 FAISS |
| 观测、故障、修复 | 合成指标及状态切换 | 实际服务采集和执行接口 |
| 轻量模型 | 规则识别＋4维固定特征＋模拟置信度参数 | PyTorch 编码器和分类头 |
| 大小语言模型 | 固定动作映射 | vLLM / llama.cpp |
| 本地训练 | 生成4维测试增量和测试质量值 | 真实梯度训练与验证 |
| 聚合 | 对测试增量做真实加权计算 | Flower、自定义论文策略、EWMA、探针 |
| 反馈 | 3次间隔50ms观测 | 配置正式SLO窗口，论文为5分钟 |
| 资源与路由 | 注入资源、简化规则 | 实测资源及论文代价模型 |

本原型使用固定特征版本 `mock-features-v1`，模拟参数更新仅改变置信度，不改变特征空间。真实编码器接入后，必须扩展特征维度契约、按模型版本重新编码案例，不能混用不同版本向量。

## 后续 Kubernetes

目前无需 Kubernetes 即可验证模块边界。若下一步需要模拟多台机器，可使用 kind 创建一个控制平面和多个worker，为worker标注 `role=edge` / `role=end`、`tier=A/B/C`，再用调度约束把相关服务放到指定worker；边缘、端侧和工作负载仍使用这些相同接口。

单机 Kubernetes 中的worker仍共享宿主机硬件，不等于真实独立设备；网络延迟、丢包也需要另外配置。本次没有创建Kubernetes集群或声称验证其部署。

详细模块边界见 `docs/interfaces.md`，后续接入计划见 `docs/architecture.md`。
