# 可选的真实 LLM 接入

无需密钥即可运行离线需求检查和 Mock 代码生成；Docker 中的训练、评分及试用仍真实执行。自然语言理解和 API 代码生成会产生费用，各自的调用预算在页面展示。

## 本地配置

仅在没有 `.env` 时从 `.env.example` 复制一份，填写自己的服务配置。真实密钥只放在被 Git 忽略的 `.env`，不要填入模板或提交仓库。

- `ALGOFACTORY_API_BASE_URL`：服务根地址，Azure 使用资源的 `/openai/v1/` 地址。
- `ALGOFACTORY_API_MODEL`：服务部署名称，可能不同于模型名称。
- Azure 使用 `ALGOFACTORY_API_STYLE=responses` 和 `ALGOFACTORY_API_AUTH_STYLE=api_key`；也支持兼容的 chat_completions / Bearer 模式。
- 金额上限和输入/输出单价按模板填写；未知单价留空会记录为未知，不能解释为免费。实际账单以服务商为准。

CLI 显式传入 `--env-file .env`；工作台使用本地配置，页面不收集密钥。环境变量优先于文件值。解析器不执行 shell 或变量展开。请求不跟随重定向，错误日志仅保留有限类别和状态码。

## 调用与停止

需求理解每轮最多两次调用、最多三轮；同轮重复操作读取已有结果，不自动重试。代码生成具有独立请求上限；有限修复也消耗该预算。预算耗尽明确停止，查看诊断后由使用者决定是否创建新任务。

API 返回内容经过本地 Pydantic、引用、方案及代码检查；不能因模型声称成功而跳过验证。Responses 使用 store=false 和 JSON 输出，不宣称服务端严格 JSON Schema 保证。失败不静默降级为 Mock。

## 可检查的证据与入口

- [完整真实 API 修复、比较及最终测试](../examples/banking-classification/comparison/report.md)。
- [新增需求理解与单个意图生成节选](../examples/intent-goals/README.md)。
- `scripts/verify_live_api.py`：需显式密钥文件的最小连接和单候选检查；不包含自动修复，最多五次请求。
- `scripts/verify_live_search.py`：有界真实候选比较；运行前阅读 --help 并明确预算。

日常体验优先使用工作台确认流程；自动复现脚本默认不调用付费 API。旧接入诊断保存在 Git 历史，不能把旧提示错误或旧调用上限当作当前操作配置。
