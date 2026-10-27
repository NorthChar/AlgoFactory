# Phase 1：知识基础层

本阶段完成数据契约、知识存储、文档抽取、检索、图谱导出和 Provider 接口。验收依据是文档到可追溯知识的真实程序运行，以及 Mock/API 共享契约测试。固定 Mock 响应的内容由人工编写，不能作为真实 LLM 抽取质量或模型性能证据。

## 已实现接口

| 模块 | 入口 | 约束 |
| --- | --- | --- |
| schemas/contracts.py | TaskSpec、AlgorithmPlan、Candidate、ValidationResult、AgentDecision、ExperienceRecord | schema_version=1、严格类型、拒绝额外字段和非有限数值 |
| schemas/knowledge.py | SourceDocument、KnowledgeBatch、Extraction | 九类实体、九种关系标签、十种端点组合、原文位置与外键校验 |
| llm/providers.py | Provider.complete(request, response_model) | Mock/API 共同响应校验、有限重试、显式失败和脱敏轨迹 |
| knowledge/extraction.py | extract_document / ingest_document | 仅抽取 Task/Capability/Algorithm/Dependency，禁止文档生成历史验证或经验 |
| knowledge/store.py | put_batch / search / evidence / export_json | SQLite 事务、不可变 ID、重复导入幂等、全部写入前重新校验 |
| knowledge/graph.py | to_networkx / export_graphml / load_graphml | MultiDiGraph 派生视图；GraphML 携带完整来源及实体/关系 JSON |

SQLite 使用 sources、entities、relations、allowed_edges 四张表。entities/relations 的类型化内容保存在 JSON payload 中，索引覆盖实体类型、来源和关系两端。外键和 SQL trigger 补充关系端点检查；跨字段一致性由 Pydantic 校验。PRAGMA user_version=1，拒绝未知版本，后续版本须显式迁移。

ID 格式为 `source:<原文 UTF-8 SHA-256>:<局部名称>`。源文档 ID 只由内容决定；同一来源的标题和实体内容视为不可变元数据。同 ID 的不同内容会冲突报错，不静默覆盖。跨文档的同名算法保留不同来源实体；合并同义实体留待后续明确策略。

每条知识的 source_span 保存 start、end、quote，按 Python Unicode 字符计数、左闭右开。字符位置及引用必须与归档原文逐字一致。API 输入额外提供预计算的原文行位置，避免模型自行计算长文本位置。引用一致性证明来源位置，不能自动证明自然语言推论在语义上正确。

历史类实体已定义契约供后续可信验证器使用：验证结果要匹配实现代码散列和划分；版本父链不能成环；verified 经验必须通过 DERIVED_FROM 关联 passed 重测记录。Phase 1 文档抽取和 CLI 导入禁止写入历史类实体。测试中的历史记录均是标注的合成 fixture。

## 本地演示

在项目根目录安装：`uv sync --frozen --python 3.11`。项目内设置了 Python 3.11.16；本阶段验证平台为 macOS ARM64。其他 Python 版本的锁文件解析不代表已完成平台验证。

```sh
.venv/bin/python -m algofactory.cli ingest data/customer_churn.txt --mode mock --db runtime/demo.sqlite
.venv/bin/python -m algofactory.cli search --db runtime/demo.sqlite --entity-type Algorithm --task-type binary_classification
.venv/bin/python -m algofactory.cli search --db runtime/demo.sqlite --text "Logistic Regression"
.venv/bin/python -m algofactory.cli export --db runtime/demo.sqlite --output-dir runtime/export
.venv/bin/python -m algofactory.cli import runtime/export/knowledge.json --db runtime/restored.sqlite
.venv/bin/python -m algofactory.cli schemas --output-dir runtime/schemas
```

`show <返回的知识 ID> --db runtime/demo.sqlite` 可查看单条证据。检索按任务类型和实体类型过滤，text 使用大小写不敏感的全部词项子串匹配，按稳定 ID 排序；不提供向量相似检索或自动语义排序。结果带实体、来源片段与相邻关系证据。当前任务类型过滤适用于 Task、Capability 和 Algorithm；其他类型可直接按 type/text/id 查询。

默认 Mock fixture 位于 src/algofactory/llm/fixtures/churn.json，打包时随 Python 包一起安装。`--fixture path.json` 可提供自定义 fixture，格式为 `{ "<文档散列>": { "description": "...", "faults": [], "response": <Extraction 对象> } }`。faults 可填 invalid_json、timeout、rate_limited、authentication_failed，依次注入后返回固定响应；未知文档散列报 mock_fixture_missing。更改文档后不会错误复用旧响应。

命令成功输出 JSON 到标准输出，失败输出 `{status: failed, error: ...}` 到标准错误，退出码为 1。原始 API 错误正文、密钥和输入全文不写入审计记录。命令输出可由调用方保存，CLI 默认不创建包含敏感请求的全量日志。

## API 配置与边界

兼容端点须支持 `POST <base_url>/chat/completions`、Bearer 认证、messages、response_format=json_object、max_tokens、temperature=0，以及 choices[0].message.content 和 finish_reason=stop 的响应结构。不承诺兼容所有模型或服务；不支持这些字段的服务需新增适配器。请求 schema 放入 system 指令，业务文档作为 user 数据。

复制 .env.example 为 .env，填写以下环境变量后在自己的 shell 中导出：

- ALGOFACTORY_API_BASE_URL：HTTPS API 根地址，通常包含 /v1，不含 /chat/completions。
- ALGOFACTORY_API_MODEL：服务提供的模型标识。
- ALGOFACTORY_API_KEY：访问凭据。
- ALGOFACTORY_API_INPUT_USD_PER_MILLION / OUTPUT_USD_PER_MILLION：所选模型的实际输入/输出单价。
- ALGOFACTORY_API_MAX_COST_USD：本 Provider 实例的保守估算预算。

程序不自动加载 .env。可以执行 `set -a`、`source .env`、`set +a` 显式加载，然后运行：

```sh
.venv/bin/python -m algofactory.cli ingest data/customer_churn.txt --mode api --db runtime/live-api.sqlite
```

默认连接/读取超时 30 秒，每个 Provider 最多 4 次请求，每次完整调用最多重试 1 次，最多输出 8192 token，请求 JSON 最大 128 KiB，响应最大 2,000,000 字节。认证错误不重试；限流、服务错误、网络错误和非法结构化响应在预算内重试。原文引用或关系校验失败直接拒绝入库。可通过 Python APIConfig 显式调整这些限制。

费用预算按请求 UTF-8 字节数加 1024 的输入 token 估算，以及最大输出 token 数和所填单价预留。失败请求也不返还预留，避免重试低估消耗。reserved_cost_usd 是估算预留而非实际账单；供应商的额外收费/推理 token 可能使用不同计费方式，真实费用硬限额应由供应商侧配置。本阶段未记录虚构的实际支出。

API 配置缺失时明确返回 api_configuration_missing；从不回退到 Mock。默认只允许 HTTPS；本地 HTTP 仅供测试构造 APIConfig 时显式启用。拒绝带用户信息、query 或 fragment 的根地址，不跟随重定向，避免把凭据发送到重定向目标。

## 验收与证据

```sh
.venv/bin/python scripts/verify_phase1.py --output-dir runtime/phase1
```

脚本检查格式、静态问题、Phase 0 原始资料散列和全部测试，再运行抽取、重复导入、关闭重开、查询与 GraphML 重载。输出 verification.json、tests.xml、check-*.log、knowledge.json、knowledge.sqlite、knowledge.graphml、retrieval.json、provider-audit.json。开始时先清除旧报告的通过状态，失败时不能残留过期的通过结论。

verification.json 记录 Asia/Shanghai 时间、解释器/架构/库版本、命令、实现提交及逐文件散列、产物散列。未提交的代码会标记 implementation_dirty，implementation_commit 为空。经检查的交付样例放在 examples/phase1/。

Phase 1 退出检查覆盖文档转实体关系、实体及来源查询、非法关系拒绝、事务与幂等、图谱往返、Mock/API 契约以及依赖复现。真实 API 调用目前缺少配置和凭据，因此该项保留 blocked。API 的本地 HTTP 契约通过不等于真实服务验收，也不等于 G2 的真实算法闭环。

## 后续阶段接口

Phase 2 接入自然语言 TaskSpec、规划、代码生成、Docker 隔离执行、四维评分与结果回写。当前 ExecutionBudget 只接受 Docker、禁网和 fail_closed；这是接口限制，不是已完成隔离执行的证据。ValidationResult 分离 validation_metrics 与 test_metrics，测试指标要求显式 final_test_evaluated；真实训练/验证/测试划分及一次性测试集访问仍由 Phase 2 验证器落实。

实现参考：[Pydantic 模型与校验](https://pydantic.dev/docs/validation/latest/concepts/models/)、[NetworkX GraphML](https://networkx.org/documentation/stable/reference/readwrite/graphml.html)。GraphML 重载限本项目可信导出，不将任意外部 XML 作为无约束输入。
