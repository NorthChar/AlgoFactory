# data

customer_churn.txt 是本项目编写、可随项目提交的模拟订阅业务材料，不含真实客户数据。UTF-8 原始内容的 SHA-256 用作 source_id；读取时保留原始换行，引用位置按 Unicode 字符计算。

Phase 1 提供这份业务资料和对应的固定 Mock 响应（src/algofactory/llm/fixtures/churn.json）。Mock 只匹配相同文件内容的散列；修改文档后应提供新 fixture 或显式使用 API。Mock fixture 是人工编写的测试输入，不代表真实模型调用结果。

固定种子的合成 CSV 数据生成器、训练/验证/测试划分及数据指纹在 Phase 2 实现。
