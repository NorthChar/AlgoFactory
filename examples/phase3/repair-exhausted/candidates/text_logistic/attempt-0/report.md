# AlgoFactory 运行报告

- 流程：workflow:da0a02317ea1475ebaced96aa222d4d2
- 状态：failed
- 任务：banking77
- 评估范围：validation_only
- LLM 模式：mock
- 代码散列：0d9f08d7a0fbbae4940581b85c671ce5daf14e3f612b3101bcc239e0e7447472
- 知识库回写：已保存
- 错误类别：interface_missing_predict_proba

Mock 指固定方案与代码响应；模型训练、预测和评分仍由真实程序执行。

## 四维验证

| 维度 | 状态 | 说明 |
| --- | --- | --- |
| 功能 | not_run | 尚未执行 |
| 指标 | not_run | 尚未执行 |
| 稳定性 | not_run | 尚未执行 |
| 接口 | failed | interface_missing_predict_proba |

## 实际指标

| 指标 | 验证集 | 独立测试集 | 冻结门槛 |
| --- | --- | --- | --- |
| macro_f1 | 未评估 | 未评估 | 0.820000 |
| accuracy | 未评估 | 未评估 | 未评估 |

BANKING77 保留官方测试集；训练侧去重后按 80/20 分层划分训练/验证。词表和 IDF 仅在训练集拟合；Macro-F1 为门槛，Accuracy 仅报告。逐类指标及混淆矩阵见 validation-class-details.json / test-class-details.json。
验证通过后锁定代码与配置，独立测试只评估一次；测试失败不触发重新调参或修复。

完整输入散列、状态轨迹、Provider 调用和容器证据见同目录 JSON 文件。

本报告仅用于验证集候选比较；validated 不表示最终测试通过。
