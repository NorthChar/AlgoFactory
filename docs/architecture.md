# AlgoFactory 架构与契约

2026-10-29 主线调整见 [ADR-001](decisions/0001-banking77-main-case.md)。Phase 2.5 已实现 BANKING77 英文文本多分类与客户流失二分类的共享流程，G2.5 已通过；详见 [指南](phase25.md)。

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

Provider 为同一结构化调用接口，Mock 按文件散列重放显式 fixture，API 使用 HTTPS chat-completions 兼容接口。两模式经过相同的响应和图谱校验；有限重试、调用数和保守费用预留独立于模型响应。上述为初始 Provider 设计；现已增加 Azure Responses/api-key 模式，并取得 [真实服务修复比较证据](../examples/api-phase3/verification.json)。本地 HTTP 测试本身仍不能替代真实服务证据。

## Phase 2 执行与评分边界

MockWorkflowProvider 和 APIProvider 共用 run_workflow；仅 Provider 的响应来源不同。前者固定需求、知识 fixture 和算法模板，未知需求明确失败。API 适配器用模拟传输测试整条编排，但不代表外部服务实测。

验证规则先由仓库自有基线在训练/验证集校准并保存散列。候选源文件通过受限 AST 检查，只有 Docker 内的 worker 会导入它。主机不加载生成模块，仅校验输出并用未挂载的标签独立评分。每个容器只看到代码、训练集、当前评估特征、配置四个输入文件；不可接触评估标签或整个工作目录。

验证阶段执行两次相同种子训练及异常输入检查；通过后锁定代码/数据/规则，写入一次性测试预约，再进行最终测试。一次测试指每个独立 workflow 的一次测试阶段；重复性实验有不同 workflow_id，禁止据其测试成绩调参。Docker 不可用、镜像过期、超时、资源超限、接口异常和回写失败均不能 ACCEPT。

实现、数据、验证运行及失败实体和 workflow_runs 记录在同一事务写入。执行证据作为来源文本，使用内容散列命名空间；实际分数保留 ValidationResult。Phase 2 不创建 Experience，不将失败诊断自动标为已验证经验。

## Phase 2.5 任务适配实现（verified，限 G2.5 范围）

共享路径为：CLI/未来 Web → 任务配置与数据适配 → 同一 Orchestrator → Provider/知识检索/生成 → 同一 Docker 执行器 → 按任务协议独立评分 → 共用报告与事务回写。适配器负责输入和任务差异；不复制 BANKING77 专用编排器，不让任意配置触发动态模块导入。

| 边界 | 改造前限制（历史 Phase 2） | Phase 2.5 实现 |
| --- | --- | --- |
| 任务契约 | TaskIntent 固定 churn，核心 TaskType 只有二分类/回归；字段类型没有 text | 增加文本输入、多分类及稳定类别映射，保留旧二分类契约兼容路径 |
| 数据适配 | 合成数据生成器、目标字段和特征名分散写在代码中 | 配置明确数据模式、特征、目标、标签映射、来源及划分协议；新增 BANKING77 导入，保留合成数据适配器 |
| 生成与依赖 | 单个 Logistic Regression 模板及有限构造器白名单 | 注册已批准的文本流水线模板及构造器；词表仅 fit 训练集；保持禁止任意 I/O 和执行前检查 |
| 执行与输出 | worker 固定 churn、类别 [0, 1] 与两列概率；宿主 WorkerResult 只接收正类概率 | 按任务输出类别 ID；多分类返回每类概率和顺序，校验与冻结映射一致、维度正确、有限值及概率合法；不把二分类输出静默解释为多分类 |
| 评分协议 | 主机评分固定二分类，校准器使用客户流失基线 | 增加 Macro-F1、Accuracy、逐类结果及混淆信息；协议与任务、类别映射绑定；独立冻结文本基线门槛 |
| 知识/经验 | 来源命名空间已有，但生成任务与回写描述仍绑定客户流失 | 保存实际数据模式、标签空间和任务身份；检索同时约束任务类型、数据类型和来源；尚不使用 Experience，防止串用字段和规则 |
| 报告与测试 | 历史报告只有客户流失二分类 | 标明任务/数据模式、原始与处理后指纹、类别映射、指标口径；同一提交验证 BANKING77 与客户流失 |

模型可读取的配置不得包含主机评估标签路径；容器仅获取训练标签和当前评估特征。构建镜像、只读挂载、禁网、预算与清理机制继续共用，修改 worker/依赖后必须重新构建并验收。新增文本适配不降低既有执行边界。

客户流失兼容检查使用固定候选与独立协议，不参与 BANKING77 的候选排名。跨场景通过证据必须来自新版本的共用核心，旧 examples/phase2 仅作为历史参考。

## Phase 3 有界比较与修复（Mock 与真实 API 均有验收证据）

search.run_search 基于统一 run_workflow 执行每个候选版本，以 validation_only 阻止子流程访问最终测试；最终测试由两模式共用的 final_test.evaluate_final 执行。SearchPolicy 固定候选、每候选最多两次修复、最多六次尝试与确定性排序。RepairContext 携带父实现、代码散列和验证集诊断。每次修复保留新目录及 DERIVED_FROM；最终验证引用已选实现。详情见 [Phase 3 指南](phase3.md)。

检索在数量限制前按来源及数据类型过滤，避免累积历史 Task 实体挤出当前算法证据。数据库 schema 仍为 v2，新增流程状态 validated 仅表示候选验证集通过；已归档旧数据库及报告保持不变。

真实 API 补验收增加受校验的历史失败恢复和同一比较内知识抽取复用。恢复只接受尚未测试的初始失败版本，核对代码/产物散列、数据库记录、算法、数据及规则；原历史尝试仍计入预算。已校验文档按内容散列在一次比较内复用，不用 Mock 替代 API 响应，也不将任意历史知识库当成此次抽取证据。

生成代码先经过原有安全检查与隔离执行；成功执行后仍须核对返回流水线的结构和运行前约定参数，才能成为排名候选。参数偏差以可诊断错误进入有界修复，不以较高分数豁免。该检查只解释受限 AST 中的构造器数据，不执行用户代码。当前真实修复比较验收见 [Phase 3](phase3.md)，经验提炼、复用机制和小规模对照现由 [Phase 4](phase4.md) 完成。


## Phase 4 经验复用路径

`experience_reuse.py` 从已归档且数据库一致的失败与修复报告提炼经验，核验所有来源散列、直接父子版本与验证协议；仅识别的文本适配规则可成为 verified，其他修复保留 proposed。可选 `repair_evidence` 扩展不改变旧记录序列化，旧格式仍可读，但不能据此自动检索。

搜索入口默认关闭经验；启用后冻结经验库快照，按任务、算法、文本字段、数据指纹、划分、配置和修复错误筛选。编排器保存检索结果与 builder 输入，要求模型逐条声明采用或不适用，并在独立配置检查后记录实际规则是否满足。新学经验只供后续搜索消费；`validation_only` 对照路径不预约最终测试，正常路径保留唯一获选版本测试规则。经验不改变安全检查、隔离执行或评分门槛。

当前仅验证同一冻结 BANKING77 协议的适配规则。Mock/API 两组配对均通过，但未观察到效果收益，详见 [Phase 4](phase4.md)。


## Phase 5 本地界面与扩展

Streamlit 是既有 CLI/编排器的入口，后台进程拥有独立数据副本、数据库与运行目录；提交 ID 幂等，进程锁限制并发，终态报告可恢复展示。读档不重新执行模型或测试，历史数据库只读。配置由 `RunSettings` 校验，Web API 请求上限 12，页面不接收密钥。

回归任务扩展共享 TaskProfile、WorkerResult、Docker worker、主机评分和回写；连续预测不再强制转整数，分类仍检查标签和概率空间。新增 Ridge 构造器保持受限 AST 工厂规则；返回流水线、数值列和 alpha 参数需通过结构检查。MAE/RMSE 由可信注册表计算，阈值方向明确为 minimize。模板通过注册表传给 Mock Provider，第三方代码不会由界面动态导入。具体限制、插件例和恢复语义见 [Phase 5](phase5.md)。


## Phase 7 可操作实验与模型边界

`experiments.ExperimentConfig` 把 BANKING77 候选、词表、词组范围和分类器参数冻结为 `experiment_hash`；评分协议仍用原 `config_hash`。CLI/Web 先验证配置，生成提示包含明确参数，静态检查验证生成代码确实遵守，再进入同一隔离执行和知识回写流程。单候选也复用有界修复协调器，报告不声称比较获胜。

`web/data_view.py` 只显示训练/验证样本；历史验证预测按归档散列校验后以 row_id 对齐。`web/models.py` 只接受已登记报告中的合格代码版本，核验模型、训练文件、类别、代码、实验及环境来源。worker 在容器内序列化和加载模型；宿主不执行生成代码或反序列化 pickle。预测容器只接收模型和本条输入，不挂载训练、验证或测试数据；测试文本重复守卫在宿主执行，不向模型提供测试标签。

新增功能的验收边界、版本及操作说明见 [Phase 7](phase7.md) 和 [工作台指南](workbench-guide.md)。
