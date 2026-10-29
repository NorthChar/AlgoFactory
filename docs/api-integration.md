# Azure GPT-4o 真实 API 接入记录

2026-10-29，按照用户授权接入 Azure OpenAI 的 `gpt-4o` 部署，暂不设置金额上限，保留小规模调用次数、输出长度和请求大小限制。主案例仍为 BANKING77，Mock 阶段证据保留原样。

## 当前结果

**连接已验证，完整业务闭环尚未通过。** 真实 Responses API 已成功完成连通性检查与需求解析；知识抽取返回通过结构契约，但未通过知识图谱一致性校验，流程以 `invalid_knowledge_graph` 停止并保存失败记录。尚未生成算法代码，没有执行本次训练或访问最终测试集。具体违反哪项图谱规则尚未定位，不能把此结果写成真实 API 闭环通过。

[汇总证据](../examples/api-integration/verification.json)、[业务失败报告](../examples/api-integration/attempt-3/single-candidate/report.md)、[用量审计](../examples/api-integration/attempt-3/provider-audit.json)。

早期三次简短请求被 HTTP 400 拒绝（第一次只有通用错误分类）。后续诊断只保留预设参数词匹配，不保存原始错误正文。将 JSON 输出提示加入 `input` 后连通性通过；仅放在 `instructions` 中不足以满足此次 Azure JSON 模式校验。随后成功返回三次响应：连通性检查、需求解析、知识抽取。总计六次真实请求，无自动重试；三个拒绝请求未返回用量，不将其写作零费用。

下一步应先补充图谱校验的脱敏诊断、定位模型生成知识的不一致之处，再做有界复测。当前不开展付费多候选、自动修复和经验对照。完整 G2、Phase 4 和其他项目 Gate 不因此自动通过。

## 本地配置

真实密钥只放在被 Git 忽略的 `.env`；`.env.example` 是可提交模板，禁止填写密钥。配置文件不会自动加载，明确指定 `--env-file .env` 才读取；已有系统环境变量优先。读取器只解析字面赋值，不运行 shell、不展开 `$()` 或环境变量，不把密钥设置到进程的全局环境。

- `ALGOFACTORY_API_BASE_URL`：Azure `/openai/v1/` 根地址。
- `ALGOFACTORY_API_MODEL`：Azure **部署名称**，本次确认为 `gpt-4o`。
- `ALGOFACTORY_API_STYLE=responses`；旧 `chat_completions` 仍支持。
- `ALGOFACTORY_API_AUTH_STYLE=api_key`；旧 Bearer 认证仍支持。
- `ALGOFACTORY_API_MAX_COST_USD`：留空表示无金额限制；填写时必须同时提供输入、输出单价。
- 单价未知时两个价格字段均留空，记录为 `null`，而非免费。
- 本次 `.env`：每轮 4 次调用、重试 0 次、每次输出最多 8192 token、超时 120 秒。

```sh
# 运行前应准备 BANKING77 数据与已批准的 Docker 镜像。
# 该命令会消耗真实 API 额度；新目录用于保留每次运行的独立证据。
.venv/bin/python scripts/verify_live_api.py --env-file .env --output-dir runtime/live-api-new

# 直接进入单候选业务流程，不增加连通性请求：
.venv/bin/python -m algofactory.cli --env-file .env demo --task banking77 --mode api --db runtime/live-api.sqlite
```

验证脚本在模型调用前检查本地数据与镜像配置；共享同一个 Provider，连通性请求最多输出 256 token，随后至多 4 次业务调用，每次最多输出 8192 token，自动重试和算法修复均关闭。若设置金额预算，连通性与业务共用预留预算。一次失败即停止，脚本不会自动开始新的一轮。

Responses 使用 `store=false`，不启用远程工具；通过 JSON 模式返回，再由本地 Pydantic 与知识规则严格校验。这里不声称使用服务端严格 JSON Schema 输出。密钥只进入指定服务的认证头，不写入报告，不跟随重定向。错误日志仅保留类别、HTTP 状态和白名单服务错误码。

## 价格与用量

来源：[微软 Azure 定价页](https://azure.microsoft.com/en-us/pricing/details/azure-openai/)、[公开零售价 API](https://prices.azure.com/api/retail/prices)、[本次查询原始快照](../examples/api-integration/reference-prices.json)。查询选择 East US、Azure OpenAI、全球标准文本模型，原始单位 1K token，下表换算为每百万 token。**这不表示用户资源位于 East US，亦不确定其部署类型或合同价格。**

| GPT-4o 版本／部署 | 输入 USD / 百万 token | 输出 USD / 百万 token |
| --- | ---: | ---: |
| 2024-08-06 Global Standard | 2.50 | 10.00 |
| 2024-11-20 Global Standard | 2.50 | 10.00 |
| 2024-05-13 Global Standard | 5.00 | 15.00 |

已返回用量：输入 **7,339 token**、输出 **3,004 token**。按前两版本参考价计算为 **0.0483875 USD**，按旧版本为 **0.081755 USD**。这仅是已知用量的情景估算，不是实际账单，也不是包含所有部署方式的费用区间。配置中未把参考价当成用户真实价格。最终以 Azure 计费记录为准。

`provider-audit.json` 保存各次请求的服务返回用量；缺失值保留 null。`provider-usage.json` 汇总已知用量和缺失次数。若提供价格，可显示已知用量估算和保守预留；不把估算标成实付。预留按输入字节上界与最大输出计价，失败不返还预留。

## 接口依据与验证边界

- [微软 Responses 指南](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses)
- [微软 Responses REST 参考](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/responses)
- [Azure v1 API 与部署名称](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle?tabs=key)

本地测试覆盖 Responses 请求与解析、拒绝/截断/非法响应、HTTP 脱敏、不设金额限制时的调用及输入大小限制、未知用量与未知价格、配置优先级与无 shell 执行、连通性和业务共享预算。历史 Mock 与 Docker 测试仍须通过；测试传输模拟不冒充真实模型成功。

最终回归：**155 项通过，0 失败、0 错误、0 跳过**（含真实 Docker），见 [测试记录](../examples/api-integration/tests.xml)。静态检查和格式检查通过。测试源码指纹及证据文件散列见汇总记录。
