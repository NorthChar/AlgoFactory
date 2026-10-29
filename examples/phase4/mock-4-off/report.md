# AlgoFactory 运行报告

- 流程：search:33a83401c1a444f0aa65cc5097593c9e
- 状态：validated
- 任务：banking77
- 评估范围：comparison_validation_only
- LLM 模式：mock
- 代码散列：01e8520b0eddcc619e744203c0f7a8dd55a516457d6cf50eba0b8577ec1ce6de
- 知识库回写：已保存
- 错误类别：无

Mock 指固定方案与代码响应；模型训练、预测和评分仍由真实程序执行。

## 四维验证

| 维度 | 状态 | 说明 |
| --- | --- | --- |
| 功能 | passed | 真实 fit/predict，长度、顺序和有限数值校验通过 |
| 指标 | passed | 验证集对照预先冻结门槛 |
| 稳定性 | passed | {"seed_repeat": true, "missing_column_rejected": true, "invalid_text_rejected": true, "unseen_text_handled": true} |
| 接口 | passed | build_pipeline / fit / predict / predict_proba |

## 实际指标

| 指标 | 验证集 | 独立测试集 | 冻结门槛 |
| --- | --- | --- | --- |
| macro_f1 | 0.872975 | 未评估 | 0.820000 |
| accuracy | 0.873437 | 未评估 | 未评估 |

BANKING77 保留官方测试集；训练侧去重后按 80/20 分层划分训练/验证。词表和 IDF 仅在训练集拟合；Macro-F1 为门槛，Accuracy 仅报告。逐类指标及混淆矩阵见 validation-class-details.json / test-class-details.json。
验证通过后锁定代码与配置，独立测试只评估一次；测试失败不触发重新调参或修复。

完整输入散列、状态轨迹、Provider 调用和容器证据见同目录 JSON 文件。

本报告仅用于验证集候选比较；validated 不表示最终测试通过。

## 候选与版本

| 候选 | 版本 | 状态 | Macro-F1（验证） | 错误 |
| --- | --- | --- | --- | --- |
| text_logistic | 0 | failed | 未完成 | worker_ValueError |
| text_logistic | 1 | validated | 0.872975 | 无 |

排名只使用验证集 Macro-F1，其次 Accuracy，再按冻结候选顺序打破平局。只有通过四维检查的版本可入选。
选定候选：text_logistic
故障 fixture：text_adapter
修复输入、父版本、修改代码和重新验证结果见 candidates/；统一决策见 decisions.json，排名见 ranking.json（若比较完成）。


## 经验复用轨迹

模型声明采用与代码规则检查分别记录；单次采用不代表普遍收益。

- 经验开关：False；匹配数：0；输出满足经验规则：False
- 经验开关：False；匹配数：0；输出满足经验规则：False