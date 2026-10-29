# AlgoFactory 验收 Gate

状态仅允许 planned、implemented、verified、blocked、out_of_scope。每项 verified 必须提供命令、提交号、时间、环境、产物散列和报告路径。骨架检查不能替代算法验收。

2026-10-29 按 [ADR-001](decisions/0001-banking77-main-case.md) 调整主线：BANKING77 为主案例，客户流失为轻量兼容性测试。下方历史 Phase 1/2 记录维持原范围；BANKING77、新版兼容性和框架跨场景能力已通过 G2.5。G2.5 是进入 Phase 3 前的阶段门槛，不替代全项目 G1–G5。

| Gate | 通过条件 | 必需证据 | 当前状态 |
| --- | --- | --- | --- |
| G0 规格基线 | 原题与方案归档；基础要求全部映射；架构、范围和演示明确 | 来源散列、需求矩阵、计划和契约 | 文档已建立，待用户评审 |
| G1 功能完整性 | 所有基础交付及选定范围有实际产物 | 矩阵逐项证据、抽取结果、代码及报告 | planned |
| G2 运行正确性 | Mock 可重复；API 至少一次真实闭环；修复与候选比较可运行 | 两模式运行记录、代码、四维验证与回写 | planned |
| G3 验证可信性 | 独立评分、训练拟合、同划分比较、测试集隔离 | 数据指纹、划分、冻结规则、泄漏及稳定性测试 | planned |
| G4 创新有效性 | 角色协作可追踪；历史经验在后续任务实际使用；同一框架支持表格/文本 | Demo B/C、经验对照、同一提交上的主案例与兼容运行证据 | planned |
| G5 交付复现性 | 新环境按 README 安装测试运行；全部交付可定位 | 依赖锁、arm64 环境记录、冷启动日志、GitHub 地址 | planned |

## 固定演示与验证协议

A 正常（当前主线，Mock 范围 verified）：BANKING77 + 可追溯的文本分类能力文档 + 自然语言开发需求，生成分类代码、在容器内训练、独立评分并回写。原客户流失 Demo A 的历史结果保留在 examples/phase2，不作为 BANKING77 成绩。

B 故障（BANKING77，Phase 3 Mock 范围 verified）：明确标识的故障注入 fixture（例如缺失 predict_proba、文本流水线接口不符或类别映射错误），必须保留初次失败日志、修复版本和重测报告。注入案例不冒充自然出现的 API 失误。最多两轮修复，覆盖无法修复和预算耗尽。

C 复用（BANKING77，Phase 4）：先由 B 得到已验证经验，再提交同场景相似任务；保存检索 ID、决策使用方式。使用相同数据、划分、初始故障、随机种子与预算，比较启用/关闭经验检索的修复次数、成功率和成本。先执行固定 Mock 对照，再记录 API 重复实验及波动，不凭单次结果声称普遍提升。不声称该经验已改善客户流失任务。

D 扩展：合成回归任务运行非空验证，使用 MAE/RMSE；新增一个模板和一个指标插件不改编排器，重复注册应失败。

E 兼容与跨场景（Phase 2.5 起）：在改造后的同一实现提交上，客户流失固定候选与 BANKING77 主案例共用核心编排、Docker、报告和回写，仅切换任务配置/适配器。两者均真实运行且通过各自冻结协议；检查标签空间、数据指纹、指标阈值与检索条件不混用。客户流失不另做业务 UI 或完整修复演示。

四维检查：功能检查实际 fit/predict、输出长度及有限值；接口检查导出函数、任务方法及概率列和类别映射一致性。BANKING77 以 Macro-F1 对照冻结门槛，同时报告 Accuracy、逐类指标和混淆情况；客户流失继续使用独立二分类 F1/ROC-AUC/Precision/Recall 协议。稳定性检查固定种子重复、超时、异常数据、缺失列、非法文本与资源超限。空候选、非法 LLM JSON、API 超时、Docker 缺失、回写失败均须输出显式失败状态。

最终无真实 API 或隔离执行证据时，对应 Gate 保持 blocked，不发布“全部通过”。

## G2.5：进入 Phase 3 前的阶段门槛（verified）

| 检查项 | 需求映射 | 必需证据 | 状态 |
| --- | --- | --- | --- |
| BANKING77 来源固定及处理后数据可复现 | BK01 / B02 | 上游版本、许可/署名、原始与处理后散列、去重清单、划分及类别映射 | verified |
| 文本与多分类契约、隔离执行及主机评分 | BK02 / T05 | 77 类预测/概率对齐、泄漏检查、非法输入/输出拒绝、镜像身份 | verified |
| 主案例单候选真实 Mock 闭环 | BK03 / T02 / T04 | Demo A 全流程、四维报告、数据库重开查询、源码与版本关联 | verified |
| 共享框架上的客户流失兼容性检查 | BK04 / B11 | 同一提交的新运行，固定数据/候选、独立协议及端到端报告 | verified |
| 数据和知识适用条件隔离 | BK05 / T03 | 字段/标签/阈值错配被拒绝，不兼容知识或经验不得直接套用 | verified |
| 可重复的阶段验收与证据索引 | BK06 / B07 / B08 / X08 | 入口、命令、时间、环境、提交、散列、两任务真实运行记录；无必需测试跳过 | verified |

2026-10-29 在实现提交 `c40ab0a32c21037f81a2472b8ec60d0626716288` 上通过：124 项测试，0 失败、0 错误、0 跳过。命令、环境、时间和全部散列见 [verification.json](../examples/phase25/verification.json)，具体结果与限制见 [Phase 2.5 指南](phase25.md)。BANKING77 正常及重复、客户流失兼容和三类失败示例均已归档；不消费 Experience，Phase 4 经验复用另验收。

该门槛的流程验证使用 Mock；真实 API 仍属于完整 G2 要求。任何历史 passing 记录都不能自动提升本表状态。Phase 3 的修复/比较和 Phase 4 的经验对照仍分别由 BK07、BK08 跟踪。

## Phase 1 阶段退出记录

本节是阶段检查，不改变 G1–G5 的完整项目验收范围。

| 检查项 | 状态 | 证据 |
| --- | --- | --- |
| 六类契约、九类知识实体及关系校验 | verified | tests/test_contracts.py、tests/test_knowledge.py |
| 业务文档 → 结构化知识 → SQLite | verified | examples/phase1/knowledge.json、knowledge.sqlite、provider-audit.json |
| 带来源检索、重开持久化、幂等与失败回滚 | verified | examples/phase1/retrieval.json、测试报告 |
| NetworkX/GraphML 导出及无损重载 | verified | examples/phase1/knowledge.graphml、测试报告 |
| Mock/API 共同契约及本地模拟 HTTP 服务测试 | verified | tests/test_providers.py、examples/phase1/tests.xml |
| Python 3.11 ARM64 依赖锁与独立安装 | verified | uv.lock、requirements 文件、examples/phase1/installation.json |
| 真实外部 API 抽取 | blocked | 未配置端点、模型、密钥与价格；不作为已通过证据 |

统一命令、提交号、Asia/Shanghai 时间、环境、代码和产物散列见 examples/phase1/verification.json。Phase 1 证据保持原样；算法闭环与隔离执行见下方 Phase 2 记录，完整项目 Gate 仍待后续验收。


## Phase 2 Mock 阶段退出记录

2026-10-27 在 macOS ARM64 / Python 3.11.16 主机及 Docker Linux ARM64 / Python 3.11.18 容器完成验收。101 项测试通过，0 失败、0 错误、0 跳过。代码版本、命令、精确时间及散列见 [verification.json](../examples/phase2/verification.json)。

| 检查项 | 状态 | 证据 |
| --- | --- | --- |
| 固定需求→检索→规划→生成→真实 Docker→独立评分→回写 | verified | examples/phase2/normal/ |
| 相同数据/候选/协议重复运行，指标一致 | verified | examples/phase2/repeat/ |
| 接口缺失、危险代码、非法响应明确失败且不进入测试 | verified | missing-interface/、unsafe-code/、invalid-response/ |
| 冻结阈值、数据指纹、标签隔离、一次测试阶段 | verified | dataset/protocol.json、normal/selection.json、test-access.json、容器证据 |
| 事务回写、重开查询及 GraphML 无损重载 | verified | knowledge.sqlite、knowledge.json、knowledge.graphml、tests.xml |
| 同机全新环境 wheel 安装及容器锁定依赖安装 | verified | installation.json、docker-image.json |
| Mock/API 共用编排器，模拟 API 传输全流程 | verified | tests/test_phase2.py；不属于真实服务证据 |
| 外部 LLM API 真实闭环 | blocked | 按当前约定使用 Mock，未配置或调用真实服务 |
| 自动修复、多候选比较及经验复用 | planned | Phase 3–4 |

超时、OOM、容器清理失败使用模拟 Docker 响应测试错误处理，未声称实际资源压测。G2 仍需真实 API、修复与比较；G3 的多候选同协议比较留待 Phase 3。所有阶段证据均不代表 G1–G5 整体通过。

## Phase 3 阶段门槛（verified，Mock 范围）

| 检查项 | 需求映射 | 必需证据 | 状态 |
| --- | --- | --- | --- |
| 至少两个候选使用同一冻结协议，稳定排名 | BK07 / A03 | comparison 与 repeat、ranking、协议及数据散列 | verified |
| 实际错误反馈、最多两次修复及版本关系 | BK07 / A02 / X06 | 初次失败、修复输入、父版本、真实容器重测及回写 | verified |
| 无法修复、预算耗尽、安全停止 | BK07 / A02 | 明确失败/停止结果，不打开最终测试 | verified |
| 只测试唯一选中版本，失败不重选 | BK07 / G3 | 一次性测试记录、单元边界检查 | verified |
| 原客户流失兼容及完整阶段证据 | BK04 / BK06 | 新提交上的兼容报告、全量测试零跳过、图谱重开 | verified |

阶段操作与验收入口见 [Phase 3 指南](phase3.md)。真实 API、经验复用与完整 G1–G5 保留原验收范围。

2026-10-29 实现提交 `bdd91bedb19ea00402aca97a9cfddac2b561563f` 完成 141 项测试（0 失败、0 错误、0 跳过）及九个 CLI 示例。排名复现、实际修复重测、两个候选各两次修复耗尽、无进展停止、总尝试/调用预算、安全停止与客户流失兼容均通过，见 [统一证据](../examples/phase3/verification.json)。最终测试失败后禁止重选、API 反馈传输等边界使用明确单元模拟；真实 API 和实际资源压力测试未执行。

## 2026-10-29 Azure API 接入增量记录

Azure GPT-4o Responses 已通过真实连通性与需求解析；首个 BANKING77 业务流程在知识图谱一致性校验处停止，失败记录已回写，尚未生成代码或访问测试集。累计六次请求，其中三次 HTTP 拒绝未返回用量，三次成功响应共输入 7,339、输出 3,004 token。完整真实 API 闭环仍未通过，不改变上面历史阶段结论或 G2 状态。见 [接入说明](api-integration.md) 与 [独立证据](../examples/api-integration/verification.json)。

### 同日知识层修复复测

重新请求并离线重放定位到 `Algorithm DEPENDS_ON Dependency` 不符合运行图谱端点规则。输出契约收窄后，真实 BANKING77 文档抽取、图谱校验、入库和检索通过；随后出现 `unsupported_phase2_plan`，未生成代码、未训练、未访问测试集。该记录只验证知识层修复，不提升完整 G2。见 [本次独立证据](../examples/api-knowledge-fix/verification.json) 和 [详细说明](api-integration.md)。

### 同日规划修复与执行复测

通过已保存的真实检索证据复现 dependencies 被解释为算法组件的问题，收窄规划契约后两轮真实 API 规划通过，代码已进入 Docker。两轮均因文本输入接口问题失败；人工单点修改在验证集上通过，仅作诊断证据，不作模型自动修复或完整闭环通过。未访问最终测试集，完整 G2 状态不变。见 [本轮证据](../examples/api-plan-fix/verification.json)；174 项回归测试零失败、零跳过。
