# AlgoFactory

基于 BANKING77 的客服意图分类算法生成与验证。主线覆盖知识抽取、方案规划、代码生成、隔离训练、独立验证、有界修复、候选比较与经验回写。当前开发版本 **0.7.0**（交付复现进行中），增加数据浏览、隔离预测与可配置实验，见 [版本变更](CHANGELOG.md)。0.6.0 的 Phase 1–6 在声明范围内已验收（Phase 6 冷启动 233 项测试、零跳过），见 [历史交付记录](docs/phase6.md)；不将旧测试数量当作当前增量的全量验收。

## 1. 项目背景和目标

本项目验证 AI 生成算法的可执行性与可追溯性：输入业务需求和知识材料，输出 Python 算法、验证报告、代码版本及持久化知识。没有合格候选时明确失败。主案例是英文银行客服的 77 类已知意图分类；合成客户流失和回归任务用于验证公共框架兼容性。

[原题](docs/source/exam-original.txt)和[原始讨论方案](docs/source/discussion-plan-original.txt)保持原样；[实施计划](docs/implementation-plan.md)、[主案例决策 ADR-001](docs/decisions/0001-banking77-main-case.md)及[需求矩阵](docs/requirements-matrix.md)记录范围变化及验收状态。

## 2. 系统架构和模块设计

```text
业务文档 / 自然语言需求
  → Mock 或 API Provider → 类型及引用校验 → SQLite 知识库
  → 条件检索 → 算法方案 → 代码生成 → 静态检查
  → Docker 训练与预测 → 主机独立评分 → 有界修复 / 验证集排名
  → 选定版本最终测试 → 报告、版本和经验回写
                            ↓
                   CLI / Streamlit / GraphML
```

`src/algofactory` 中的 `schemas` 定义契约，`llm` 管理结构化调用与预算，`knowledge` 管理持久知识，`orchestrator` 与 `search` 编排任务，`execution` 隔离运行，`validation` 独立评分，`plugins` 注册可信模板及指标，`web` 提供本地工作台。SQLite 降低运维成本，Pydantic 保证接口一致，scikit-learn 支持 CPU 轻量模型，NetworkX 支持图谱导出。详见[架构与边界](docs/architecture.md)。

## 3. 知识图谱 Schema 和示例

知识包含任务、能力、算法、数据集、实现、验证和经验等类型化实体及关系。例如 `Task REQUIRES Capability`、`Algorithm IMPLEMENTS Capability`、`Algorithm APPLICABLE_TO Task`。知识保存稳定 ID、来源字符区间和 Schema 版本；验证记录关联实际代码散列、父版本及运行 ID。

可检查[知识 JSON](examples/phase1/knowledge.json)、[GraphML](examples/phase1/knowledge.graphml)及[Schema 设计](docs/architecture.md)。导出和检索：

```sh
.venv/bin/python -m algofactory.cli ingest data/customer_churn.txt --mode mock
.venv/bin/python -m algofactory.cli search --entity-type Algorithm --task-type binary_classification
.venv/bin/python -m algofactory.cli export --output-dir runtime/knowledge-export
.venv/bin/python -m algofactory.cli schemas --output-dir runtime/schemas
```

## 4. Agent 工作流设计

知识、构建、审查是三个逻辑角色，分别负责证据检索、方案/代码生成、确定性验收。它们共享编排与显式契约；目前不是三个独立自治进程。每个阶段记录输入、输出、判断和停止原因。

比较模式使用冻结数据协议、两种候选及每候选最多两次修复；只依据验证集选择。最终测试每次工作流仅允许选定版本评估一次，结果不用于修复或重新选择。失败经验必须有关联的失败、修复和重测证据；搜索开始后冻结经验库，避免同轮污染。详见[修复与比较](docs/phase3.md)、[经验复用](docs/phase4.md)。

## 5. 环境配置和运行方法

已验证平台为 macOS ARM64、Python 3.11。需安装 uv，启动 Docker Desktop。取得私有仓库访问权限后，可先运行 `git clone https://github.com/NorthChar/AlgoFactory.git`，进入 `AlgoFactory` 目录再执行下列命令。首次安装依赖及构建镜像需要网络，生成代码执行时禁网。`uv.lock` 与三个 `requirements*.txt` 固定版本和散列，构建工具也固定版本。

```sh
uv sync --extra web --locked --python 3.11
.venv/bin/python -m algofactory.cli status
.venv/bin/python scripts/prepare_sandbox.py --base-image python@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60
.venv/bin/python -m algofactory.cli prepare-banking77 --raw-dir examples/phase25/banking77-data/raw
.venv/bin/python -m algofactory.cli demo --task banking77 --mode mock --db runtime/demo.sqlite
.venv/bin/python -m algofactory.cli demo --task banking77 --compare --fault repairable_interface
.venv/bin/python -m streamlit run src/algofactory/web/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

打开 [本地工作台](http://127.0.0.1:8501)，默认 Mock、BANKING77 比较与验证集评估，可查看代码、报告、图谱及经验来源。刷新可恢复查看后台任务，取消会保留状态。操作见 [Phase 5 指南](docs/phase5.md)。

首次使用默认进入“从这里开始”，通过银行客服例子了解工作台用途和三项交付物：算法代码、验证报告、开发过程记录。点击“看一个已经完成的例子”直接进入历史报告，先查看生成文件，再按 a–g 七步查看依据。点击“我想试着生成一次”进入新建任务，不会立即提交或调用模型。新任务报告会在产出后自动选中；历史案例有独立标识。当前输入输出和算法候选受案例协议约束，尚不支持上传自己的数据或任意业务任务。

Mock 无需密钥，只接受内置任务及文档 fixture；API 使用同一契约且不会静默降级。真实 Azure GPT-4o 接入配置见 [API 指南](docs/api-integration.md)。从 `.env.example` 复制为被忽略的 `.env` 后在本机填写密钥；不要将密钥填入示例文件。显式选择 API 会产生费用，需设置请求次数限制；本阶段复验使用 Mock。

```sh
# 完整测试必须先准备数据及批准镜像；未启用 Docker 的普通测试会跳过容器用例
ALGOFACTORY_DOCKER_TESTS=1 .venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests scripts
# 源码与文档须全部提交，输出目录必须尚不存在
.venv/bin/python scripts/verify_phase6.py --output-dir runtime/phase6-cold-start
```

该脚本从 Git 提交创建独立副本、全新环境、非 editable wheel，并无缓存安装依赖及重建容器。复现边界及日志见 [Phase 6](docs/phase6.md)。

## 6. 示例数据和测试任务

| 任务 | 数据及划分 | 模型与指标 |
| --- | --- | --- |
| BANKING77 主案例 | 官方固定版本；去重后训练侧按 80/20 分层划分；保留官方测试集 | TF-IDF + Logistic Regression / MultinomialNB；Macro-F1、Accuracy |
| 客户流失兼容性 | 固定种子生成 1,500 行；60/20/20 分层划分 | Logistic Regression；F1、ROC-AUC |
| 回归扩展 | 固定种子生成 600 行；60/20/20 划分 | Ridge；MAE、RMSE（越低越好） |

BANKING77 来源 PolyAI，作者 Iñigo Casanueva、Tadas Temcinas、Daniela Gerz、Matthew Henderson、Ivan Vulić（2020），论文 *Efficient Intent Detection with Dual Sentence Encoders*。保留[原许可 CC BY 4.0](examples/phase25/banking77-data/raw/LICENSE)，固定上游提交为 `57ec275d8078af65b7731c2a98be812d844a6d6b`；去重和划分属于本项目的处理，详见[导入协议](docs/phase25.md)。客户流失和回归是合成数据，不代表真实业务效果。

```sh
.venv/bin/python -m algofactory.cli demo --task churn --mode mock
.venv/bin/python -m algofactory.cli demo --task regression --mode mock
```

## 7. 生成算法代码示例

[真实 API 生成并修复后的 BANKING77 算法](examples/api-phase3/comparison/candidate.py)与[对应报告](examples/api-phase3/comparison/report.md)包含完整来源链。当前 Mock 演示可检查 [BANKING77](examples/phase5/banking77/candidate.py)、[客户流失](examples/phase5/churn/candidate.py)及[回归](examples/phase5/regression/candidate.py)代码。

代码必须符合任务接口，并在隔离容器内加载、训练、输出预测。主机保管评分标签并计算指标；回归输出连续值，不沿用分类概率契约。模板/指标插件由可信代码显式注册，不能把任意不受信任模块加载到主机评分进程。

## 8. 验证结果和报告样例

[Phase 6 冷启动验收](examples/phase6/verification.json)在独立副本、全新环境、非 editable wheel 与无缓存重建镜像上通过 233 项测试，0 失败、0 错误、0 跳过；三类 CLI、两类 Web、实际超时清理与服务健康检查通过。新增付费 API 请求为 0，三个任务指标与 Phase 5 一致。[交付索引](examples/phase6/README.md)包含包、报告及早期尝试记录。

[Phase 5 验收](examples/phase5/verification.json)记录 231 项测试全部通过，CLI 三任务、Web 两任务、图谱、取消及真实一秒超时清理通过。主案例最终测试 Macro-F1 0.878695、Accuracy 0.878247；客户流失 F1 0.666667、ROC-AUC 0.816260；回归 MAE 0.405306、RMSE 0.501081。指标仅适用于归档的数据协议和候选。

[真实 API Phase 3](examples/api-phase3/verification.json)通过生成、训练、修复、严格比较、最终测试和回写；[完整总账](examples/api-phase3/campaign-summary.json)保留全部 20 次请求及失败轮次。[Phase 4](examples/phase4/verification.json)的 Mock/API 各两组经验开关对照均通过机制验收，但未观察到修复次数或指标收益，开启组多用 1,067 token。

历史报告按当时提交保留；哈希完整不代表其中每次失败尝试都通过语义验收。统一验证维度为功能、指标、稳定性、接口。当前交付状态见 [Phase 6](docs/phase6.md)，Gate 定义见[验收协议](docs/acceptance-gates.md)。

## 9. 挑战和解决方案

- 生成内容可能不合法：结构化契约、来源引用校验、静态检查、真实容器执行及确定性审查逐层约束。
- 评估可能泄漏：冻结划分和门槛，预处理仅训练集拟合，标签留在主机，验证排名与最终测试分开。
- 修复可能无限循环或耗费 API：限制候选、修复轮次、总请求、输出长度和执行时间，保留失败状态。
- 历史经验可能失真：只复用有重测证据且协议匹配的记录，保存引用并进行开关对照，不把机制通过描述成效果提升。
- 生成代码有执行风险：非 root、只读文件系统、禁网、资源/时间限制；缺少批准镜像时拒绝执行。OOM 等部分异常目前以模拟测试覆盖，不声称完成真实资源压测。
- 交付可能依赖开发环境：版本/散列锁定，独立副本和 wheel 安装复验，文档链接与历史产物哈希检查，发布前检查当前密钥及高置信凭据模式。

## 10. 后续可扩展方向

[Phase 7 可操作工作台](docs/phase7.md) 已实现数据与验证错误浏览、模型保存及单条英文预测、受限实验配置；7D 独立复现进行中。先按 [工作台使用指南](docs/workbench-guide.md) 完成一次无费用操作。范围决定见 [ADR-002](docs/decisions/0002-interactive-workbench.md)。

Phase 7 完成后再评估题目中的自动接口文档或资源消耗分析；任意数据上传、自然语言自动适配新任务、自动回复机器人、生产部署、Beam/MCTS 及跨业务效果保证不在当前增量范围内。

项目已发布至私有仓库 [NorthChar/AlgoFactory](https://github.com/NorthChar/AlgoFactory)，默认分支为 `main`；访问需要仓库授权。源码、文档及脱敏验收产物进入 Git，`.env`、本地运行数据、缓存及开发环境不上传。阶段提交与[需求矩阵 CSV](docs/requirements-matrix.csv)保持可追溯；仓库私有属性、远端提交及完整文件树已核对，见[发布证据](examples/phase6-publication/publication.json)和 [Phase 6](docs/phase6.md)。
