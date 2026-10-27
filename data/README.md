# data

customer_churn.txt 是本项目编写、可随项目提交的模拟订阅业务材料，不含真实客户数据。UTF-8 原始内容的 SHA-256 用作 source_id；读取时保留原始换行，引用位置按 Unicode 字符计算。

Phase 1 提供这份业务资料和对应的固定 Mock 响应（src/algofactory/llm/fixtures/churn.json）。Mock 只匹配相同文件内容的散列；修改文档后应提供新 fixture 或显式使用 API。Mock fixture 是人工编写的测试输入，不代表真实模型调用结果。

Phase 2 的 src/algofactory/datasets.py 提供固定种子 42 的合成 CSV 生成器，默认 1,500 行，训练/验证/测试按 60/20/20 分层划分。运行 prepare-data 或首次 demo 生成 CSV、划分索引及数据指纹；评估特征和标签分文件保存，标签不挂载进执行容器。详见 docs/phase2.md。
