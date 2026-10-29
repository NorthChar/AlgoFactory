# Phase 2：Mock LLM 单候选流程验证

本页保留客户流失案例的历史实现与验收说明。2026-10-29 已确认 BANKING77 为新主案例，客户流失转为轻量兼容性测试；新适配尚未实现，后续先执行 Phase 2.5，再进入 Phase 3，见 [ADR-001](decisions/0001-banking77-main-case.md)。下述命令当前仍运行客户流失，不运行 BANKING77。

本阶段用固定 Mock 响应验证需求到结果回写的完整路径。算法代码在真实 Docker 容器里训练、预测，指标由主机上的独立评分器计算。无需提供 API 文件或密钥。真实服务质量、任意需求理解、多候选选择和修复效果不在本阶段证据范围内。

## 运行

在项目根目录安装依赖并启动 Docker Desktop：

```sh
uv sync --frozen --python 3.11
.venv/bin/python -m algofactory.cli sandbox-status
.venv/bin/python scripts/prepare_sandbox.py
.venv/bin/python -m algofactory.cli demo --mode mock
```

构建脚本下载官方 Python 3.11 镜像，记录基础镜像摘要，以 requirements.txt 的版本及散列安装依赖，并生成 runtime/docker-image.json。仅 Dockerfile、依赖文件和受信 worker 进入构建上下文。修改 worker 或依赖后必须重新构建；每次算法执行使用不可变镜像 ID。

默认需求为“根据客户特征预测客户是否流失，输出流失类别和概率。”。Mock 不接受其他任意需求或文档；不支持时会明确失败。首次 demo 生成 runtime/phase2-data，后续复用并校验其指纹；每次 demo 使用新的运行目录，避免覆盖历史报告。

```sh
# 显式故障：缺少 predict_proba；预期失败退出且不访问最终测试阶段
.venv/bin/python -m algofactory.cli demo --mode mock --fault missing_predict_proba
# 另有 unsafe_code、invalid_json 两个故障 fixture
# 查询打印出的 workflow_id
.venv/bin/python -m algofactory.cli workflow-show WORKFLOW_ID --db runtime/phase2.sqlite
# 导出包括实际运行结果的知识图谱
.venv/bin/python -m algofactory.cli export --db runtime/phase2.sqlite --output-dir runtime/phase2-graph
```

## 验证协议

确定性合成数据默认 1,500 行、种子 42，按类别分层划分为 900 行训练、300 行验证、300 行测试。数值特征为 tenure_months、monthly_fee、support_tickets，类别特征为 contract_type，目标为 churn。包含受控缺失值，仅用于流程演示，分数不代表真实业务效果。

仓库自有 Logistic Regression 基线只用训练/验证集校准。每个指标的门槛规则固定为 `max(0.50, floor((验证集基线 - 0.05) * 100) / 100)`，另要求基线 AUC ≥ 0.65、F1 ≥ 0.55。协议、数据和划分散列在候选运行前保存；既有协议不得被静默重新计算。数据预处理在 Pipeline 中，仅对训练集 fit。

生成候选为带缺失值填补、数值标准化及 OneHotEncoder 的 Logistic Regression。验证器检查四个维度：

| 维度 | 实际检查 |
| --- | --- |
| 功能 | fit/predict 真正执行；预测数量、行 ID、类别及概率合法 |
| 接口 | build_pipeline(config)、fit、predict、predict_proba |
| 指标 | F1、ROC-AUC、Precision、Recall 均达到冻结门槛 |
| 稳定性 | 固定种子重复训练一致；缺失列/非法数值被拒绝；未知类别可预测 |

验证通过后写入 selection.json 和独占 test-access.json，才启动最终测试容器。评估标签始终不挂载到容器；主机独立评分。测试未通过即停止，不据测试分数调参。重复性验证创建独立 workflow，但使用同一固定候选与协议，不形成选优循环。

## 隔离与失败证据

每次容器执行限制为 2 CPU、4 GiB、120 秒、128 PID；非 root、禁网、只读根目录、删除 capabilities、禁止提权，只挂载一次性只读输入目录。AST 检查限制代码形态，不能代替 Docker。生成源码不会在主机导入，Docker 缺失或镜像不匹配时禁止执行。

超时/OOM/清理失败分支有模拟 Docker 响应的单元测试；真实容器测试覆盖正常训练、重复一致性、接口失败及模拟 API 适配器闭环。不要将模拟 OOM 用例称为实际内存压测。API 模拟测试不访问外部 LLM。

报告目录保存 candidate.py、task/plan/candidate、冻结协议、检索引用、角色决定、Provider 调用记录、状态轨迹及 JSON/中文 Markdown 报告。容器子目录保存命令、输出、退出状态和清理记录。知识库用同一事务写入实现、数据、验证运行、失败及 workflow 记录；未执行的检查记为 not_run，失败不标成通过。Experience 提炼与复用留待 Phase 4。

## 复现与阶段边界

```sh
# 一般测试不启动 Docker，容器用例会明确跳过
.venv/bin/python -m pytest -q
# 完整阶段检查：包含实际容器、五组 CLI 示例、持久化重开及图谱重载
.venv/bin/python scripts/verify_phase2.py --output-dir runtime/phase2-verification
```

目标目录必须为空。verification.json 汇总命令、测试数量、时间、提交号、代码散列、环境和产物散列。标准留档目录为 examples/phase2；迁移项目路径后，旧报告中的绝对运行路径仅为历史证据，复现应使用新目录。

当前 APIProvider 已有 `demo --mode api` 入口，并与 Mock 共用编排器。真实调用需要按 phase1.md 配置端点、模型、密钥、价格和预算，再独立验收；不自动回退到 Mock。后续先完成 Phase 2.5 主案例适配与兼容性，再于 Phase 3 在 BANKING77 上实现有界修复、版本追踪及至少两个候选的同协议比较。G1–G5 的完整范围仍未通过。


阶段验收已通过：101 项测试、零跳过；独立测试 F1 0.666667、ROC-AUC 0.816260、Precision 0.760870、Recall 0.593220，均达到冻结门槛。参见 [正常报告](../examples/phase2/normal/report.md)、[故障报告](../examples/phase2/missing-interface/report.md) 和 [完整证据](../examples/phase2/verification.json)。
