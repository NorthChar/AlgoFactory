# 测试与复验

先按 README 安装 Python 3.11 依赖和 web extra，导入 BANKING77，准备 Docker 镜像，再运行：

```sh
ALGOFACTORY_DOCKER_TESTS=1 .venv/bin/python -m pytest -q
```

完整验收要求零失败、零错误、零跳过。未启用 Docker 的普通测试会跳过真实容器用例。HTTP 测试只在 127.0.0.1 临时启动模拟服务，不调用外部模型；环境需允许本地端口和 Docker。

- contracts / knowledge / providers：契约、来源、知识存储、检索、图重载、API 预算与错误边界。
- phase2 / phase25 / phase3 / phase5：共享执行、文本与表格任务、有限修复比较、插件与合成回归。文件名保留既有历史编号，不是测试执行顺序。
- requirements / requirement_understanding / intent_goals：需求解析、语义复核与澄清、确认绑定、目标数据和评估协议。
- web / web_workflow / data_view / model_trials：页面、只读证据、任务版本和隔离模型试用。
- delivery：凭据检测及可达 Git 历史扫描的边界。

tests/fixtures 保存离线重放所需的原始错误和基线；来源及散列列于 examples/provenance.json，不重新调用真实 API。部分超时、OOM、清理异常使用模拟响应检查，不宣称真实资源压测。

后台工作台任务与模型试用：`python scripts/verify_intent_goals.py --output-dir runtime/goals-new`。
需求配置与故障修复：`python scripts/verify_requirements.py --output-dir runtime/requirements-new`。
独立克隆与新环境：见 [交付复现](../docs/delivery.md)。这些脚本默认不调用付费 API，不执行最终测试。
