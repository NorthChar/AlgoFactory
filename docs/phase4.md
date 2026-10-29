# Phase 4：已验证经验提炼与复用

状态：**planned，进入条件已满足，开始实施准备；经验复用功能与对照实验尚未实现。** 2026-10-29，Phase 3 已通过 Mock 与真实 Azure API 补验收，见 [最终严格证据](../examples/api-phase3/verification.json) 和 [完整调用/失败总账](../examples/api-phase3/campaign-summary.json)。本文件承接总体计划，原始 docs/source 不变。

## 输入与第一项工作

第一项工作是从已通过的真实修复链提炼一条有证据的文本输入接口经验：原始代码直接把 DataFrame 交给 TF-IDF，真实执行失败；GPT-4o 补上 ColumnTransformer 和标量文本列选择器后通过验证。输入包括失败/修复代码散列、父子实现 ID、失败类别、验证运行 ID 与冻结协议。只使用验证阶段证据，不把最终测试分数作为生成或检索条件。

首批证据来自 [修复前](../examples/api-phase3/comparison/candidates/text_logistic/attempt-0/report.json)、[修复输入](../examples/api-phase3/comparison/candidates/text_logistic/attempt-1/repair-input.json) 和 [修复后](../examples/api-phase3/comparison/candidates/text_logistic/attempt-1/report.json)。先前人工单点诊断和存在参数偏差的首轮不作为本阶段的已验证经验来源。

## 实施顺序与验收

| 顺序 | 工作 | 必需产物/判断 |
| --- | --- | --- |
| 4.1 经验提炼 | 从失败→修改→真实验证通过链构造 Experience；区分 proposed/verified | 引用失败与重测、代码变化、适用条件和已测结果；缺少成功重测不得 verified；幂等回写 |
| 4.2 条件检索 | 按任务类型、文本输入接口、算法及失败类型过滤经验 | 返回经验 ID、来源、匹配理由；未知/不兼容条件拒绝，不直接用于客户流失 |
| 4.3 流程消费 | 将匹配经验作为生成/修复的显式参考，提供开关 | 保存实际检索 ID、传入位置与采用/不采用理由；沿用同一安全、参数检查和评分流程 |
| 4.4 对照验证 | 相同任务、数据、初始故障、模型参数、种子和预算下开关对照 | 先固定 Mock 对照，再小规模 API 重复实验；记录成功率、修复次数和 token 成本，保留无提升/负结果 |

现有 ExperienceRecord 和 ExperienceEntity 仅提供基础契约；存在类定义或历史 ValidationRun 不代表已经实现经验提炼与消费。扩展适用条件时保持旧图谱可读、来源完整和关系端点约束。首轮只覆盖 BANKING77 文本分类，不扩充客户流失业务或提前实现 UI。

## 对照边界

- 经验来源与后续测试任务分开记录，避免只在同一运行中把已有答案伪装成复用收益。
- 两组只切换经验开关；不能同时修改提示主干、错误难度、调用/修复预算或评价门槛来制造提升。
- Mock 只验证可控流程，真实 API 的波动单独记录；一次运行不支持普遍效果结论。
- 新的经验应用仍须真实 Docker 重测，不能因引用 verified 经验就跳过验证；测试集不参与经验选择或修复。
- 本轮 Phase 3 已用完明确的 20 次请求预算，已停止付费调用。Phase 4 先做实现与离线/Mock 检查，新的真实对照运行须事先固定小规模调用预算。

本阶段通过后更新 BK08/X05 和 G4 的相应证据，再进入 Phase 5 界面与插件。当前不将这些条目标为 implemented 或 verified。
