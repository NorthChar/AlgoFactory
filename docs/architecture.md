# AlgoFactory 架构与契约

## 模块边界

CLI / Streamlit → Orchestrator → Knowledge Agent、Builder Agent、Review Agent → 确定性工具。三角色可共用 Provider，但各有输入、输出及真实决策日志。Review 只能诊断与建议，不得修改验证规则。

| 模块 | 输入与输出 | 责任 |
| --- | --- | --- |
| schemas | TaskSpec、AlgorithmPlan、Candidate、ValidationResult、AgentDecision、ExperienceRecord | Pydantic 校验，版本化契约 |
| llm | 角色消息与结构化响应 | Mock/API 同接口；有限重试、超时和费用预算 |
| knowledge | 文档→实体关系；任务→证据 ID | SQLite 事实源，NetworkX 为派生视图 |
| agents / planning | 状态与证据→方案和动作 | 分角色决策，固定预算 |
| generation | 方案/诊断→代码版本 | 模板与修复插件，不直接执行 |
| execution | 代码、数据、预算→退出码及日志 | 安全检查与隔离执行 |
| validation | 执行产物和冻结规则→四维结果 | 指标由程序计算，拒绝 LLM 自报分数 |
| experience | 运行与修复→经验及版本关联 | 事务、幂等、来源及已验证状态 |
| reporting | 结构化结果→JSON/Markdown | 候选比较、失败原因、证据路径 |

状态流为 received → parsed → retrieved → planned → generated → checked → executed → validated → persisted → accepted/failed/stopped。诊断后可 repair/optimize/switch 回到生成；超预算终止。每次转换记录 run_id、candidate_id、代码散列、来源 ID、配置散列与原因。失败也保存，但不得标为通过。

## 接口契约

TaskSpec 包含 task_id、task_type、target、feature_schema、data_fingerprint、split_id、metrics、constraints、seed。AlgorithmPlan 包含算法、预处理、依赖、evidence_ids。Candidate 包含 implementation_id、parent_id、code_hash、plan_id、attempt。ValidationResult 包含功能/指标/稳定性/接口四项结果、验证与测试指标分离、运行资源、报告路径、错误类别。AgentDecision 包含 action、reason、evidence_ids、budget_remaining。ExperienceRecord 包含 condition、action、outcome、source_run_id、verification_status。

生成模块统一提供 build_pipeline(config)，返回具备 fit、predict 的 sklearn 兼容估计器，二分类额外支持 predict_proba。数据拆分和评分归验证器所有。生成模块不读取测试集路径、不安装依赖、不发起网络请求。

## 图谱模型

| 实体 | 必要属性 |
| --- | --- |
| Task | id、type、constraints |
| Capability | id、description、input、output、conditions、metrics |
| Algorithm | id、family、applicability |
| Implementation | id、version、code_hash、parent_id |
| Dataset | id、schema、fingerprint、split_id |
| ValidationRun | id、status、metrics、config_hash |
| FailureCase | id、category、root_cause |
| Experience | id、condition、action、outcome、verification_status |
| Dependency | id、package、version_constraint |

关系为 Task REQUIRES Capability；Algorithm IMPLEMENTS Capability / APPLICABLE_TO Task；Implementation USES Algorithm / DEPENDS_ON Dependency / DERIVED_FROM Implementation；ValidationRun EVALUATES Implementation / USES_DATASET Dataset / REPORTS FailureCase；Experience DERIVED_FROM ValidationRun。实体含 source_id、source_span、schema_version；外键与关系类型必须校验。原文片段到抽取实体、规划引用、代码版本及验证报告应可连续追踪。

## 安全与扩展

预先批准的容器镜像与依赖，非 root、禁网、根文件系统只读、临时可写目录、输入只读挂载、限制 CPU/内存/PID/超时、移除 capabilities，不挂载 Docker socket、用户主目录或密钥。静态代码检查只是第一层，不能替代隔离。没有 Docker 时 fail closed。

任务验证配置以 task_type 选择指标和接口规则；模板插件及指标插件用显式注册表，重复名称和不兼容任务类型报错。不允许由用户输入自动导入任意 Python 路径。

## 决策记录

采用 SQLite + NetworkX 而非独立图数据库以减少本地运维；采用同进程三角色而非分布式消息系统以便调试；不引入 Beam/MCTS，先用有界候选策略。Phase 2 已实现 orchestrator、datasets、generation、execution、validation、experience.py 与 reporting。Knowledge/Builder 使用 Provider 结构化调用，Review 为确定性 ACCEPT/STOP；独立 LLM Review、修复和经验提炼留待后续阶段。

## Phase 1 落地说明

实现细节与操作见 [Phase 1 指南](phase1.md)。SQLite 是事实源，NetworkX MultiDiGraph 为可重建视图；JSON/GraphML 保留完整类型化 payload 和归档原文。知识 payload 的 schema_version 保持 1；Phase 2 将 SQLite user_version 升为 2，新增 workflow_runs 表，打开旧库时迁移并保留已有知识。

来源采用内容散列 ID，实体和关系使用来源命名空间。source_span 是原文 Unicode 字符的左闭右开区间及精确引用。写入前检查引用、关系端点、ID 冲突、历史验证与实现/划分关联、经验状态和版本环；一个批次在同一事务中提交，重复内容幂等返回。文档抽取只允许 Task/Capability/Algorithm/Dependency，禁止把文档中的模型自述当成真实运行历史。

Provider 为同一结构化调用接口，Mock 按文件散列重放显式 fixture，API 使用 HTTPS chat-completions 兼容接口。两模式经过相同的响应和图谱校验；有限重试、调用数和保守费用预留独立于模型响应。真实服务调用尚待配置和验收，本地 HTTP 测试不能替代它。

## Phase 2 执行与评分边界

MockWorkflowProvider 和 APIProvider 共用 run_workflow；仅 Provider 的响应来源不同。前者固定需求、知识 fixture 和算法模板，未知需求明确失败。API 适配器用模拟传输测试整条编排，但不代表外部服务实测。

验证规则先由仓库自有基线在训练/验证集校准并保存散列。候选源文件通过受限 AST 检查，只有 Docker 内的 worker 会导入它。主机不加载生成模块，仅校验输出并用未挂载的标签独立评分。每个容器只看到代码、训练集、当前评估特征、配置四个输入文件；不可接触评估标签或整个工作目录。

验证阶段执行两次相同种子训练及异常输入检查；通过后锁定代码/数据/规则，写入一次性测试预约，再进行最终测试。一次测试指每个独立 workflow 的一次测试阶段；重复性实验有不同 workflow_id，禁止据其测试成绩调参。Docker 不可用、镜像过期、超时、资源超限、接口异常和回写失败均不能 ACCEPT。

实现、数据、验证运行及失败实体和 workflow_runs 记录在同一事务写入。执行证据作为来源文本，使用内容散列命名空间；实际分数保留 ValidationResult。Phase 2 不创建 Experience，不将失败诊断自动标为已验证经验。
