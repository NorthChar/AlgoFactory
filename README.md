# AlgoFactory

AI Agent 算法能力工厂原型，目标是能力抽取、代码复刻、独立验证、修复与经验回写。2026-10-29 确定主案例为“基于 BANKING77 的客服意图分类算法生成与验证”，已有客户流失案例保留为轻量兼容性测试，详见 [ADR-001](docs/decisions/0001-banking77-main-case.md)。

Phase 2.5 已实现 BANKING77 文本多分类与客户流失共享的单候选流程，G2.5 已通过：124 项测试零失败、零跳过，BANKING77 最终测试 Macro-F1 0.8787、Accuracy 87.82%，客户流失指标与历史基线一致。训练、Docker 执行、主机独立评分和回写均使用同一核心；Phase 3 修复和候选比较也已通过 Mock 阶段验收：141 项测试、零失败、零跳过。Azure GPT-4o 的真实自动修复、两候选严格比较、选定版本最终测试与回写现已通过；该阶段回归 190 项、零失败、零跳过，累计 20 次请求，最终通过轮为 7 次，见 [真实验收](examples/api-phase3/verification.json) 与 [完整用量及失败记录](examples/api-phase3/campaign-summary.json)。Phase 4 已完成可追溯经验提炼、条件检索、生成/修复消费及开关对照：210 项回归全部通过，Mock/API 各两组对照通过。本次开启与关闭经验均一次修复成功，未观察到收益，开启组多用 1,067 token。Phase 5 已实现本地 Streamlit 工作台、图谱与报告、回归插件及任务恢复；231 项测试通过，CLI/Web 真实隔离运行通过，本阶段新增付费 API 请求为零。详见 [Phase 5 使用与验收](docs/phase5.md)。下一阶段为 Phase 6 集成交付。

## 文档入口

- [题目原文](docs/source/exam-original.txt) 与 [用户方案原始附件](docs/source/discussion-plan-original.txt)
- [总体实施计划与问题定义](docs/implementation-plan.md)
- [主案例调整决策与 Phase 2.5 范围](docs/decisions/0001-banking77-main-case.md)
- [需求追踪矩阵](docs/requirements-matrix.md) 与 [CSV](docs/requirements-matrix.csv)
- [架构、图谱及数据契约](docs/architecture.md)
- [验收 Gate 与演示协议](docs/acceptance-gates.md)
- [Phase 1 使用与验收说明](docs/phase1.md) 与 [实际验证证据](examples/phase1/verification.json)

- [Phase 3 多候选与修复指南](docs/phase3.md)、[Mock 阶段证据](examples/phase3/verification.json) 与 [真实 API 证据](examples/api-phase3/verification.json)
- [Phase 4 经验复用指南与对照结果](docs/phase4.md)及 [验收证据](examples/phase4/verification.json)
- [Phase 5 本地工作台、插件与回归指南](docs/phase5.md)及 [验收证据](examples/phase5/verification.json)
- [Phase 2.5 主案例与兼容性指南](docs/phase25.md) 与 [验收证据](examples/phase25/verification.json)
- [Phase 2 Mock 闭环指南](docs/phase2.md) 与 [运行报告](examples/phase2/normal/report.md)

## 安装与运行

已在 macOS ARM64、Python 3.11.16 验证。使用 uv 的项目环境：

```sh
uv sync --frozen --python 3.11
.venv/bin/python -m algofactory.cli status
.venv/bin/python -m algofactory.cli ingest data/customer_churn.txt --mode mock
.venv/bin/python -m algofactory.cli search --entity-type Algorithm --task-type binary_classification
.venv/bin/python -m algofactory.cli export --output-dir runtime/knowledge-export
.venv/bin/python scripts/verify_phase1.py --output-dir runtime/phase1
```

首次安装依赖需要联网；安装后 Mock 演示与测试无需外部网络或 API Key。测试会在 127.0.0.1 临时启动模拟 HTTP 服务。预期知识导入为 6 个实体、7 条关系，检索返回 3 个候选算法及原文证据；重复导入新增数量为 0。

不用 uv 时，可以使用已有的 Python 3.11：

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m pip install --no-deps -e .
```

requirements.txt 是运行依赖，requirements-dev.txt 另含测试与检查工具；两者从 uv.lock 导出，带版本和文件散列。构建工具由 pyproject.toml 声明。

## Phase 3：比较与修复

```sh
.venv/bin/python -m algofactory.cli demo --task banking77 --compare
.venv/bin/python -m algofactory.cli demo --task banking77 --compare --fault repairable_interface
```

两个候选共用冻结协议，只按验证集排名；每个候选最多两次修复，唯一获胜版本最终测试一次。操作与停止条件见 [Phase 3 指南](docs/phase3.md)。

## 当前主案例：BANKING77

```sh
.venv/bin/python scripts/prepare_sandbox.py
.venv/bin/python -m algofactory.cli prepare-banking77
.venv/bin/python -m algofactory.cli demo --task banking77 --mode mock --db runtime/phase25.sqlite
# 完整阶段验收：源码应已提交，输出目录必须为空
.venv/bin/python scripts/verify_phase25.py --raw-dir runtime/banking77-data/raw
```

首次数据导入从固定官方版本下载，并保留许可、署名与处理记录。BANKING77 是英文、77 类已知意图分类；初始候选为 TF-IDF + Logistic Regression，主指标 Macro-F1。完整说明见 [Phase 2.5 指南](docs/phase25.md)。

## 客户流失兼容性入口

以下入口保留旧命令兼容性，通过同一套改造后的核心执行固定客户流失候选。

先安装并启动 Docker Desktop，然后在项目根目录运行：

```sh
.venv/bin/python scripts/prepare_sandbox.py
.venv/bin/python -m algofactory.cli demo --mode mock
```

首次构建镜像需要联网，生成算法运行时禁网。默认生成 1,500 行客户流失合成数据，以 60/20/20 分层划分；训练 Logistic Regression，输出四维验证报告和知识库记录。每次运行生成新的目录，并打印报告路径。不需要 LLM API Key。

```sh
# 明确注入缺少概率预测接口的故障，预期退出码为 1
.venv/bin/python -m algofactory.cli demo --mode mock --fault missing_predict_proba
# 全量验收，目标目录必须为空；包含真实 Docker 测试和正常/失败示例
.venv/bin/python scripts/verify_phase2.py --output-dir runtime/phase2-verification
```

客户流失 Mock 只接受内置固定需求“根据客户特征预测客户是否流失，输出流失类别和概率。”；BANKING77 使用其独立固定需求，均不表示模型已能理解任意自然语言。数据与阈值校准规则见 [Phase 2 指南](docs/phase2.md)。

## Phase 1 架构与示例

```text
UTF-8 业务文档 → Mock/API Provider → Pydantic 契约与原文引用校验
                                   ↓
                           SQLite 原子化入库
                                   ↓
                   条件检索与来源证据 / JSON / NetworkX GraphML
```

模块位于 src/algofactory：schemas 定义六类核心契约和九类知识实体；llm 提供有预算的结构化调用；knowledge 负责抽取、持久化、检索及导出；cli 提供上述命令。

示例关系包括 `Task REQUIRES Capability`、`Algorithm IMPLEMENTS Capability` 和 `Algorithm APPLICABLE_TO Task`。文档引用采用原始字符区间，每条知识保存 source_id、source_span 和 schema_version。完整定义见 [架构](docs/architecture.md)，实际结果见 [知识 JSON](examples/phase1/knowledge.json) 和 [GraphML](examples/phase1/knowledge.graphml)。

Mock 使用人工编写、按原文散列匹配的固定 fixture。未知文档会明确失败；API 使用相同抽取及校验流程，可处理新文档。API 端点、模型、密钥与价格需显式配置，详见 [Phase 1 指南](docs/phase1.md)。Azure GPT-4o Responses 已完成真实连接、抽取、规划、生成与自动修复、严格两候选比较、最终测试和回写。配置、用量及失败证据见 [真实 API 接入记录](docs/api-integration.md)。

## 测试与产物

```sh
.venv/bin/python -m pytest -q
# 已准备 Docker 镜像时，显式启用真实容器测试
ALGOFACTORY_DOCKER_TESTS=1 .venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m algofactory.cli schemas --output-dir runtime/schemas
```

验收脚本生成知识 JSON、SQLite、GraphML、检索结果、调用轨迹、测试日志和 verification.json。报告记录命令、环境、代码提交/散列及产物散列。Phase 1 证据保留在 examples/phase1；Phase 2 的完整验收脚本包含 Docker 实跑、独立指标、失败拦截和回写。未启用 Docker 的普通测试会跳过容器用例，不能作为闭环验收。

## 最终交付进度

1. 背景和目标：见本页及实施计划。
2. 架构和模块：契约、知识、编排、生成、隔离执行、验证及回写已实现。
3. 图谱 Schema 和示例：类型化 Schema、持久知识与可重载导出。
4. Agent 工作流：单候选流程及角色调用轨迹；Review 当前由确定性程序判断。
5. 环境与运行：Python 3.11、锁定依赖、Docker、CLI 和 API 配置指南。
6. 示例数据和任务：BANKING77 已完成固定版本导入、去重、训练/验证划分及真实运行；合成客户流失保留为兼容性测试。
7. 生成代码示例：见 examples/phase2/normal/candidate.py。
8. 验证结果与报告：四维结果、验证/测试指标及失败报告见 examples/phase2。
9. 挑战和解决方案：来源追踪、事务失败、隔离运行、测试标签隔离及冻结门槛。
10. 扩展方向：Phase 2.5 已通过；Phase 3 比较与修复的 Mock 及真实 API 验收已通过；Phase 4 经验复用机制及小规模效果对照已通过，未观察到收益；Phase 5 界面、插件、合成回归和异常恢复验收已通过；下一步为 Phase 6 冷启动与集成交付。

## 工作区与版本管理

此目录为独立本地 Git 仓库。每阶段验收后形成提交，原始资料保持不变。运行产物放 runtime/，经核验的交付样例纳入 examples/。密钥与私人数据禁止提交。


## 本地可视化工作台（Phase 5）

```sh
uv sync --extra web --locked
.venv/bin/python -m streamlit run src/algofactory/web/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

打开 <http://127.0.0.1:8501>，默认 Mock、BANKING77 比较和验证集评估。可查看报告、候选代码、经验来源与图谱，后台任务可在刷新后恢复查看。回归扩展使用连续值预测及 MAE/RMSE；客户流失继续通过 CLI 验证。界面仅供本机使用，真实 API 需主动选择，单次任务最多 12 次请求。数据和批准镜像需先准备，详见 [操作指南](docs/phase5.md)。
