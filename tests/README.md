# tests

使用 Python 3.11 环境运行 `.venv/bin/python -m pytest -q`。

- test_contracts.py：严格类型、字段/指标约束、四维结果、测试集显式标识、执行安全默认值。
- test_knowledge.py：原文引用、关系端点、事务回滚、重复导入、ID 冲突、持久化检索、GraphML/JSON 重载，以及历史记录与版本关联。
- test_providers.py：Mock/API 共用接口、非法响应、重试、超时、调用与费用预算、HTTP 错误脱敏和禁止重定向。
- test_cli.py：真实子进程验证命令入口、导入导出、查询、错误退出码及 Schema 导出。

HTTP 测试只在 127.0.0.1 临时启动模拟服务，使用虚构密钥，不访问外部模型 API。运行环境需要允许本地端口绑定。历史验证记录只用于契约测试，不能作为真实模型成绩。

完整 Phase 1 验证及证据导出：`.venv/bin/python scripts/verify_phase1.py --output-dir runtime/phase1`。该命令运行格式检查、静态检查、来源校验和全部测试，再生成可追溯的知识样例及报告。
