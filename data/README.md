# 数据与能力材料

`banking77/raw/` 是固定上游版本的 BANKING77 原始数据及许可：10,003 条训练咨询、3,080 条测试咨询、77 类英文意图。来源 PolyAI，作者 Iñigo Casanueva、Tadas Temcinas、Daniela Gerz、Matthew Henderson、Ivan Vulić（2020）；上游提交 `57ec275d8078af65b7731c2a98be812d844a6d6b`，许可 [CC BY 4.0](banking77/raw/LICENSE)。见 [官方仓库](https://github.com/PolyAI-LDN/task-specific-datasets)。

按 README 运行 prepare-banking77，将数据导入 runtime/banking77-data；导入器校验原始散列，移除训练侧重复及与测试重合项，形成 7,993 训练、1,999 验证及 3,080 最终测试记录。训练用于拟合分类器，验证用于比较和修复，测试用于冻结版本的最终评价。派生任务在原划分内筛选或重映射。

本目录的 `.txt` 是算法能力材料，供抽取与检索使用，不是咨询训练数据。知识材料与 Mock fixture 通过内容散列绑定。customer_churn.txt 为合成订阅业务说明，回归材料也用于兼容检查，不含真实客户数据。修改知识材料需要更新对应 Mock fixture，或显式使用 API。
