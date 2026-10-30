# AlgoFactory 运行报告

- 流程：workflow:048943f906d74592ac96d80406802e7d
- 状态：failed
- 任务：regression
- 评估范围：validation_and_final_test
- LLM 模式：mock
- 代码散列：02fdc4c55d40ecb2f018daa6f152eaf7faaa4ff29acc5df329e7e394df3ff068
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
| mae | 未评估 | 未评估 | 1.000000 |
| rmse | 未评估 | 未评估 | 1.500000 |

合成回归按固定种子 60/20/20 随机划分，预处理只在训练集拟合；MAE/RMSE 越低越好，门槛预先固定。
验证通过后锁定代码与配置，独立测试只评估一次；测试失败不触发重新调参或修复。

完整输入散列、状态轨迹、Provider 调用和容器证据见同目录 JSON 文件。


## 经验复用轨迹

模型声明采用与代码规则检查分别记录；单次采用不代表普遍收益。

- 经验开关：False；匹配数：0；输出满足经验规则：False

## 设计依据与解释

任务要求预测 value，类型为 regression。方案依据适用知识选择算法实体 source:b07ff4609755bb9dc34b0e3dfd8d088c0fd579f5b4f8e0900e9f989af6a3a59f:algorithm:logistic_regression，并要求预处理只在训练集拟合。候选是否通过由独立验证器依据冻结门槛决定，不由模型自行评分。此次运行状态为 failed。

预先指定的单候选；不声称是所有算法中最优

知识引用：source:b07ff4609755bb9dc34b0e3dfd8d088c0fd579f5b4f8e0900e9f989af6a3a59f:algorithm:logistic_regression, source:b07ff4609755bb9dc34b0e3dfd8d088c0fd579f5b4f8e0900e9f989af6a3a59f:capability:regression
验证记录：source:53ae2e4792e001749c3e729f0b2f2992e29805816ba7dfe1362ccfe8a20c5611:validation
