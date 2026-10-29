# Phase 3：BANKING77 候选比较与有界修复

承接 [ADR-001](decisions/0001-banking77-main-case.md) 和 [Phase 2.5](phase25.md)。当前实现完成，阶段验收待归档；真实外部 API、经验复用与界面仍待后续阶段。

## 实现及边界

`search.run_search` 是有界协调器。它复用 `orchestrator.run_workflow` 完成每次候选的需求解析、来源知识检索、规划、生成/修复、代码检查、真实 Docker 验证和事务回写；`validation.final_test.evaluate_final` 是单候选及比较模式共用的最终测试入口。客户流失保持一个固定候选，不进入文本候选比较。

两种候选均使用只在训练集拟合的词级 TF-IDF（1–2 gram、sublinear_tf、最多 30,000 词项）：

| 候选 | 初始分类器配置 | 可执行的 Mock 修复/优化 |
| --- | --- | --- |
| text_logistic | LogisticRegression，C=4.0、max_iter=500、seed=42 | 将明确注入的 LinearSVC 缺少概率接口故障改回原定分类器；不进行无依据的参数搜索 |
| text_nb | MultinomialNB，alpha=0.1 | 若验证集未达门槛，按预先定义的 alpha=0.05、0.01 最多尝试两次 |

候选与参数在查看本阶段最终测试前确定，冻结协议继续使用 Phase 2.5 的数据规则与校准方法。新增来源文档 `data/banking77-phase3.txt` 及其独立 Mock fixture；不覆盖原文档或历史阶段证据。

Mock 的生成/修复响应为明确的固定策略。真实 API 适配器使用同一 `repair_code` 请求和契约，输入包括原代码、原代码散列、父版本 ID、实际错误和验证集反馈；已提供模拟 API 传输测试，但不作为真实服务有效性证据。每次尝试仍通过公共流程重新解析、检索及规划，所以单次尝试通常消耗 4 次 Provider 调用；调用预算由整个比较流程共享。

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

本阶段验收跟踪 BK07/A02/A03/X06 的 Mock 范围。完整 G2 仍需要真实 API；完整 G3/G4/G5 及 Phase 4 经验对照不因本阶段通过而自动完成。
