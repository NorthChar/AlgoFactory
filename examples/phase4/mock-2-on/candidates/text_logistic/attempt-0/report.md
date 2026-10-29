# AlgoFactory 运行报告

- 流程：workflow:d258c50dea324a0987b2f8b7a9e62e2d
- 状态：failed
- 任务：banking77
- 评估范围：validation_only
- LLM 模式：mock
- 代码散列：48ce0fbf6d9a651fc6ba087c25ce577b77e0e7511fc84497fb118b222421bd3e
- 知识库回写：已保存
- 错误类别：worker_ValueError

Mock 指固定方案与代码响应；模型训练、预测和评分仍由真实程序执行。

## 四维验证

| 维度 | 状态 | 说明 |
| --- | --- | --- |
| 功能 | failed | worker_ValueError |
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

本报告仅用于验证集候选比较；validated 不表示最终测试通过。


## 经验复用轨迹

模型声明采用与代码规则检查分别记录；单次采用不代表普遍收益。

- 经验开关：True；匹配数：1；输出满足经验规则：False
- source:b76667cea3ed76845a4b7234d07fc8517bd657e22d1b65d215e15eee9153f963:experience：adopted；显式 Mock：输出固定的、符合文本适配经验的模板；不代表模型推理或收益。