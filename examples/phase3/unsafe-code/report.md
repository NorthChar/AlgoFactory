# AlgoFactory 运行报告

- 流程：search:cc4e8605930446b7a6f3706248f03ebe
- 状态：failed
- 任务：banking77
- 评估范围：comparison_and_final_test
- LLM 模式：mock
- 代码散列：尚未生成
- 知识库回写：已保存
- 错误类别：unapproved_import

Mock 指固定方案与代码响应；模型训练、预测和评分仍由真实程序执行。

## 四维验证

| 维度 | 状态 | 说明 |
| --- | --- | --- |
| 功能 | not_run | 尚未执行 |
| 指标 | not_run | 尚未执行 |
| 稳定性 | not_run | 尚未执行 |
| 接口 | not_run | 尚未执行 |

## 实际指标

| 指标 | 验证集 | 独立测试集 | 冻结门槛 |
| --- | --- | --- | --- |
| macro_f1 | 未评估 | 未评估 | 0.820000 |
| accuracy | 未评估 | 未评估 | 未评估 |

BANKING77 保留官方测试集；训练侧去重后按 80/20 分层划分训练/验证。词表和 IDF 仅在训练集拟合；Macro-F1 为门槛，Accuracy 仅报告。逐类指标及混淆矩阵见 validation-class-details.json / test-class-details.json。
验证通过后锁定代码与配置，独立测试只评估一次；测试失败不触发重新调参或修复。

完整输入散列、状态轨迹、Provider 调用和容器证据见同目录 JSON 文件。

## 候选与版本

| 候选 | 版本 | 状态 | Macro-F1（验证） | 错误 |
| --- | --- | --- | --- | --- |
| text_logistic | 0 | failed | 未完成 | unapproved_import |

排名只使用验证集 Macro-F1，其次 Accuracy，再按冻结候选顺序打破平局。只有通过四维检查的版本可入选。
选定候选：无
故障 fixture：unsafe_code
修复输入、父版本、修改代码和重新验证结果见 candidates/；统一决策见 decisions.json，排名见 ranking.json（若比较完成）。
