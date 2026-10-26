# Windows 本地 Kubernetes 部署教程（16 个逻辑端节点）

> **历史部署记录，当前操作请优先使用 [docs/运行与复现.md](docs/运行与复现.md)。** 本文件保留了首次部署细节，但其开头的 Docker 故障状态和验证时间是历史快照，不能代表现在的集群状态。

更新：2026-09-10。本文对应当前项目，所有命令在 **Windows PowerShell** 执行。

**目前的真实状态：Docker Linux Engine 连接失败，Kubernetes 镜像构建和集群启动尚未实机验证。原来 15000 端口上的 Windows 进程版不是 Kubernetes。本文附带实际部署脚本，必须完成下面的 Pod、存储和业务验收，才能算部署成功。**

## 1. 这次到底部署什么

使用 Docker Desktop 的 Linux 容器引擎，通过 kind 创建真正的 Kubernetes 集群。kind 的 Kubernetes 节点本身是 Docker 容器，内部运行 Kubernetes 控制面、kubelet 和容器运行时。参见 [kind 官方说明](https://kind.sigs.k8s.io/docs/user/quick-start/)。

```text
Windows → Docker Desktop / WSL2
  └─ kind 集群 fedhelm16
      ├─ 1 个 Kubernetes control-plane
      └─ 1 个 Kubernetes worker，承载：
          ├─ edge Pod：管理平台、联邦服务、两个模型 API 网关
          ├─ injector Pod：独立故障实验站
          ├─ agent-a01 ～ agent-a05：5 个 A 类逻辑端
          ├─ agent-b01 ～ agent-b06：6 个 B 类逻辑端
          └─ agent-c01 ～ agent-c05：5 个 C 类逻辑端
              每端 Pod = Agent 容器 + 测试业务容器
```

**16 个端是 16 个独立 Pod，不是 16 个 Kubernetes Worker，也不是 16 台物理机。** 每端独立采集、诊断、训练、存储和业务进程，K8s 负责运行这些容器。以后要一端一台物理机，需要增加物理 Worker，并配置节点亲和性；当前清单没有强制一端一机。

应用预期规模：18 个 Deployment、18 个 Pod、37 个应用容器、18 个 PVC。Kubernetes 自己的系统 Pod 不在这些数字中。轻量模型在各端 Agent 中运行；两个语言模型先通过边侧 API 网关调用远程或自部署接口，当前没有在每个 A 端运行 1.5B 权重。这些是部署取舍，不等同论文硬件配置的完整复现。

## 2. 准备环境

本机已找到 `tools\kind.exe`（v0.33.0）和 Docker 自带的 kubectl。先打开 Docker Desktop，启用 WSL2 后端、使用 Linux containers，等待引擎启动完成。**不需要启用 Docker Desktop 自带的 Kubernetes**，本文用 kind 单独创建集群。未安装 Docker 时按 [Docker Windows 安装说明](https://docs.docker.com/desktop/setup/install/windows-install/) 操作；安装或启用 WSL 可能要求重启 Windows。

本机内存约 16 GB，先关闭本项目进程版及不用的软件。建议给 Docker/WSL 留约 8 GB 内存、4 个 CPU 的起步预算，实际是否足够以运行和训练时的内存为准；不要同时运行两套 16 端平台。WSL2 的资源限制应按你的现有 WSL 配置调整，不要直接覆盖已有 `.wslconfig`。镜像首次构建会下载 Python、PyTorch 和 Kubernetes 镜像，需要网络和数 GB 磁盘空间。

打开 PowerShell，逐条执行：

```powershell
Set-Location 'C:\Users\28120\Desktop\631wujiao'
wsl --status
docker info
docker info --format '{{.OSType}}'
.\tools\kind.exe version
kubectl version --client
```

验收：`docker info` 必须能显示 Server 信息，OSType 必须输出 `linux`。如果仍是 `dockerDesktopLinuxEngine ... The system cannot find the file specified`，**到这里停止，先处理 Docker 启动问题**。有 docker.exe 并不代表 Docker 引擎在运行。

如果项目复制到了别的电脑，修改上面的路径；没有 kind 时可执行 `winget install Kubernetes.kind`，重新打开终端后使用 `kind version`。部署脚本优先使用项目自带 kind，其次查找 PATH。当前提供的清单已生成，正常部署不需要在 Windows 额外安装 Python 或 PyTorch，依赖安装在镜像中完成。

## 3. 部署：使用新的入口

若原来的进程版仍在运行，先在其启动窗口按 Ctrl+C，或执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\stop-cluster.ps1
```

若提示找不到启动记录，不要随意结束其他 Python 进程，使用原启动窗口停止即可。

运行新脚本：

```powershell
.\start-k8s16.cmd
```

**使用 `start-k8s16.cmd`，不要用旧的 `start-k8s.cmd` 或 `start-cluster.cmd`。** 脚本会：

1. 检查 Docker Linux Engine；失败立即停止。
2. 创建名为 `fedhelm16` 的 kind 集群；同名集群已存在则复用，不删除。
3. 用 `Dockerfile.training` 构建 `fedhelm-cluster:k8s16`，加载到 kind。
4. 创建 `fedhelm-cluster` 命名空间和内部鉴权 Secret。新令牌保存在 `secrets/k8s-internal.token`，不会打印值，也不依赖进程版先启动。
5. 应用 `k8s/cluster16-local.json`，刷新应用 Pod，最多等待 600 秒就绪。

首次构建耗时取决于下载速度。任何一步出现 `STOPPED` 或非零退出码，都表示尚未完成；保留报错定位。脚本不会重置 Docker、删除已有集群或启动 Windows 进程版来替代 Kubernetes。重复运行会重建镜像并重启本项目应用，已有 PVC 保留。已有同名集群会保持原来的 Worker 数量，可用下一节命令确认。

## 4. 验收真正的 Kubernetes

执行：

```powershell
kubectl --context kind-fedhelm16 get nodes -o wide
kubectl --context kind-fedhelm16 -n fedhelm-cluster get deployments
kubectl --context kind-fedhelm16 -n fedhelm-cluster get pods -o wide
kubectl --context kind-fedhelm16 -n fedhelm-cluster get pvc
```

新建集群预期：

| 检查项 | 应看到什么 |
|---|---|
| Kubernetes 节点 | `fedhelm16-control-plane`、`fedhelm16-worker` 均为 Ready |
| Deployment | 共 18 个，每个 READY 为 1/1 |
| edge Pod | READY 为 4/4，STATUS 为 Running |
| injector Pod | READY 为 1/1，STATUS 为 Running |
| 16 个 agent Pod | 每个 READY 为 2/2，STATUS 为 Running |
| PVC | 共 18 个，全部 Bound |

启动/滚动重启期间数量可能短暂变化，等稳定后再核对。仅有 Running 而 READY 不全也不算成功。

进一步证明端程序确实在 Pod 内：

```powershell
kubectl --context kind-fedhelm16 -n fedhelm-cluster exec deployment/agent-a01 -c agent8000 -- printenv NODE_ID POD_NAME K8S_NODE_NAME
kubectl --context kind-fedhelm16 -n fedhelm-cluster logs deployment/agent-a01 -c agent8000 --tail=50
```

第一条应输出 `a01`、实际 Pod 名、实际承载 Kubernetes 节点名，而不是仅靠界面写了一个节点名称。

## 5. 打开两个网页

另开两个 PowerShell 窗口，每个执行一条并保持运行：

窗口一，系统平台：

```powershell
kubectl --context kind-fedhelm16 -n fedhelm-cluster port-forward svc/edge 16000:8000
```

窗口二，故障实验站：

```powershell
kubectl --context kind-fedhelm16 -n fedhelm-cluster port-forward svc/injector 16090:8000
```

- 系统平台：<http://127.0.0.1:16000/>
- 集群大屏：<http://127.0.0.1:16000/topology>
- 独立故障实验站：<http://127.0.0.1:16090/>

K8s 版专门使用 16000/16090，旧的 15000 页面不能用于验收本次部署。关闭转发窗口或对应 Pod 重启后，必要时重新执行转发。无需将 16 个 Agent 的端口全部暴露到 Windows。

## 6. 模型 API：可选，先不配置也能检查集群

新 PVC 不会自动读取 Windows 的 API 配置和历史模型。两个网关没有可用 API 时，不应期待依赖语言模型的处置成功，任务应保留未配置或调用失败信息。

要使用已经保存的百炼密钥，确认本地 `secrets\bailian-api.key` 存在，然后执行一次：

```powershell
kubectl --context kind-fedhelm16 -n fedhelm-cluster create secret generic provider-key --from-file=bailian-api.key=secrets/bailian-api.key
kubectl --context kind-fedhelm16 -n fedhelm-cluster rollout restart deployment/edge
kubectl --context kind-fedhelm16 -n fedhelm-cluster rollout status deployment/edge --timeout=180s
```

Secret 已存在时不要重复创建；上面创建命令报 AlreadyExists 不是密钥更新成功。需要换密钥时另行更新 Secret。完成后重新运行边侧端口转发。

在系统“API 配置”页面分别配置边侧和小模型角色：使用百炼对应地域的兼容接口地址；模型可沿用此前配置的 `qwen-plus`、`qwen-turbo`；**容器内密钥文件路径填写 `/secrets/bailian-api.key`，不能填 Windows 路径**。保持低调用预算和短输出限制，保存后只做少量连通性测试。具体角色提示词、限制和自部署接口见 [模型 API 说明](docs/模型API与密钥说明.md)。可用额度及实际费用以你的百炼账户为准。

密钥只挂载到边侧有关容器。注意：删除 Windows 的 key 文件，不会撤销已复制到 Kubernetes Secret 中的密钥。要停止集群使用它，先在页面禁用 API，再执行 `kubectl --context kind-fedhelm16 -n fedhelm-cluster delete secret provider-key` 并重启 edge；若要彻底使密钥失效，在百炼控制台撤销。

## 7. 实测一次完整流程

按顺序操作，先只测试一个端，避免训练和故障同时压满电脑：

1. 系统大屏确认 A×5、B×6、C×5 在线。进入 a01 查看服务、观测指标、Pod/主机信息。
2. 模型页面先同步全局模型到各端。新存储中的初始模型不等于原进程版已训练的 v6。
3. 数据集页面为各端生成并激活时序训练集。训练按端顺序进行，查看训练记录、上传记录，完成后聚合、下发，核对端侧版本。数据保存在各端 PVC；这里用于仿真流程验证，不据此宣称论文实验效果。
4. 保持 a01 正常采集，去 16090 实验站选择 a01，执行“停止业务”一类故障。观察业务健康探测、进程状态和采集指标变化。
5. 回到系统的节点详情与任务链，查看检测、轻量模型诊断、调度、模型调用、执行、验证和案例记录的时间线。API 未配置时，相关步骤可能失败，不能把这个算自动修复成功；可在实验站恢复业务。
6. 对照操作日志、模型上传下发记录、故障前后指标。自动修复成功要有恢复后的实际采样/探测证据，而不只是任务显示“成功”。

**当前真实故障作用于容器里的测试业务进程或业务配置。** 例如终止业务子进程、改变响应行为；Agent 和业务控制器仍可存活，因此 Pod 仍显示 Running 是合理的。当前不是关闭物理机或杀死整个 Kubernetes Worker，不能将这类测试写成物理节点宕机实验。

## 8. 数据存在哪里，如何停止和恢复

每个逻辑端一个 PVC，边侧和实验站各一个，共 18 个，各申请 1 GiB。实际数据包括 SQLite 数据库、时序样本、模型和任务记录。它们位于 kind 内的存储卷，**不是 Windows 的 `runtime/cluster`**。界面“数据存储”“模型”“日志”展示应用记录；容器标准输出另用 `kubectl logs` 查看。

停止应用并保留数据：

```powershell
kubectl --context kind-fedhelm16 -n fedhelm-cluster scale deployment --all --replicas=0
```

同时在两个转发窗口按 Ctrl+C。kind 控制面和 Worker 仍在运行、仍占少量资源。下次恢复无需重建镜像：

```powershell
kubectl --context kind-fedhelm16 -n fedhelm-cluster scale deployment --all --replicas=1
kubectl --context kind-fedhelm16 -n fedhelm-cluster wait --for=condition=Available deployment --all --timeout=600s
```

然后重新开两条端口转发。**删除 kind 集群、删除 PVC 或恢复 Docker 出厂设置会造成存储丢失；不要把这些当停止按钮。** 迁移到物理集群时也需要单独迁移数据和配置，不能只复制 Windows 的项目目录。

## 9. 出错时查哪里

```powershell
kubectl --context kind-fedhelm16 -n fedhelm-cluster get events --sort-by=.metadata.creationTimestamp
kubectl --context kind-fedhelm16 -n fedhelm-cluster describe pods
kubectl --context kind-fedhelm16 -n fedhelm-cluster logs deployment/edge -c edge8000 --tail=100
kubectl --context kind-fedhelm16 -n fedhelm-cluster logs deployment/agent-a01 -c agent8000 --tail=100
kubectl --context kind-fedhelm16 -n fedhelm-cluster logs deployment/agent-a01 -c real-workload8001 --tail=100
kubectl --context kind-fedhelm16 get storageclass
```

| 现象 | 处理方向 |
|---|---|
| Docker named pipe 找不到 | Docker Linux Engine 没启动好，先修复环境，不继续部署 |
| 镜像构建下载失败 | 按具体 pip/镜像错误检查网络、代理和版本；构建没完成就不算已部署 |
| ImagePullBackOff | 检查镜像是否成功构建并加载到 `fedhelm16`，标签必须匹配 `fedhelm-cluster:k8s16` |
| PVC Pending | 查看默认 StorageClass 和存储 provisioner 是否正常 |
| CreateContainerConfigError | 查看 describe 中是否缺 `internal-auth` Secret |
| OOMKilled / Evicted | 内存不足；先停止训练、关闭进程版，再检查 Docker 内存和容器限制 |
| 端口已占用 | 检查是否已有同一条转发；不要结束不认识的进程 |
| 16000 打不开 | 转发窗口是否还运行、edge Pod 是否 Ready |
| 模型调用失败 | 检查 API 启用状态、容器内 key 文件路径、服务商地址和额度 |

## 10. 交付文件和验证边界

- `start-k8s16.cmd`：双击入口，出错保留窗口。
- `scripts/deploy-k8s16.ps1`：构建、创建、加载、部署、等待；显式指定本项目 context。
- `k8s/kind16.yaml`：1 控制面 + 1 Worker。
- `k8s/cluster16-local.json`：完整 16 端应用清单，网页地址为 16000/16090。
- `scripts/cluster_manifest.py`：后续改配置时重新生成清单；普通启动不用运行。

重新生成清单的命令（修改节点配置后才需要；需要项目 Python 环境）：

```powershell
.\.venv\Scripts\python.exe -m scripts.cluster_manifest --image fedhelm-cluster:k8s16 --console-url http://127.0.0.1:16000 --injector-public-url http://127.0.0.1:16090 --output k8s/cluster16-local.json
```

截至本文交付：已检查清单数量、节点分类、端口、卷挂载和脚本语法，并验证 Docker 不可用时脚本会失败退出。**未完成 Docker 镜像构建、Kubernetes Pod 就绪和 K8s 中完整故障/训练流程的实测。** 这三项需要 Docker 引擎可用后，按本文执行验收，不能用进程版的测试结果代替。


## 补充：Docker Hub 拉取 EOF 时使用镜像源（2026-09-10）

本机后续已成功创建 kind 集群，但 Docker Hub 拉取 Python 镜像报 EOF。已实际通过 DaoCloud 拉取 `docker.m.daocloud.io/library/python:3.12-slim`，并将 `Dockerfile.training` 默认基础镜像改为该地址。该地址用法见 [DaoCloud 镜像源说明](https://github.com/DaoCloud/public-image-mirror)。这是本项目的构建配置，不需要修改 Docker 全局配置或重启引擎。

```powershell
docker pull docker.m.daocloud.io/library/python:3.12-slim
.\start-k8s16.cmd
```

也支持手动指定其他可访问的基础镜像：

```powershell
docker build -f Dockerfile.training --build-arg PYTHON_IMAGE=python:3.12-slim -t fedhelm-cluster:k8s16 .
```

镜像源只解决基础镜像下载；后续 pip、PyTorch 下载失败仍需按实际报错排查。基础镜像拉取成功不等于应用部署成功，仍需完成前面的 Pod 和业务验收。

后续实测结果：已通过 DaoCloud 基础镜像完成 fedhelm-cluster:k8s16 全部构建（退出码 0），并在该 Linux 容器中成功导入 PyTorch 2.14.0+cpu 和 FastAPI 0.135.1。此时两个 kind 节点均 Ready，应用 Deployment 仍待启动脚本部署。


当前自动训练、初始化同步与反馈机制见 [自动联邦训练与反馈闭环](docs/自动联邦训练与反馈闭环.md)。此前文中的手动轮次步骤仍可用于调试。
