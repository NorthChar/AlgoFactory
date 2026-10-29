# AlgoFactory 运行报告

- 流程：workflow:84afd242f75e41c39eb4163f7749ac2a
- 状态：accepted
- 任务：churn
- 评估范围：validation_and_final_test
- LLM 模式：mock
- 代码散列：55e841b65763c76114bafc9c69b302bbe4d407f4030b10214407a283078bdd3f
- 知识库回写：已保存
- 错误类别：无

Mock 指固定方案与代码响应；模型训练、预测和评分仍由真实程序执行。

## 四维验证

| 维度 | 状态 | 说明 |
| --- | --- | --- |
| 功能 | passed | 真实 fit/predict，长度、顺序和有限数值校验通过 |
| 指标 | passed | 验证集及一次性独立测试均达到冻结门槛 |
| 稳定性 | passed | {"seed_repeat": true, "missing_column_rejected": true, "invalid_numeric_rejected": true, "unseen_category_handled": true} |
| 接口 | passed | build_pipeline / fit / predict / predict_proba |

## 实际指标

| 指标 | 验证集 | 独立测试集 | 冻结门槛 |
| --- | --- | --- | --- |
| f1 | 0.645740 | 0.666667 | 0.590000 |
| roc_auc | 0.800455 | 0.816260 | 0.750000 |
| precision | 0.692308 | 0.760870 | 0.640000 |
| recall | 0.605042 | 0.593220 | 0.550000 |

训练/验证/测试按 60/20/20 分层划分；预处理只在训练数据拟合。门槛在独立测试之前冻结。
验证通过后锁定代码与配置，独立测试只评估一次；测试失败不触发重新调参或修复。

完整输入散列、状态轨迹、Provider 调用和容器证据见同目录 JSON 文件。


## 经验复用轨迹

模型声明采用与代码规则检查分别记录；单次采用不代表普遍收益。

- 经验开关：False；匹配数：0；输出满足经验规则：False

## 设计依据与解释

任务要求预测 churn，类型为 binary_classification。方案依据适用知识选择算法实体 source:ae8aa246325a083652ad97b25b61c4797ec4e5d66e7e1393c17e68a3ef63136a:algorithm:logistic_regression，并要求预处理只在训练集拟合。候选是否通过由独立验证器依据冻结门槛决定，不由模型自行评分。此次运行状态为 accepted。

预先指定的单候选；不声称是所有算法中最优

知识引用：source:ae8aa246325a083652ad97b25b61c4797ec4e5d66e7e1393c17e68a3ef63136a:algorithm:logistic_regression, source:ae8aa246325a083652ad97b25b61c4797ec4e5d66e7e1393c17e68a3ef63136a:capability:churn
验证记录：source:9f4f44e878b36f0a4643fe0b5f48ae5a65140709f3e8aa53ab847dada24aaa9d:validation
