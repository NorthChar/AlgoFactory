# AlgoFactory 运行报告

- 流程：workflow:2ba8a252a4b343c9a41b7f4d0583965f
- 状态：validated
- 任务：banking77
- 评估范围：validation_only
- LLM 模式：mock
- 代码散列：f2019deef87f93b84159808e3d83a2b7e1a1a1c8161c81adc94377d4e4e75178
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
| macro_f1 | 0.826924 | 未评估 | 0.820000 |
| accuracy | 0.835918 | 未评估 | 未评估 |

BANKING77 保留官方测试集；训练侧去重后按 80/20 分层划分训练/验证。词表和 IDF 仅在训练集拟合；Macro-F1 为门槛，Accuracy 仅报告。逐类指标及混淆矩阵见 validation-class-details.json / test-class-details.json。
验证通过后锁定代码与配置，独立测试只评估一次；测试失败不触发重新调参或修复。

完整输入散列、状态轨迹、Provider 调用和容器证据见同目录 JSON 文件。

本报告仅用于验证集候选比较；validated 不表示最终测试通过。


## 经验复用轨迹

模型声明采用与代码规则检查分别记录；单次采用不代表普遍收益。

- 经验开关：False；匹配数：0；输出满足经验规则：False

## 设计依据与解释

任务要求预测 intent，类型为 multiclass_classification。方案依据适用知识选择算法实体 source:60afe9a659918ddfb1b5faecb7ed146c9c52d0e9b7ab18f808dd84424dc977b1:algorithm:text_nb，并要求预处理只在训练集拟合。候选是否通过由独立验证器依据冻结门槛决定，不由模型自行评分。此次运行状态为 validated。

预先指定的单候选；不声称是所有算法中最优

知识引用：source:60afe9a659918ddfb1b5faecb7ed146c9c52d0e9b7ab18f808dd84424dc977b1:algorithm:text_nb, source:60afe9a659918ddfb1b5faecb7ed146c9c52d0e9b7ab18f808dd84424dc977b1:capability:intent
验证记录：source:ecac8dc60c22b609d7a7ab02ed13285c73acb1614fc5ae9298da4e9e56fb22df:validation
