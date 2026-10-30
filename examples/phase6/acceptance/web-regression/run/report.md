# AlgoFactory 运行报告

- 流程：workflow:f681876a5d124c01875d88f5969c2c71
- 状态：validated
- 任务：regression
- 评估范围：validation_only
- LLM 模式：mock
- 代码散列：89f8e5686986c46bd0f0d329019f9829537644c0ed8e93fbfc0184d5948bfebc
- 知识库回写：已保存
- 错误类别：无

Mock 指固定方案与代码响应；模型训练、预测和评分仍由真实程序执行。

## 四维验证

| 维度 | 状态 | 说明 |
| --- | --- | --- |
| 功能 | passed | 真实 fit/predict，长度、顺序和有限数值校验通过 |
| 指标 | passed | 验证集对照预先冻结门槛 |
| 稳定性 | passed | {"seed_repeat": true, "missing_column_rejected": true, "invalid_numeric_rejected": true} |
| 接口 | passed | build_pipeline / fit / predict |

## 实际指标

| 指标 | 验证集 | 独立测试集 | 冻结门槛 |
| --- | --- | --- | --- |
| mae | 0.396443 | 未评估 | 1.000000 |
| rmse | 0.504133 | 未评估 | 1.500000 |

合成回归按固定种子 60/20/20 随机划分，预处理只在训练集拟合；MAE/RMSE 越低越好，门槛预先固定。
验证通过后锁定代码与配置，独立测试只评估一次；测试失败不触发重新调参或修复。

完整输入散列、状态轨迹、Provider 调用和容器证据见同目录 JSON 文件。

本报告仅用于验证集候选比较；validated 不表示最终测试通过。


## 经验复用轨迹

模型声明采用与代码规则检查分别记录；单次采用不代表普遍收益。

- 经验开关：False；匹配数：0；输出满足经验规则：False

## 设计依据与解释

任务要求预测 value，类型为 regression。方案依据适用知识选择算法实体 source:b07ff4609755bb9dc34b0e3dfd8d088c0fd579f5b4f8e0900e9f989af6a3a59f:algorithm:logistic_regression，并要求预处理只在训练集拟合。候选是否通过由独立验证器依据冻结门槛决定，不由模型自行评分。此次运行状态为 validated。

预先指定的单候选；不声称是所有算法中最优

知识引用：source:b07ff4609755bb9dc34b0e3dfd8d088c0fd579f5b4f8e0900e9f989af6a3a59f:algorithm:logistic_regression, source:b07ff4609755bb9dc34b0e3dfd8d088c0fd579f5b4f8e0900e9f989af6a3a59f:capability:regression
验证记录：source:0bfa6925250514013d95951afd2d713fba5ec5a6feb6882b4e8986a30b542cb4:validation
