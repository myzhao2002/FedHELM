# Kubernetes + 实际轻量模型训练

## 本机部署后端变更

Docker Desktop启动时遇到dockerInference运行时端点异常，因此本机入口已切到WSL Ubuntu中原有的独立Docker Engine。集群名改为`fedhelm-wsl`，专用配置`runtime/kubeconfig-fedhelm-wsl`，kubectl上下文`kind-fedhelm-wsl`。`start-k8s.cmd`和`open-k8s.cmd`已指向`scripts.k8s_wsl`；现有Ubuntu应用容器不做删除或重置。下面的Desktop通用方案仍保留为备选，本机请以此段名称为准。

本机查看状态：`.venv\Scripts\python.exe -m scripts.k8s_wsl status`。

## 范围

集群名`fedhelm`，专用kubeconfig为`runtime/kubeconfig-fedhelm`，命名空间`fedhelm`。一个真实Kubernetes控制平面承担边缘服务，三个worker分别标记A/B/C。kind的节点是Linux容器，所有节点仍共享宿主机硬件；不是四台实体服务器。

大小语言模型保持HTTP替身，后续替换`/infer`适配器即可。轻量模型已使用CPU PyTorch实际训练：8维观测输入 → 12维可训练隐层 → 4类分类头，共160个参数。编码层与分类头都参与训练。这个小型工程模型不等同于论文的22.6M参数Transformer。

## 启动

1. 本机默认使用WSL Ubuntu的Docker Engine，确认其能下载Docker Hub镜像。若使用Desktop备选方案，先启动Docker Desktop，再运行`python -m scripts.k8s up`。
2. 首次部署双击`start-k8s.cmd`。这会创建专用集群、构建并加载镜像、部署应用。
3. 已部署后双击`open-k8s.cmd`，打开 http://127.0.0.1:13000/ 。关闭网页不会停止集群。

`start-k8s.cmd`也可用于代码更新，但会重启本命名空间Deployment；请在没有采集/训练操作时运行。不会关闭旧的本地进程平台，不会删除其他集群，也不修改用户全局kubectl上下文。

本机kind二进制位于tools/kind.exe，来自官方v0.33.0并核对官方SHA256：`4b22adaa135368c5a465d56bbd8e520cbea87272a06ca00b6078e7b81515c9fc`。其他机器应自行从https://kind.sigs.k8s.io/docs/user/quick-start/安装对应平台二进制。镜像首次下载较大，失败可重试，已有构建层会复用。

## UI操作

1. 全端同步：从联邦服务加载初始模型。
2. 各节点分别点击“采集训练数据”：会在该节点业务注入4类状态，完成后恢复。每类3次独立事件，共12条；8条训练、4条验证，事件不会跨集合。
3. 全端训练：各端实际执行60轮AdamW训练，上传参数增量和本地验证Macro-F1。
4. 聚合更新：真实加权合并所有节点增量。
5. 全端同步：加载新版本。
6. 手动注入故障并运行诊断处置；成功后可提交案例。

首次全局模型使用明确生成的合成观测预训练，保证冷启动能基本诊断。后续本地训练使用`/collect`采集的实际Kubernetes业务观测。数据和训练日志保留在各节点自己的/data目录，不上传原始训练记录。小样本测试分数不代表论文准确率或真实场景泛化能力。

记忆检索使用固定8维遥测特征空间`telemetry-features-v1`，独立于训练模型的隐层，避免模型版本变化使旧案例向量失效。该方案与论文直接使用学习嵌入不同。

## 故障是什么

| 故障 | 实际动作 | 恢复 |
|---|---|---|
| 服务不可用 | Kubernetes API将本节点business Deployment副本缩为0，等待Pod和访问路径不可用 | 副本恢复1，等待实际健康接口可达 |
| 配置错误 | 在业务Pod内写入错误数据库配置，实际订单HTTP返回503 | 恢复配置文件 |
| 连接池耗尽 | 业务Pod占住4个真实SQLite连接，请求等待后503 | 释放占用连接 |

这里是真实测试工作负载故障，不是物理主机宕机、worker断电或内核级资源故障。未引入Chaos Mesh，不操作宿主机网络。每个故障控制器的ServiceAccount仅能GET/PATCH自己对应Deployment的scale子资源，不能修改其他节点Deployment。业务内部管理端点仅在集群内提供，不做公网暴露。

故障控制器独立于业务Pod，所以即使业务副本为0，仍可接受修复指令。业务成功判定使用真实HTTP观测，动作执行成功本身不代表恢复成功。当前仍采用短窗口验证；不是论文5分钟SLO。

## 存储与实现边界

各Deployment使用所在kind节点的`/var/local/fedhelm/<服务名>`目录作为独立数据存储，Pod重启保留，删除kind集群会丢失。跨节点迁移和生产存储尚未实现。

联邦服务使用项目自定义HTTP协调器，不是Flower。实现实际本地训练、质量评估、标签多样性和当轮余弦稳定性加权聚合；论文中的探针集、EWMA、稀疏量化、攻击防御尚未完成。资源状态/网络配置仍是可注入的模拟数据，不能解释为真实硬件能耗或网络实验。

## 验证和排查

```powershell
.\.venv\Scripts\python.exe -m scripts.k8s status
.\.venv\Scripts\python.exe -m scripts.verify_real --url http://127.0.0.1:13000 --output runtime/k8s-verification.json
kubectl --kubeconfig runtime/kubeconfig-fedhelm --context kind-fedhelm get pods -n fedhelm -o wide
kubectl --kubeconfig runtime/kubeconfig-fedhelm --context kind-fedhelm logs -n fedhelm deployment/agent-a
```

验证脚本会真实注入故障、训练一轮、聚合、同步并验证恢复，运行期间不要同时操作相同节点。完整过程记录到JSON报告。
