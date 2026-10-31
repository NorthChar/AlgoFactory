# AlgoFactory 需求追踪矩阵

所有基础项均纳入实现范围；planned 表示尚待实施，不代表已经满足。ID 是原题的逐项映射，具体原文以 source/exam-original.txt 为准。CSV 为同内容的机器可读版本，未选择加分项不影响基础覆盖。

Phase 1 已验证 B03、B04 和当前阶段的 B10；命令、提交号、时间、环境、代码/产物散列统一记录在 [verification.json](../examples/phase1/verification.json)。独立安装证据见 [installation.json](../examples/phase1/installation.json)。后续依赖变更仍须重新验证 B10。全项目 Gate 尚未通过。

Phase 2 已通过 101 项测试（含真实 Docker，零跳过）及正常/重复/三类故障 CLI 验收，详见 [verification.json](../examples/phase2/verification.json)。本轮 verified 限于固定 Mock 单候选范围；T01/D07 的真实 API、Phase 3 修复比较及 Phase 4 经验复用仍未验收。B10 的新依赖在同机全新环境安装，并在 Linux ARM64 镜像安装验证；不代表新机器冷启动。

2026-10-29 的范围变更见 [ADR-001](decisions/0001-banking77-main-case.md)：BANKING77 为主案例，客户流失为轻量兼容性测试。Phase 2.5 已通过 G2.5，BK01–BK06、T02、X08 更新为 verified（固定 Mock 单候选范围），统一证据见 [verification.json](../examples/phase25/verification.json)。124 项测试零失败、零跳过；两任务共用同一实现提交。BK05 当前不消费 Experience，未来经验复用仍由 BK08 验收。BK08 与 Phase 5 轻量回归计划继续保留，完整 G1–G5 尚未通过。

Phase 3 的 BK07/A02/A03/X06 已通过 Mock 范围验收，见 [统一证据](../examples/phase3/verification.json)：141 项测试零失败、零跳过，包含真实 Docker 比较/修复与客户流失兼容。真实 API 与 Phase 4 经验复用仍未验收。

2026-10-29 真实 API 补验收已通过：T01/D07 更新为 verified，BK07/A02/A03/X06 增补真实证据，见 [最终严格复测](../examples/api-phase3/verification.json) 和 [全部三轮及用量](../examples/api-phase3/campaign-summary.json)。190 项回归测试全部通过，客户流失兼容仍通过；G2 的当前主线运行要求已满足。Phase 4 的 BK08/X05 保持 planned，实施入口见 [phase4.md](phase4.md)。

Phase 4 的 BK08/X05 现已 verified，见 [统一证据](../examples/phase4/verification.json)：210 项回归零失败、零跳过，Mock/API 各两组同条件对照及客户流失兼容通过。两组均一次修复、相同验证指标；开启组 token 更多，未证明普遍收益。此前 planned 记录为历史阶段时点，当前范围见 [Phase 4 指南](phase4.md)，下一阶段为 Phase 5。

Phase 5 已验证 T06/A01/A04/A07/A08/X02/X07，并补齐 F06 的既有修复证据索引。231 项测试与 CLI/Web 三任务运行见 [阶段证据](../examples/phase5/verification.json)。X02 限三个逻辑角色，X07 限证据驱动解释；本阶段无新付费 API 调用。完整交付仍由 Phase 6 验收。

Phase 6 本地冷启动已通过 233 项测试、零跳过，README 十项、依赖/构建锁、独立 wheel、三任务及 CLI/Web 见 [交付记录](phase6.md)和[统一证据](../examples/phase6/verification.json)。B01 的本地代码库及私有远端交付均已验收；[发布证据](../examples/phase6-publication/publication.json)核对仓库、提交和文件树，G1–G5 在声明范围内全部关闭。上文未验收/待下一阶段的描述保留各历史时点，当前状态以本段和下表为准。

2026-10-30 工作台增量单独记录为 UX01–UX05：0.6.1 的用途首页、七步证据和预算预检已有针对性验证；Phase 7 的数据浏览、模型预测、实验配置及新版本交付已验收（0.7.0）。2026-11-01 增加 UX06，将这些能力串成同一开发任务（0.7.1）。新验收使用 U0–U4，不覆盖原 G1–G5 或原题资料，详见 [Phase 7](phase7.md)。

| ID | 类别 | 要求 | 责任模块 | 交付或证据 | Phase | 验收方法 | Gate | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B01 | 基础 | 完整的项目代码库 | 全模块 | Git 仓库；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web）；examples/phase6-publication/publication.json（私有仓库、远端提交及文件树一致） | 6 | 冷启动完整运行 | G1/G5 | verified |
| B02 | 基础 | 示例行业数据、文档或模拟业务材料 | data | 数据生成器、CSV、业务文档；examples/phase2/verification.json（Mock 范围） | 1–2 | 种子与数据指纹一致 | G1/G5 | verified |
| B03 | 基础 | 能力知识图谱 schema 设计说明 | schemas/knowledge | docs/architecture.md、schema | 1 | 实体关系约束测试 | G1/G5 | verified |
| B04 | 基础 | 知识抽取结果文件 | knowledge | JSON、SQLite、GraphML | 1 | 文档抽取与图谱导出重载 | G1/G5 | verified |
| B05 | 基础 | Agent 工作流代码或流程配置 | orchestrator | 编排器及角色轨迹；examples/phase2/verification.json（Mock 范围） | 2 | 状态转换与停止条件测试 | G1/G5 | verified |
| B06 | 基础 | 至少 1 个从能力描述到算法代码生成的完整示例 | generation/examples | Demo A Python 与完整轨迹；examples/phase2/verification.json（Mock 范围） | 2 | 生成代码实际加载与执行 | G1/G5 | verified |
| B07 | 基础 | 自动验证脚本 | validation/scripts | 验证入口与四维检查；examples/phase2/verification.json（Mock 范围） | 2 | 故障 fixture 验证四维判断 | G1/G5 | verified |
| B08 | 基础 | 验证报告样例 | reporting/examples | 真实运行 JSON/Markdown；examples/phase2/verification.json（Mock 范围） | 2 | 报告与运行 ID、代码散列一致 | G1/G5 | verified |
| B09 | 基础 | 项目文档 README.md | docs | README 十项内容；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 逐项核对且命令可执行 | G1/G5 | verified |
| B10 | 基础 | 环境依赖文件 requirements.txt 或 environment.yml | configs | requirements.txt 及锁文件；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 1/6 | Mac arm64 干净环境安装 | G1/G5 | verified |
| B11 | 基础 | 使用示例和测试用例 | examples/tests | Demo A–D、单元及集成测试；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 2–6 | 依 README 执行且输出符合预期 | G1/G5 | verified |
| T01 | 任务 | LLM 理解、抽取、生成或修复 | llm | API/Mock 契约与调用记录；examples/api-phase3/verification.json（真实 Azure API 修复/严格比较/最终测试/回写）；campaign-summary.json（含全部失败与 20 次请求） | 1–3 | 两模式同编排器，API 真实调用 | G1/G2/G3 | verified |
| T02 | 任务 | 具体行业场景 | data | BANKING77 主案例（ADR-001、BK03）；客户流失历史证据仍见 examples/phase2；docs/phase25.md；examples/phase25/verification.json（G2.5 Mock 范围） | 0–2.5 | BANKING77 Demo A；客户流失新版兼容检查另见 BK04 | G1/G2/G3 | verified |
| T03 | 任务 | 能力知识库表达输入输出、条件、指标、依赖、历史结果 | knowledge | 实体关系与版本化验证；examples/phase2/verification.json（Mock 范围） | 1–2 | 全部字段可查询及来源追踪 | G1/G2/G3 | verified |
| T04 | 任务 | 自然语言到可运行代码 | agents/generation | 需求、方案与 Python；examples/phase2/verification.json（Mock 范围）；examples/api-phase3/verification.json | 2 | 固定 Mock 需求与真实 API 到真实容器执行；Phase 3 API 已验收 | G1/G2/G3 | verified |
| T05 | 任务 | 功能、指标、稳定性、接口统一验证 | validation | 四维检查与配置；examples/phase2/verification.json（Mock 范围）；examples/phase5/verification.json（231 项回归、CLI/Web、三任务及异常证据） | 2 | 正常及失败用例 | G1/G2/G3 | verified |
| T06 | 任务 | 提供用户入口 | cli/app | CLI 与 Streamlit；docs/phase5.md；examples/phase5/verification.json | 2/5 | 各自完成主流程 | G1/G2/G3 | verified |
| F01 | 流程 | 理解需求 | agents | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | TaskSpec 校验 | G2/G3 | verified |
| F02 | 流程 | 检索能力知识 | knowledge | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围）；examples/phase4/verification.json（210 项回归、经验隔离/幂等与当前兼容检查） | 1–4 | 返回实体与来源 ID | G2/G3 | verified |
| F03 | 流程 | 规划方案 | planning | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | AlgorithmPlan 与证据 | G2/G3 | verified |
| F04 | 流程 | 生成代码 | generation | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | Python 文件可加载 | G2/G3 | verified |
| F05 | 流程 | 自动测试与评估 | validation | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | 确定性指标 | G2/G3 | verified |
| F06 | 流程 | 错误修复或优化 | agents/generation | 状态轨迹与对应产物；examples/phase3/verification.json；examples/api-phase3/verification.json（真实修复与比较）；docs/phase5.md；examples/phase5/verification.json | 1–4 | Demo B | G2/G3 | verified |
| F07 | 流程 | 结果知识沉淀 | experience/knowledge | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | 重启后可查询 | G2/G3 | verified |
| A01 | 进阶 | CLI + Streamlit | cli/app | 双入口；docs/phase5.md；examples/phase5/verification.json | 2/5 | 主路径运行 | G1/G2/G3 | verified |
| A02 | 进阶 | 多轮代码修复 | agents/generation | 有界修复日志；docs/phase3.md；examples/phase3/verification.json（Mock 范围）；examples/api-phase3/verification.json（真实 Azure API 修复/严格比较/最终测试/回写）；campaign-summary.json（含全部失败与 20 次请求） | 3 | 错误修复与超预算终止 | G1/G2/G3 | verified |
| A03 | 进阶 | 多个候选自动比较 | planning/validation | 候选排名表；docs/phase3.md；examples/phase3/verification.json（Mock 范围）；examples/api-phase3/verification.json（真实 Azure API 修复/严格比较/最终测试/回写）；campaign-summary.json（含全部失败与 20 次请求） | 3 | 至少两候选同划分同预算 | G1/G2/G3 | verified |
| A04 | 进阶 | 知识图谱可视化 | knowledge/app | 图谱视图与 GraphML；docs/phase5.md；examples/phase5/verification.json | 5 | 显示实体及验证关联 | G1/G2/G3 | verified |
| A05 | 进阶 | 自动验证报告 | reporting | JSON/Markdown；examples/phase2/verification.json（Mock 范围）；examples/phase5/verification.json（231 项回归、CLI/Web、三任务及异常证据） | 2/5 | 字段完整、失败也报告 | G1/G2/G3 | verified |
| A06 | 进阶 | 验证结果回写 | knowledge/experience | SQLite 运行记录；examples/phase2/verification.json（Mock 范围）；examples/phase4/verification.json（210 项回归、经验隔离/幂等与当前兼容检查）；examples/phase5/verification.json（231 项回归、CLI/Web、三任务及异常证据） | 2 | 事务与幂等重试 | G1/G2/G3 | verified |
| A07 | 进阶 | 不同任务类型验证配置 | configs/validation | 表格二分类、文本多分类、合成回归；三任务独立协议与 MAE/RMSE 方向；docs/phase5.md；examples/phase5/verification.json | 2.5/5 | Demo A/E；Phase 5 Demo D 真实运行 | G1/G2/G3 | verified |
| A08 | 进阶 | 模板和指标插件 | plugins | 注册协议及插件样例；docs/phase5.md；examples/phase5/verification.json | 5 | 新增插件不改编排器 | G1/G2/G3 | verified |
| X01 | 加分 | 图搜索、Beam Search 或 MCTS | planning | 候选预算优先 | — | 候选预算优先 | — | out_of_scope |
| X02 | 加分 | 多智能体协作 | agents | 知识、构建、审查三个逻辑角色；输入/输出与确定性审查轨迹；非独立自治进程；docs/phase5.md；examples/phase5/verification.json | 3–5 | 三角色独立输入输出与决策轨迹 | G4 | verified |
| X03 | 加分 | 真实仓库抽取 | knowledge | 额外复杂性暂缓 | — | 额外复杂性暂缓 | — | out_of_scope |
| X04 | 加分 | 安全检查与沙箱 | execution | 非 root、禁网、限资源、超时、缺 Docker 拒绝；examples/phase2/verification.json（Mock 范围）；examples/phase5/verification.json（231 项回归、CLI/Web、三任务及异常证据） | 2–5 | 真实容器正常/接口故障/一秒超时与清理；OOM/清理失败仍为模拟测试 | G4 | verified |
| X05 | 加分 | 失败分析与复用经验 | experience | Demo C 与检索开关对照；docs/phase4.md；examples/phase4/verification.json（Mock/API 各两组；机制通过，未观察到次数/指标收益） | 3–5 | Demo C 与检索开关对照 | G4 | verified |
| X06 | 加分 | 能力版本管理 | experience | 父版本、散列、修改原因、报告关联；docs/phase3.md；examples/phase3/verification.json（Mock 范围）；examples/api-phase3/verification.json（真实 Azure API 修复/严格比较/最终测试/回写）；campaign-summary.json（含全部失败与 20 次请求） | 3–5 | 父版本、散列、修改原因、报告关联 | G4 | verified |
| X07 | 加分 | 设计依据自然语言解释 | reporting | 报告基于已接受 TaskSpec/AlgorithmPlan 生成解释，引用算法知识与验证记录；不声称单候选全局最优；docs/phase5.md；examples/phase5/verification.json | 3–5 | 解释引用真实知识与运行 ID | G4 | verified |
| X08 | 加分 | 跨场景迁移 | orchestrator/validation | ADR-001、BK04/BK06：同一核心运行表格与文本任务；docs/phase25.md；examples/phase25/verification.json（G2.5 Mock 范围）；examples/phase5/verification.json（231 项回归、CLI/Web、三任务及异常证据） | 2.5–5 | 同一提交及共用编排、隔离、评分/回写；两任务真实证据；不承诺经验跨业务提升 | G3/G4 | verified |
| X09 | 加分 | 自动接口文档或部署配置 | reporting | 当前非交付重点 | — | 当前非交付重点 | — | out_of_scope |
| X10 | 加分 | 性能优化和资源消耗分析 | execution | 仅安全预算与记录，不承诺优化 | — | 仅安全预算与记录，不承诺优化 | — | out_of_scope |
| D01 | 开发 | Git 清晰提交 | Git | 阶段提交历史；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web）；examples/phase6-publication/publication.json | 6 | 提交可追踪 | G5 | verified |
| D02 | 开发 | 完整文档 | docs | README、指南、示例；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 十项内容齐全 | G5 | verified |
| D03 | 开发 | 模块化及注释 | src | 契约、边界、说明；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 1–6 | 静态检查及代码评审 | G5 | verified |
| D04 | 开发 | 本地复现 | scripts | 环境与复现记录；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web）；examples/phase6-publication/publication.json | 6 | 冷启动 | G5 | verified |
| D05 | 开发 | Python 主语言 | src | Python 包；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 0–6 | 包入口运行 | G5 | verified |
| D06 | 开发 | 工具选型说明 | docs | 实施计划及架构；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 0 | 每个核心工具有理由 | G5 | verified |
| D07 | 开发 | Mock/API 演示 | llm | Provider 与 fixtures；examples/api-phase3/verification.json（真实 Azure API 修复/严格比较/最终测试/回写）；campaign-summary.json（含全部失败与 20 次请求） | 1–2 | 不得静默降级 | G5 | verified |
| R01 | README | 项目背景和目标 | docs/README | README 第 1 项；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 内容及链接、命令逐项核对 | G1/G5 | verified |
| R02 | README | 系统架构和模块设计 | docs/README | README 第 2 项；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 内容及链接、命令逐项核对 | G1/G5 | verified |
| R03 | README | 知识图谱 schema 和示例 | docs/README | README 第 3 项；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 内容及链接、命令逐项核对 | G1/G5 | verified |
| R04 | README | Agent 工作流设计 | docs/README | README 第 4 项；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 内容及链接、命令逐项核对 | G1/G5 | verified |
| R05 | README | 环境配置和运行方法 | docs/README | README 第 5 项；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 内容及链接、命令逐项核对 | G1/G5 | verified |
| R06 | README | 示例数据和测试任务说明 | docs/README | README 第 6 项；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 内容及链接、命令逐项核对 | G1/G5 | verified |
| R07 | README | 生成算法代码示例 | docs/README | README 第 7 项；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 内容及链接、命令逐项核对 | G1/G5 | verified |
| R08 | README | 验证结果和报告样例 | docs/README | README 第 8 项；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 内容及链接、命令逐项核对 | G1/G5 | verified |
| R09 | README | 挑战和解决方案 | docs/README | README 第 9 项；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 内容及链接、命令逐项核对 | G1/G5 | verified |
| R10 | README | 后续可扩展方向 | docs/README | README 第 10 项；examples/phase6/verification.json（233 项、同机独立环境及 wheel、三任务/CLI/Web） | 6 | 内容及链接、命令逐项核对 | G1/G5 | verified |
| S1 | 评分 | 技术能力 40% | 全模块 | G1/G2/G3：闭环、知识模型、验证、修复与比较 | 6 | 对应 Gate 证据审查 | G1/G2/G3 | planned |
| S2 | 评分 | 代码质量 30% | 全模块 | G5：模块、契约、日志、错误处理、测试、复现 | 6 | 对应 Gate 证据审查 | G5 | planned |
| S3 | 评分 | 创新性 15% | 全模块 | G4：角色协作、图谱增强、反馈决策、经验复用 | 6 | 对应 Gate 证据审查 | G4 | planned |
| S4 | 评分 | 完整性 15% | 全模块 | G1/G5：交付矩阵、文档、示例、报告、UI | 6 | 对应 Gate 证据审查 | G1/G5 | planned |
| BK01 | 主线调整 | BANKING77 数据来源固定与防泄漏处理 | datasets/configs | 版本、许可、原始/处理后散列、去重清单及类别映射；docs/phase25.md；examples/phase25/verification.json（G2.5 Mock 范围） | 2.5 | 重复导入可复现；按 ADR-001 划分且词表只 fit 训练集 | G2.5/G3/G5 | verified |
| BK02 | 主线调整 | 文本和多分类契约及独立验证 | schemas/execution/validation | 文本输入、77 类映射与概率矩阵、Macro-F1/逐类报告；docs/phase25.md；examples/phase25/verification.json（G2.5 Mock 范围） | 2.5 | 真实容器训练；输出对齐与标签隔离；非法输入拒绝 | G2.5/G2/G3 | verified |
| BK03 | 主线调整 | BANKING77 主案例单候选闭环 | orchestrator/llm/generation | Demo A 代码、角色轨迹、四维报告和知识回写；docs/phase25.md；examples/phase25/verification.json（G2.5 Mock 范围） | 2.5 | Mock 真执行可重复；失败不接受；真实 API 另验收 | G2.5/G1/G2 | verified |
| BK04 | 主线调整 | 客户流失轻量兼容性测试 | tests/configs | 已有合成数据、固定候选、改造后同一提交的新运行报告；docs/phase25.md；examples/phase25/verification.json（G2.5 Mock 范围）；examples/phase3/verification.json（持续兼容/证据）；examples/phase4/verification.json（210 项回归、经验隔离/幂等与当前兼容检查）；examples/phase5/verification.json（231 项回归、CLI/Web、三任务及异常证据） | 2.5–6 | 共用新编排与执行核心，二分类评分/回写通过；不扩充业务 UI | G2.5/G3/G5 | verified |
| BK05 | 主线调整 | 任务数据与知识适用条件隔离 | knowledge/orchestrator/validation | 数据模式、字段、标签空间、指标规则及经验适用条件；docs/phase25.md；examples/phase25/verification.json（G2.5 Mock 范围）；Phase 2.5 不消费 Experience，经验复用另由 BK08 验收；examples/phase4/verification.json（210 项回归、经验隔离/幂等与当前兼容检查） | 2.5–4 | 拒绝错配字段/标签/阈值及不兼容经验 | G2.5/G3/G4 | verified |
| BK06 | 主线调整 | 主案例与兼容案例验收证据索引 | scripts/reporting/docs | 命令、提交、时间、环境、代码/数据散列及两任务报告；docs/phase25.md；examples/phase25/verification.json（G2.5 Mock 范围）；examples/phase3/verification.json（持续兼容/证据）；examples/phase5/verification.json（231 项回归、CLI/Web、三任务及异常证据） | 2.5–6 | 必需测试零跳过；重开记录和证据匹配；支撑 X08 | G2.5/G1/G3/G4/G5 | verified |
| BK07 | 主线调整 | BANKING77 有界修复与候选比较 | planning/generation/validation | Demo B、多候选排名、代码父子版本与停止记录；docs/phase3.md；examples/phase3/verification.json（Mock 范围）；examples/api-phase3/verification.json（真实 Azure API 修复/严格比较/最终测试/回写）；campaign-summary.json（含全部失败与 20 次请求） | 3 | 至少两候选同协议；最多两次修复；客户流失兼容检查通过 | G2/G3 | verified |
| BK08 | 主线调整 | BANKING77 已验证经验复用 | experience/knowledge | Demo C、检索引用及启用/关闭经验对照；docs/phase4.md；examples/phase4/verification.json（Mock/API 各两组；机制通过，未观察到次数/指标收益） | 4 | 同输入/划分/预算对照；不声称客户流失效果改善 | G4 | verified |
| UX01 | 产品增量 | 工作台用途说明与七步证据浏览 | web/docs | docs/phase5.md；examples/workbench-061/verification.json；tests/test_web_workflow.py | 6后增量 | 只读导航不提交任务；候选证据与历史记录一致 | U0 | verified |
| UX02 | 产品增量 | 数据浏览与验证错误查看 | web/datasets/reporting | docs/phase7.md；tests/test_data_view.py | 7A | 样本与划分可核对；错误按 row_id 对齐；不访问逐条测试标签 | U1 | verified |
| UX03 | 产品增量 | 可信模型保存与隔离预测体验 | execution/schemas/web | docs/phase7.md；examples/phase7/verification.json；scripts/verify_phase7.py | 7B | 模型与代码数据配置绑定；真实预测；缺失和错配拒绝；无宿主执行 | U2 | verified |
| UX04 | 产品增量 | 受限可配置算法实验 | schemas/planning/generation/web | docs/phase7.md；examples/phase7/verification.json；scripts/verify_phase7.py | 7C | 配置贯穿真实执行与报告；冻结规则；拒绝冲突；旧默认兼容 | U3 | verified |
| UX05 | 产品增量 | 可操作工作台集成验收与版本交付 | tests/scripts/docs | docs/phase7.md；examples/phase7/verification.json；0.7.0 | 7D | U1–U3 通过；当前回归和独立复现；代码文档及远端一致 | U4 | verified |
| UX06 | 产品增量 | 围绕同一开发任务组织需求、进度、报告和算法试用 | web/tests/docs | docs/workbench-guide.md；tests/test_web_workflow.py；tests/test_model_trials.py；examples/workbench-071/verification.json | 7后整理 | 提交自动进入本任务；任务切换同步试用版本；失败不借用其他模型；浏览不执行 | U4 | verified |
