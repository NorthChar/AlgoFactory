# Azure GPT-4o 真实 API 接入记录

2026-10-29，按照用户授权接入 Azure OpenAI 的 `gpt-4o` 部署，暂不设置金额上限，保留小规模调用次数、输出长度和请求大小限制。主案例仍为 BANKING77，Mock 阶段证据保留原样。

## 当前结果

**连接及知识层已通过单次真实复测，完整业务闭环尚未通过。** 初次流程在知识图谱一致性校验处停止；本次收窄文档抽取契约后，真实知识抽取、图谱校验、入库与检索均通过，随后在规划约束检查处以 `unsupported_phase2_plan` 停止。尚未生成算法代码、执行训练或访问最终测试集。原始运行与本次修复证据分别保留，不覆盖历史失败。

[汇总证据](../examples/api-integration/verification.json)、[业务失败报告](../examples/api-integration/attempt-3/single-candidate/report.md)、[用量审计](../examples/api-integration/attempt-3/provider-audit.json)。

早期三次简短请求被 HTTP 400 拒绝（第一次只有通用错误分类）。后续诊断只保留预设参数词匹配，不保存原始错误正文。将 JSON 输出提示加入 `input` 后连通性通过；仅放在 `instructions` 中不足以满足此次 Azure JSON 模式校验。随后成功返回三次响应：连通性检查、需求解析、知识抽取。总计六次真实请求，无自动重试；三个拒绝请求未返回用量，不将其写作零费用。

下一步应定位算法规划与候选约束不一致的问题；本次计划在小规模知识复测后停止付费调用。当前不开展付费多候选、自动修复和经验对照。完整 G2、Phase 4 和其他项目 Gate 不因此自动通过。

## 知识校验修复与复测（2026-10-29）

[本次汇总](../examples/api-knowledge-fix/verification.json)、[诊断结果](../examples/api-knowledge-fix/diagnosis/diagnosis.json)、[离线重放](../examples/api-knowledge-fix/offline-replay/diagnosis.json)、[复测报告](../examples/api-knowledge-fix/retest/single-candidate/report.md)。

旧运行未保存模型抽取结果，无法断言当时具体哪条关系出错。本次使用旧抽取提示与输出契约重新发出一次请求，复现相同错误类别，并保存了可离线重放的结构化抽取结果。诊断定位到第 4 条关系（索引 3）：`Algorithm DEPENDS_ON Dependency`。模型把 TF-IDF + Logistic Regression 与 scikit-learn 相连，但项目的 DEPENDS_ON 约束只允许 `Implementation -> Dependency`。严格校验正确拒绝该关系。

根因是输出契约与抽取阶段职责不一致：提示只允许文档知识，给模型的完整 Extraction Schema 却包含全部运行历史实体和关系，包括 DEPENDS_ON。修复增加 DocumentExtraction，仅包含 Task、Capability、Algorithm、Dependency 四类实体与 REQUIRES、IMPLEMENTS、APPLICABLE_TO 三类关系；依赖库保留为独立实体，具体实现生成后再由可信回写建立依赖关系。未删除模型错误关系来伪装通过，未放宽全图校验。

诊断改为安全的规则码与对象位置，例如 `knowledge_endpoint_type / relation / 3`；不附带引用正文、模型生成的 ID 或原始校验错误全文。工作流 JSON、Markdown 和失败入库记录保留诊断。新增显式诊断脚本可保留抽取结果（仅诊断时启用，并阻止保存包含当前凭据的响应）；后续可零调用重放。

```sh
# 零 API 调用：预期失败退出，并准确指出历史诊断样本中的非法关系。
.venv/bin/python scripts/diagnose_knowledge.py --response-file examples/api-knowledge-fix/diagnosis/extraction.json --output-dir runtime/knowledge-offline-replay

# 一次付费抽取诊断，无重试；只在需要新诊断时执行。
.venv/bin/python scripts/diagnose_knowledge.py --env-file .env --output-dir runtime/knowledge-diagnosis-new

# 省略已通过的连通性检查，单候选最多 4 次调用。
.venv/bin/python scripts/verify_live_api.py --env-file .env --skip-smoke --output-dir runtime/knowledge-retest-new
```

本次复测实际进行 3 次调用：需求解析、知识抽取、规划。前两阶段成功，抽取内容已通过全部图谱校验并可重新打开数据库检索；第三阶段在规划结果与候选限制一致性检查中失败，错误为 `unsupported_phase2_plan`。这是一项新的阻塞，具体违反哪个规划子条件尚未定位；不能称整个 API 流程通过。

本轮累计 **4 次请求，0 次自动重试**（定位 1 次、复测 3 次）；输入 **12,381 token**、输出 **5,906 token**。按下文已有公开价格快照计算，本轮费用情景估算为 **0.0900125 USD** 或 **0.150495 USD**，不代表实际账单。知识层已完成这次小规模复测，不继续付费重复运行。

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

初次接入轮次已返回用量（不含上述修复复测）：输入 **7,339 token**、输出 **3,004 token**。按前两版本参考价计算为 **0.0483875 USD**，按旧版本为 **0.081755 USD**。这仅是已知用量的情景估算，不是实际账单，也不是包含所有部署方式的费用区间。配置中未把参考价当成用户真实价格。最终以 Azure 计费记录为准。

`provider-audit.json` 保存各次请求的服务返回用量；缺失值保留 null。`provider-usage.json` 汇总已知用量和缺失次数。若提供价格，可显示已知用量估算和保守预留；不把估算标成实付。预留按输入字节上界与最大输出计价，失败不返还预留。

## 接口依据与验证边界

- [微软 Responses 指南](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses)
- [微软 Responses REST 参考](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/responses)
- [Azure v1 API 与部署名称](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle?tabs=key)

本地测试覆盖 Responses 请求与解析、拒绝/截断/非法响应、HTTP 脱敏、不设金额限制时的调用及输入大小限制、未知用量与未知价格、配置优先级与无 shell 执行、连通性和业务共享预算。历史 Mock 与 Docker 测试仍须通过；测试传输模拟不冒充真实模型成功。

初次接入回归：**155 项通过，0 失败、0 错误、0 跳过**（含真实 Docker），见 [测试记录](../examples/api-integration/tests.xml)。静态检查和格式检查通过。测试源码指纹及证据文件散列见汇总记录。

知识层修复回归：**163 项通过，0 失败、0 错误、0 跳过**（含真实 Docker），见 [本轮测试记录](../examples/api-knowledge-fix/tests.xml)。重开数据库验证得到 1 个来源、4 个实体、3 条合法关系和 1 条算法检索结果。旧非法关系样本作为离线回归用例保留。
