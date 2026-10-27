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

采用 SQLite + NetworkX 而非独立图数据库以减少本地运维；采用同进程三角色而非分布式消息系统以便调试；不引入 Beam/MCTS，先用有界候选策略。上述为待实施架构，当前没有核心运行实现。
