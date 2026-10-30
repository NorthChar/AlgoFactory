# tests

使用 Python 3.11 环境运行 `.venv/bin/python -m pytest -q`。

- test_contracts.py：严格类型、字段/指标约束、四维结果、测试集显式标识、执行安全默认值。
- test_knowledge.py：原文引用、关系端点、事务回滚、重复导入、ID 冲突、持久化检索、GraphML/JSON 重载，以及历史记录与版本关联。
- test_providers.py：Mock/API 共用接口、非法响应、重试、超时、调用与费用预算、HTTP 错误脱敏和禁止重定向。
- test_cli.py：真实子进程验证命令入口、导入导出、查询、错误退出码及 Schema 导出。

HTTP 测试只在 127.0.0.1 临时启动模拟服务，使用虚构密钥，不访问外部模型 API。运行环境需要允许本地端口绑定。历史验证记录只用于契约测试，不能作为真实模型成绩。

完整 Phase 1 验证及证据导出：`.venv/bin/python scripts/verify_phase1.py --output-dir runtime/phase1`。该命令运行格式检查、静态检查、来源校验和 Phase 1 四个测试文件，再生成可追溯的知识样例及报告。


Phase 2 的 test_phase2.py 覆盖数据/协议完整性、安全语法、独立评分、事务迁移及回写失败。超时、OOM、清理失败以模拟 Docker 响应验证错误路径。真实容器用例需先运行 scripts/prepare_sandbox.py，再设置 ALGOFACTORY_DOCKER_TESTS=1；覆盖 Mock 正常重复、接口故障及模拟 API 传输适配。API 适配用例仍不调用真实 LLM。

完整 Phase 2 验证：`.venv/bin/python scripts/verify_phase2.py --output-dir runtime/phase2-verification`。脚本明确启用容器测试，任何跳过或失败都不签署通过，随后运行正常/重复/三类故障 CLI 演示并校验数据库重开和图谱重载。


Phase 5 测试需要 web extra（`uv sync --extra web --locked` 或带散列安装 `requirements-dev.txt`）。`tests/test_web.py` 使用 Streamlit AppTest，普通单元测试不启动付费模型；`scripts/verify_phase5.py` 的页面验收实际启动 Mock 后台进程和 Docker，检查提交、刷新、恢复、下载入口、真实超时和三任务兼容。

Phase 7：`test_data_view.py` 验证只读数据与压缩历史预测；`test_model_trials.py` 验证模型来源、输入和测试集守卫及失败停止；`test_experiments.py` 验证配置贯穿生成、参数检查、CLI 和页面。使用 `python -m pytest` 保证项目 scripts 可导入。实际容器保存、重复预测、历史显式准备和真实表单提交由 `scripts/verify_phase7.py` 复现；不会调用付费 API。
