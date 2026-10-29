# AlgoFactory 运行报告

- 流程：workflow:a71f69db332f44dfbbb4d4cc1ab5985a
- 状态：accepted
- 任务：banking77
- LLM 模式：mock
- 代码散列：01e8520b0eddcc619e744203c0f7a8dd55a516457d6cf50eba0b8577ec1ce6de
- 知识库回写：已保存
- 错误类别：无

Mock 指固定方案与代码响应；模型训练、预测和评分仍由真实程序执行。

## 四维验证

| 维度 | 状态 | 说明 |
| --- | --- | --- |
| 功能 | passed | 真实 fit/predict，长度、顺序和有限数值校验通过 |
| 指标 | passed | 验证集及一次性独立测试均达到冻结门槛 |
| 稳定性 | passed | {"seed_repeat": true, "missing_column_rejected": true, "invalid_text_rejected": true, "unseen_text_handled": true} |
| 接口 | passed | build_pipeline / fit / predict / predict_proba |

## 实际指标

| 指标 | 验证集 | 独立测试集 | 冻结门槛 |
| --- | --- | --- | --- |
| macro_f1 | 0.872975 | 0.878695 | 0.820000 |
| accuracy | 0.873437 | 0.878247 | 未评估 |

BANKING77 保留官方测试集；训练侧去重后按 80/20 分层划分训练/验证。词表和 IDF 仅在训练集拟合；Macro-F1 为门槛，Accuracy 仅报告。逐类指标及混淆矩阵见 validation-class-details.json / test-class-details.json。
验证通过后锁定代码与配置，独立测试只评估一次；测试失败不触发重新调参或修复。

完整输入散列、状态轨迹、Provider 调用和容器证据见同目录 JSON 文件。
