# Phase 3：BANKING77 候选比较与有界修复

承接 [ADR-001](decisions/0001-banking77-main-case.md) 和 [Phase 2.5](phase25.md)。本阶段于 2026-10-29 完成 Mock 范围验收（141 项测试、零失败、零跳过），现补齐 Azure GPT-4o 真实修复、严格比较、最终测试和回写证据（最新回归 190 项通过）。历史 Mock 证据保留原样；真实结果见本文末尾。经验复用与界面尚未实现。

## 已验证结果

实现提交 `bdd91bedb19ea00402aca97a9cfddac2b561563f`；源码干净。统一命令、时间、环境、镜像及产物散列见 [verification.json](../examples/phase3/verification.json)。本阶段沿用固定数据处理规则与 Macro-F1 0.82 门槛，没有根据测试成绩修改参数或阈值。

| 候选 | 验证集 Macro-F1 | 验证集 Accuracy | 比较结果 |
| --- | --- | --- | --- |
| TF-IDF + Logistic Regression | 0.872975 | 0.873437 | 排名第一，选中后最终测试 Macro-F1 0.878695、Accuracy 0.878247 |
| TF-IDF + MultinomialNB | 0.826924 | 0.835918 | 验证通过，排名第二，不使用最终测试集 |

正常比较与重复运行的排名、代码和指标一致；获选模型仍是原 Logistic Regression。客户流失所有指标与历史固定候选一致。

| 示例 | 实测结果 | 证据 |
| --- | --- | --- |
| 正常比较/重复 | 两候选均验证通过，只测试获胜版本 | [比较报告](../examples/phase3/comparison/report.md)、[重复报告](../examples/phase3/comparison-repeat/report.md) |
| 注入接口故障 | Logistic Regression 初版缺少 predict_proba；修复一次后验证通过并入选 | [修复报告](../examples/phase3/repair/report.md)、[版本轨迹](../examples/phase3/repair/attempts.json) |
| 持续故障 | 两候选各两次修复，合计六个版本；无合格候选，停止且不测试 | [耗尽报告](../examples/phase3/repair-exhausted/report.md) |
| 无修复进展 | 原样代码被拒绝，停止当前候选；最终无合格候选 | [无进展报告](../examples/phase3/unrepairable/report.md) |
| 总尝试/调用预算 | 上限分别为一次尝试、四次调用；比较未完成即停止 | [尝试预算](../examples/phase3/attempt-budget/report.md)、[调用预算](../examples/phase3/call-budget/report.md) |
| 安全停止 | 危险导入被静态检查拒绝，不进入 Docker 或最终测试 | [安全报告](../examples/phase3/unsafe-code/report.md) |
| 客户流失兼容 | 同一提交、共用核心、固定候选仍通过 | [兼容报告](../examples/phase3/churn-compatibility/report.md) |

所有子流程与最终流程可从重开的数据库查询，父子版本和 GraphML 无损往返已核验。修复故障为明确 fixture，未调用真实外部 LLM。下一步是 Phase 4 的经验提炼、适用条件检索及启用/关闭经验的对照验证。

## 实现及边界

`search.run_search` 是有界协调器。它复用 `orchestrator.run_workflow` 完成每次候选的需求解析、来源知识检索、规划、生成/修复、代码检查、真实 Docker 验证和事务回写；`validation.final_test.evaluate_final` 是单候选及比较模式共用的最终测试入口。客户流失保持一个固定候选，不进入文本候选比较。

两种候选均使用只在训练集拟合的词级 TF-IDF（1–2 gram、sublinear_tf、最多 30,000 词项）：

| 候选 | 初始分类器配置 | 可执行的 Mock 修复/优化 |
| --- | --- | --- |
| text_logistic | LogisticRegression，C=4.0、max_iter=500、seed=42 | 将明确注入的 LinearSVC 缺少概率接口故障改回原定分类器；不进行无依据的参数搜索 |
| text_nb | MultinomialNB，alpha=0.1 | 若验证集未达门槛，按预先定义的 alpha=0.05、0.01 最多尝试两次 |

候选与参数在查看本阶段最终测试前确定，冻结协议继续使用 Phase 2.5 的数据规则与校准方法。新增来源文档 `data/banking77-phase3.txt` 及其独立 Mock fixture；不覆盖原文档或历史阶段证据。

Mock 的生成/修复响应为明确的固定策略。真实 API 适配器使用同一 `repair_code` 请求和契约，输入包括原代码、原代码散列、父版本 ID、实际错误和验证集反馈；已提供模拟 API 传输测试，但不作为真实服务有效性证据。每次尝试通过公共流程重新解析、检索及规划；当前同一比较内只抽取同一内容散列的知识文档一次，后续候选和修复复用已校验知识，并记录 knowledge-input.json。因此首次新尝试通常 4 次 Provider 调用，后续 3 次；调用预算由整个比较流程共享。

## 排名、修复与停止

- 默认两候选，每个候选最多两次修复，即最多三个代码版本；全流程最多六次候选尝试。CLI 可以降低预算，不能突破这两个上限。Mock 比较的 Provider 调用上限默认为 32 次（包括结构化响应重试）；API 沿用配置上限，或显式传 `--llm-call-budget`，费用上限仍独立生效。
- 功能、指标、接口、稳定性全部通过的版本标为 `validated`，含义仅是验证集通过。先按验证集 Macro-F1 降序，再按 Accuracy 降序，完全相同时按冻结候选顺序排名。排名不读取测试成绩、运行耗时或其他不可重复因素。
- 接口/执行/稳定性问题产生 REPAIR 决策；指标未达标产生 OPTIMIZE；候选结束后可 SWITCH。修复输入使用真实错误类别及验证集结果，不包含测试标签、测试预测或测试指标。
- 每个版本保留 candidate.json、原始代码、四维报告、修复输入和 diagnosis.json；修复后的知识实体保存 parent_id、递增版本号及 DERIVED_FROM 关系。失败版本保留，不覆盖。最终测试记录关联被选中的同一个实现实体，不创建虚假的“修复版本”。
- 相同代码原样返回时停止当前候选（unrepairable_no_change）；达到修复上限停止当前候选（repair_budget_exhausted）；没有合格候选时整体停止。总尝试/调用/费用预算耗尽时整体停止，即使已有部分候选通过，也不把未完成比较当作成功。
- 安全、数据完整性、知识回写和服务错误停止整个流程，不通过再次生成绕过。资源超时等可修复错误仍受原执行预算及两次修复上限约束。
- 所有候选只接触训练数据和验证特征。排名保存后锁定唯一获胜版本，写入一次性 test-access.json，再执行一次最终测试。最终测试失败或超时立即结束，不修复、不换第二名、不重新比较。

报告根目录的资源数值对应被选版本的验证和最终测试；各失败/未选版本资源分别保存在子报告。budget_usage 记录总尝试与 Provider 调用数。独立 LLM Review 和已验证经验提炼不在本阶段，Review 决策仍由确定性规则产生。

## 使用

先完成根 README 中的依赖安装、数据导入与 Docker 镜像准备。镜像 worker 和依赖在本阶段没有变化，无须仅因新增候选重建；DockerExecutor 仍会核验镜像身份。

```sh
# 两候选正常比较
.venv/bin/python -m algofactory.cli demo --task banking77 --compare --db runtime/phase3.sqlite
# 明确的故障 fixture：失败 → 修复 → 重新验证 → 统一排名 → 最终测试
.venv/bin/python -m algofactory.cli demo --task banking77 --compare --fault repairable_interface --db runtime/phase3.sqlite
# 两候选持续缺少概率接口，每个都达到两次修复上限；预期退出码 1
.venv/bin/python -m algofactory.cli demo --task banking77 --compare --fault persistent_interface
# 修复没有代码变化；预期退出码 1
.venv/bin/python -m algofactory.cli demo --task banking77 --compare --fault unrepairable
# 总尝试预算不足以完成比较；预期退出码 1
.venv/bin/python -m algofactory.cli demo --task banking77 --compare --attempt-budget 1
# 客户流失仍通过同一公共流程执行固定候选
.venv/bin/python -m algofactory.cli demo --task churn
```

上述故障均为显式注入，不冒充真实 LLM 自然出错。`--compare` 只对 BANKING77 开放；不指定该选项仍保留原单候选行为。

## 阶段验收

实现源码提交后运行，输出目录必须为空：

```sh
.venv/bin/python scripts/verify_phase3.py --raw-dir runtime/banking77-raw --output-dir runtime/phase3-verification
```

脚本覆盖全量测试（必需测试零跳过）、正常比较及重复、可修复故障、两次修复耗尽、无进展、尝试/调用预算耗尽、安全停止、客户流失兼容，并核验数据库重开、父版本、完整图谱和稳定排名。候选和获胜版本均真实 Docker 执行；最终测试失败/超时后的禁止重选、API 反馈传输和部分异常处理使用明确的单元模拟，不冒充实际服务或资源压力测试。

产物包含 search-config.json、attempts.json、ranking.json、decisions.json、candidates/ 下的代码版本与反馈、最终报告及知识库；统一 verification.json 保存命令、源码提交、时间、环境、镜像身份和产物散列。完整预测矩阵按 Phase 2.5 的无损 gzip 约定归档，解压后散列与原报告一致。

本阶段验收跟踪 BK07/A02/A03/X06 的 Mock 范围。当时 G2 的真实 API 项尚未完成，现由下方增量证据补齐；完整 G3/G4/G5 及 Phase 4 经验对照不因此自动完成。

## 真实 API 补验收（2026-10-29，verified）

最终实现提交 `3c305f6`，完整源码和测试散列见 [verification.json](../examples/api-phase3/verification.json)。最新回归 190 项通过，0 失败、0 错误、0 跳过，包含真实 Docker 与客户流失兼容；本次真实服务为 Azure `gpt-4o`，无故障 fixture、无人工修改模型生成代码。

| 候选/版本 | 实际结果 | 验证集 Macro-F1 | 最终测试 Macro-F1 |
| --- | --- | --- | --- |
| Logistic Regression 历史 v1 | 真实 `worker_ValueError`；复用原始失败证据，不冒充新执行 | 未完成 | 未访问 |
| Logistic Regression 自动修复 v2 | GPT-4o 补上 ColumnTransformer 和标量文本选择器，四维及参数校验通过，排名第一 | 0.8729749094 | 0.8786952176 |
| MultinomialNB v1 | 模型生成符合预定参数的代码，四维及参数校验通过，排名第二 | 0.8269238047 | 未访问 |

获选版本最终 Accuracy 0.8782467532。原失败、修复输入、代码散列、父子关系、验证集分数及唯一测试预约均已保存；重开 SQLite 与 GraphML 无损往返通过。最终版本未经过人工代码修改，验证器没有降低门槛。

本次增加两项必要支持：

- `resume_failures` 只接纳未访问最终测试、初始版本、失败且可修复、已回写且与当前数据/协议一致的记录。原始代码及产物散列、数据库版本和算法引用全部核对后才进入已有修复循环；历史尝试计入六次总尝试限额，新增调用单独计数。
- 对返回的实际 Pipeline 做静态参数检查，要求两个候选均使用预先指定的 TF-IDF 参数及各自分类器参数。只解析受限语法，不在宿主导入或执行生成代码；检查不通过时保存 `configuration-check.json`，以 `algorithm_configuration_mismatch` 进入有限修复。传入模型的 `required_configuration` 来自原定配置，不从最终测试分数推导。

三轮记录分别保留：[首轮及人工复核限制](../examples/api-search-initial/review.json)、[结构响应失败轮](../examples/api-search-structured-failure/verification.json)、[最终严格通过轮](../examples/api-phase3/verification.json)。首轮已完成真实修复和运行，但 NB 省略约定参数，不能作为严格比较退出证据；第二轮在 NB 规划结构校验处停止、未访问测试；第三轮全部通过。总请求 **7 + 6 + 7 = 20**，没有自动重试，最终轮用掉其 7 次上限。失败和费用不从总账中剔除。

三轮为独立 workflow；首轮与最终轮各对其唯一获胜版本评估一次，中间轮没有测试。两次测试使用相同既定 LR 参数、数据与冻结门槛，测试结果未提供给修复请求或选优规则。此证据证明本次工作流可完成真实自动修复与比较，不声称任意模型响应都正确或服务成功率已统计稳定。

复现入口会消耗真实额度，必须使用新输出目录；历史数据库只读备份，不修改原始失败证据：

```sh
ALGOFACTORY_DOCKER_TESTS=1 .venv/bin/python -m pytest -q --junitxml=runtime/live-search-tests.xml
.venv/bin/python scripts/verify_live_search.py --env-file .env --resume-failure runtime/plan-retest-20261029-02/single-candidate --resume-db runtime/plan-retest-20261029-02/knowledge.sqlite --tests-xml runtime/live-search-tests.xml --call-budget 20 --output-dir runtime/live-search-new
```

归档版失败产物中的 `predictions.json.gz` 须按散列还原后才能作为恢复输入；历史源码及 runtime 路径可能不在新机器存在，复现前需恢复相应失败目录和知识库。新机器冷启动仍由 Phase 6 验收。

当前已具备进入 [Phase 4](phase4.md) 的条件；经验提炼与复用对照仍需独立实现和验收。
