# Phase 4：已验证经验提炼与复用

状态：**verified，限 BANKING77 同一冻结协议下的文本适配经验。** 实现提交 `0a5234f`；210 项回归测试全部通过，0 失败、0 错误、0 跳过。Mock 与 Azure GPT-4o 各完成两组开关对照，共八个真实 Docker 验证流程；客户流失兼容检查通过。证据见 [verification.json](../examples/phase4/verification.json)、[预先固定的实验方案](../examples/phase4/experiment-plan.json) 与 [独立复核](../examples/phase4/review.json)。

**此次验证了经验沉淀、检索、传入、采用声明与重测链路；没有观察到修复次数、成功率或分类指标提升。** 开启经验的 API 组多用 1,067 个 token。样本只覆盖一个已知接口故障，不据此声称一般性收益或一般性无效。

## 已实现的能力

| 工作 | 实现与边界 | 证据 |
| --- | --- | --- |
| 经验提炼 | 从失败→代码修改→真实验证通过链做确定性的结构差异归纳；当前识别缺失 DataFrame 文本适配器这一规则 | learned-experience.json、knowledge.json |
| 来源验证 | 核对代码、报告、产物散列、失败/成功运行、父子实现、算法、数据和配置；拒绝包含最终测试结果的来源 | 测试、DERIVED_FROM 两条来源关系 |
| 状态区分 | 能识别且有重测证据的规则为 verified；成功但原因未识别的修复为 proposed，不进入自动复用 | tests/test_experience.py、tests/test_experience_workflow.py |
| 条件检索 | 仅匹配任务、文本字段、算法、DataFrame 接口、数据指纹、划分、配置及修复错误类型；最多返回三条 | experience-retrieval.json、experience-library.json |
| 生成/修复消费 | 显式开关；保存原始 builder-input、模型采用/不适用理由、输出是否满足规则；不接受虚构经验 ID | builder-input.json、experience-use.json、decisions.json |
| 回写与隔离 | 支持显式提炼及搜索中自动学习；同一搜索开始时冻结经验库，新学经验供以后流程使用 | learned-experiences.json、SQLite、图谱重载、幂等测试 |
| 对照与兼容 | 验证集专用模式、同条件开关对照、小规模真实 API 重复；旧模式关闭经验时保持原状态轨迹 | 八个实验报告、churn/report.json、210 项回归 |

经验包含失败/修复代码散列、失败与重测运行 ID、适用条件和结构规则。`ExperienceRecord.repair_evidence` 是可选扩展，旧经验格式仍可读取，但缺少结构化修复证据的旧记录不能自动进入此次复用。图谱校验要求失败与成功运行对应同一数据/协议，成功实现必须直接继承失败实现；经验同时关联两次运行。

主机只解析受限 Python AST，不导入或执行候选代码。验证器检查返回流水线及既定参数；经验文本不能覆盖任务、安全规则、冻结参数或评分条件。模型声明采用不等于代码已正确应用，更不等于因果收益，因此分别保存声明、规则检查和独立评分。

## 经验来源与后续任务

经验来源为上一阶段的 [真实失败](../examples/api-phase3/comparison/candidates/text_logistic/attempt-0/report.json) 和 [自动修复后通过的验证](../examples/api-phase3/comparison/candidates/text_logistic/attempt-1/report.json)：原代码直接把 DataFrame 交给 TF-IDF，修复版增加 ColumnTransformer 并使用标量文本列选择器。算法构造器参数保持一致，重测通过。来源不包含先前人工修改的诊断版本。

后续实验使用新的任务描述：“为另一个调用方复用相同 BANKING77 输入协议，请生成并验证可接收 DataFrame 的 77 类英文客服意图分类组件。”每次产生独立 workflow 和代码版本，但仍使用同一冻结数据与算法。这是已知失败的重放与新任务中的复用验证，不是未见故障或新业务迁移实验。

- Mock 对照使用显式 `text_adapter` fixture，两组初版故障代码一致；故障注入会覆盖生成结果，Mock 采用声明仅模拟传递流程，不能用来证明模型推理或收益。
- API 对照恢复同一份真实历史失败；复用此前真实 API 已抽取并校验的文档知识，不重复付费抽取，也不以 Mock 生成替代本轮真实修复。
- 两组数据库从同一个经验库快照复制；顺序为关闭、开启、开启、关闭。提示主干、输出契约、初始故障、模型配置、数据、评分规则和预算保持一致，差异为经验输入及不可避免的新运行 ID。
- 每个 API 实验最多三次新请求（需求解析、规划、修复），一个修复机会；四次实验合计最多十二次，无自动重试。实验方案在模型调用前保存。
- 八个 BANKING77 经验对照流程只使用验证集，没有最终测试预约或测试分数；回归套件仍验证已有最终测试路径，客户流失兼容流程仍按原协议运行最终测试。对照结果不用于修改测试门槛或模型参数。

## 实测结果

| 模式 | 经验开关 | 实验成功 | 每次修复调用 | 每次新 Provider 调用 | 验证集 Macro-F1 |
| --- | --- | --- | --- | --- | --- |
| Mock | 关闭 | 2/2 | 1 | 6 | 0.8729749094 |
| Mock | 开启 | 2/2 | 1 | 6 | 0.8729749094 |
| Azure GPT-4o | 关闭 | 2/2 | 1 | 3 | 0.8729749094 |
| Azure GPT-4o | 开启 | 2/2 | 1 | 3 | 0.8729749094 |

Mock 每次重新产生显式故障再修复；API 从既有失败恢复，所以两种模式的调用数不作横向成本比较。两次 API 开启实验均返回 adopted，且实际代码通过结构与参数检查。全部结果为 validated，仅表示通过验证集；不冒充一次新的最终测试结果。

| API 组（各两次实验） | 输入 token | 输出 token | 合计 |
| --- | --- | --- | --- |
| 关闭经验 | 7,402 | 984 | 8,386 |
| 开启经验 | 8,269 | 1,184 | 9,453 |

共 **12 次请求，输入 15,671、输出 2,168 token，0 次自动重试**；本轮付费调用已停止。价格配置未知，程序中的实际费用为 null；[独立复核](../examples/phase4/review.json)只提供先前公开价格快照的参考情景，不作为账单。

本次基线提示已经明确说明文本适配方式，关闭经验同样一次修复成功，因此没有观察到降低修复次数或提升指标。开启组增加上下文和采用说明，实测总 token 较多。两个配对实验不足以估计一般成功率；后续若研究收益，应预先增加不同故障类别与独立任务样本，保留负结果，而不是削弱基线或制造更容易的开启组。

## 使用与复现

普通模式默认关闭经验。先复制已有证据库到工作目录，保留 examples 中的历史档案：

```sh
cp examples/api-phase3/knowledge.sqlite runtime/phase4.sqlite
.venv/bin/python -m algofactory.cli learn-experience --db runtime/phase4.sqlite --algorithm text_logistic --failed-dir examples/api-phase3/comparison/candidates/text_logistic/attempt-0 --repaired-dir examples/api-phase3/comparison/candidates/text_logistic/attempt-1
.venv/bin/python -m algofactory.cli experience-search --db runtime/phase4.sqlite --dataset-dir runtime/banking77-data --algorithm text_logistic --failure-category worker_ValueError

# 采用已有经验并记录版本，仍走原有隔离、参数检查和评分路径。
.venv/bin/python -m algofactory.cli demo --task banking77 --compare --experiences --reuse-knowledge --validation-only --db runtime/phase4.sqlite --output-dir runtime/phase4-demo-new

# 对支持的修复链自动提炼；新经验不在同一搜索内消费。
.venv/bin/python -m algofactory.cli demo --task banking77 --compare --fault text_adapter --learn-experiences --validation-only --db runtime/phase4-new.sqlite --output-dir runtime/phase4-learning-new
```

提炼可直接核对归档的无损 gzip 预测产物；使用同一对报告重复提炼，实体和关系新增数为零。`--reuse-knowledge` 显式复用同内容文档知识，避免模型重新抽取造成不可变 ID 冲突；它不跳过图谱校验。`--validation-only` 不打开最终测试；不指定该选项时，正常搜索仍仅测试唯一获选版本。

完整阶段验证要求已提交实现、固定 BANKING77 数据和已批准 Docker 镜像；输出目录必须新建：

```sh
# 零外部 API：全量测试、Mock 配对实验、客户流失兼容。
.venv/bin/python scripts/verify_phase4.py --output-dir runtime/phase4-mock-new

# 显式付费：先完成上述检查，再进行两组真实 API 对照；最多 12 次新请求。
.venv/bin/python scripts/verify_phase4.py --output-dir runtime/phase4-live-new --live-api --env-file .env
```

当前 BK08/X05 的机制及小规模对照已验收，G4 的当前范围已补齐证据；未承诺未知数据/业务迁移或普遍性能收益。当时下一阶段为 Phase 5；现已由 [独立界面与质量验收](phase5.md) 完成，完整 G1/G3/G5 和 Phase 6 交付复现仍待总审。
