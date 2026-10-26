# ALFA 数据集训练与评估

原始来源：[CMU AirLab](https://www.cs.cmu.edu/~mmousaei/alfa-dataset/)、[官方数据发布](https://kilthub.cmu.edu/articles/dataset/12707963)。引用 Keipour, Mousaei, Scherer, *ALFA: A Dataset for UAV Fault and Anomaly Detection*, IJRR 40(2–3), 515–520, 2021，DOI: 10.1177/0278364920966642。

## 安装和运行

在项目根目录创建 Python 3.12 虚拟环境；已创建则不要重建：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.training.txt
.\.venv\Scripts\python.exe -m pip install -r requirements.alfa.txt
.\.venv\Scripts\python.exe -m scripts.download_alfa
.\.venv\Scripts\python.exe -m scripts.train_alfa --method extra-trees --repeats 10
.\.venv\Scripts\python.exe -m scripts.train_alfa --method fedhelm --rounds 80 --repeats 1
```

Linux 将解释器路径替换成 `.venv/bin/python`。首次下载约 272 MB 的 processed.zip，只解压 CSV/text；不需要 ROS。下载器从官方 Figshare API 读取文件信息并校验 MD5，保留 `data/alfa/source.json`。

先用一次留出验证运行，再根据算力运行论文指定的 10 次留出：

```powershell
.\.venv\Scripts\python.exe -m scripts.train_alfa --method fedhelm --rounds 80 --repeats 10 --output artifacts/alfa-full
.\.venv\Scripts\python.exe -m scripts.train_alfa --method fedavg --rounds 80 --repeats 10 --output artifacts/alfa-full
```

同一已完成输出不覆盖；需要重跑时换 `--output`。固定随机种子起点 631，每个重复加 1；不同方法使用同一划分。CPU 线程限制为 2，每轮 12 个序列客户端顺序执行，不调用收费语言模型。

## 数据和泄漏防护

- 官方文件中 `no_ground_truth` 序列排除；复合方向舵/副翼飞行单独留出，不加入 5 类闭集。
- 5 类：healthy、engine、elevator、aileron、rudder。
- 每条完整飞行序列只属于训练或测试之一；按故障大类约束 70%/30% 分组留出，少数类至少各一条。
- 2 秒窗口、1 秒步长，10 Hz 因果前值采样；故障起点来自 `failure_status`，跨越/触及起点的窗口剔除。
- 传感器超过 1 秒无新观测的窗口剔除。字段缺失/非有限数直接失败，不静默生成输入。
- 输入白名单包含 IMU 角速度/加速度、6 路 RC 输出、roll/pitch 的 commanded/measured、地速/油门/爬升，共 19 个原始测量通道；额外派生 roll/pitch 控制跟踪残差，共 21 个模型输入。派生量只由控制指令和实测值计算，不含失败标志、文件名、绝对时间、序号或根因文本。
- 归一化只拟合训练窗口。联邦端的本地验证使用训练飞行内每类尾部窗口，并清除与训练集时间重叠的窗口。测试飞行始终隔离。

## 模型与输出

`extra-trees` 是集中式强基线，使用窗口均值、标准差、最小/最大值和首尾差。它用于检查数据确实可学习，不是 FedHELM 的替代名。

`fedhelm` 使用 6 层、32 维紧凑 Transformer、5 类输出；每轮抽取 12 个飞行客户端，本地 2 epochs、batch 32、AdamW。增量执行 Top50% 稀疏和分块 INT8 量化；前三轮冷启动，之后按多样性、验证质量 EWMA、更新方向稳定性 EWMA 加权。没有兼容的验证案例探针时使用验证 F1，不伪造记忆探针分数。类别权重默认使用训练分布的平方根逆频率；`--class-weight-power` 可调节指数，必须只依据验证集选择。

`fedavg` 使用同一编码器、压缩、训练和划分，聚合权重只按样本量。当前未提供 FedProx/SCAFFOLD，不能自动补上它们的实验结果。

输出位于 `artifacts/alfa/<method>/seed-<seed>/`：

- `split.json`：完整飞行 ID 的训练/测试/复合留出名单。
- `model.pt` 或 `model.pkl`：模型及特征配置；只加载自己可信的模型文件。
- `report.json`：Top-1、Macro-F1、逐类 precision/recall/F1、混淆矩阵、正常飞行误报率、检测时延及漏检飞行。
- `predictions.json`：逐窗口预测，可回查时间和飞行。
- `rounds.json`、`client-splits.json`：联邦轮次、客户端贡献和本地训练/验证索引。
- 上层 `summary.json`：重复次数、均值和总体标准差。一次运行的标准差为 0，不代表统计稳定。

检测时延定义为故障发生后首次非正常预测的窗口结束时间减故障时间；漏检单独计数，P50/P95 仅对已检出的飞行计算。该指标不等同于正确根因识别时延。只使用完全位于故障后的窗口，最小可报告时延受 2 秒窗口约束。

## 本机实际运行结果（2026-10-11）

官方 ALFA processed archive 已完成 MD5 校验并转换成窗口样本。命令 `--method extra-trees --repeats 10 --seed 641` 完整训练并评估了 10 个按完整飞行序列隔离的留出划分：准确率 **97.71% ± 1.19%**，Macro-F1 **77.45% ± 9.53%**。逐类平均 F1 为 healthy **98.7%**、engine **95.7%**、elevator **24.5%**、aileron **88.3%**、rudder **80.0%**。这说明数据读取、训练、留出评估和报告链路可运行；总体指标被常见类拉高，elevator 的独立飞行样本很少，不能称为每类都效果良好。

一次 80 轮 `fedhelm` 紧凑编码器运行（原始 19 通道，seed 631）得到准确率 **94.11%**、Macro-F1 **38.76%**；elevator 和 rudder 的测试召回率为 0。加入两个控制跟踪残差、将类别权重指数设为 1 后，另一 80 轮运行（seed 641）得到准确率 **94.15%**、Macro-F1 **36.29%**；elevator、aileron、rudder 的召回率为 0。两次结果都低于论文表 8 的 FedHELM Macro-F1 **61.4%**，所以当前本机结果**没有复现论文报告的联邦性能**。不能把 ExtraTrees 基线的分数写成 FedHELM 的分数，也不能据此声称达到论文表 8。

完整逐次数据位于本地 `artifacts/alfa/residual-features-20261011/extra-trees/`，该目录被 `.gitignore` 排除。每次留出的 `report.json` 可检查完整混淆矩阵和逐类分数；`summary.json` 保存 10 次均值和标准差。紧凑联邦模型明细位于 `artifacts/alfa/verified-20261011/fedhelm/seed-631/` 与 `artifacts/alfa/imbalance-experiment-20261011/fedhelm/seed-641/`。

## 与论文的差异

这是实际可运行的 ALFA 诊断实验入口，**不是对论文表 8 数字的保证**。论文主模型为 384 维、22.6M 参数；本机联邦实验为 32 维紧凑配置。当前没有复合类识别器或联邦记忆融合实验，也不执行无人机自动修复。复合序列只保留供后续开放集评估，不能报告“复合新故障 Top-1”。额外实现控制跟踪残差与训练类别加权；这些差异应在论文实验设置中明确。ALFA 模型与在线业务模型有不同输入和标签，不能交叉下发。
