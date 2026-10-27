# AlgoFactory 需求追踪矩阵

所有基础项均纳入实现范围；planned 表示尚待实施，不代表已经满足。ID 是原题的逐项映射，具体原文以 source/exam-original.txt 为准。CSV 为同内容的机器可读版本，未选择加分项不影响基础覆盖。

Phase 1 已验证 B03、B04 和当前阶段的 B10；命令、提交号、时间、环境、代码/产物散列统一记录在 [verification.json](../examples/phase1/verification.json)。独立安装证据见 [installation.json](../examples/phase1/installation.json)。后续依赖变更仍须重新验证 B10。全项目 Gate 尚未通过。

Phase 2 已通过 101 项测试（含真实 Docker，零跳过）及正常/重复/三类故障 CLI 验收，详见 [verification.json](../examples/phase2/verification.json)。本轮 verified 限于固定 Mock 单候选范围；T01/D07 的真实 API、Phase 3 修复比较及 Phase 4 经验复用仍未验收。B10 的新依赖在同机全新环境安装，并在 Linux ARM64 镜像安装验证；不代表新机器冷启动。

| ID | 类别 | 要求 | 责任模块 | 交付或证据 | Phase | 验收方法 | Gate | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B01 | 基础 | 完整的项目代码库 | 全模块 | Git 仓库 | 6 | 冷启动完整运行 | G1/G5 | planned |
| B02 | 基础 | 示例行业数据、文档或模拟业务材料 | data | 数据生成器、CSV、业务文档；examples/phase2/verification.json（Mock 范围） | 1–2 | 种子与数据指纹一致 | G1/G5 | verified |
| B03 | 基础 | 能力知识图谱 schema 设计说明 | schemas/knowledge | docs/architecture.md、schema | 1 | 实体关系约束测试 | G1/G5 | verified |
| B04 | 基础 | 知识抽取结果文件 | knowledge | JSON、SQLite、GraphML | 1 | 文档抽取与图谱导出重载 | G1/G5 | verified |
| B05 | 基础 | Agent 工作流代码或流程配置 | orchestrator | 编排器及角色轨迹；examples/phase2/verification.json（Mock 范围） | 2 | 状态转换与停止条件测试 | G1/G5 | verified |
| B06 | 基础 | 至少 1 个从能力描述到算法代码生成的完整示例 | generation/examples | Demo A Python 与完整轨迹；examples/phase2/verification.json（Mock 范围） | 2 | 生成代码实际加载与执行 | G1/G5 | verified |
| B07 | 基础 | 自动验证脚本 | validation/scripts | 验证入口与四维检查；examples/phase2/verification.json（Mock 范围） | 2 | 故障 fixture 验证四维判断 | G1/G5 | verified |
| B08 | 基础 | 验证报告样例 | reporting/examples | 真实运行 JSON/Markdown；examples/phase2/verification.json（Mock 范围） | 2 | 报告与运行 ID、代码散列一致 | G1/G5 | verified |
| B09 | 基础 | 项目文档 README.md | docs | README 十项内容 | 6 | 逐项核对且命令可执行 | G1/G5 | planned |
| B10 | 基础 | 环境依赖文件 requirements.txt 或 environment.yml | configs | requirements.txt 及锁文件 | 1/6 | Mac arm64 干净环境安装 | G1/G5 | verified |
| B11 | 基础 | 使用示例和测试用例 | examples/tests | Demo A–D、单元及集成测试 | 2–6 | 依 README 执行且输出符合预期 | G1/G5 | implemented |
| T01 | 任务 | LLM 理解、抽取、生成或修复 | llm | API/Mock 契约与调用记录 | 1–3 | 两模式同编排器，API 真实调用 | G1/G2/G3 | implemented |
| T02 | 任务 | 具体行业场景 | data | 客户流失预测任务；examples/phase2/verification.json（Mock 范围） | 0–2 | Demo A | G1/G2/G3 | verified |
| T03 | 任务 | 能力知识库表达输入输出、条件、指标、依赖、历史结果 | knowledge | 实体关系与版本化验证；examples/phase2/verification.json（Mock 范围） | 1–2 | 全部字段可查询及来源追踪 | G1/G2/G3 | verified |
| T04 | 任务 | 自然语言到可运行代码 | agents/generation | 需求、方案与 Python；examples/phase2/verification.json（Mock 范围） | 2 | 固定 Mock 需求到真实容器执行；真实 API 待验收 | G1/G2/G3 | verified |
| T05 | 任务 | 功能、指标、稳定性、接口统一验证 | validation | 四维检查与配置；examples/phase2/verification.json（Mock 范围） | 2 | 正常及失败用例 | G1/G2/G3 | verified |
| T06 | 任务 | 提供用户入口 | cli/app | CLI 与 Streamlit | 2/5 | 各自完成主流程 | G1/G2/G3 | implemented |
| F01 | 流程 | 理解需求 | agents | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | TaskSpec 校验 | G2/G3 | verified |
| F02 | 流程 | 检索能力知识 | knowledge | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | 返回实体与来源 ID | G2/G3 | verified |
| F03 | 流程 | 规划方案 | planning | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | AlgorithmPlan 与证据 | G2/G3 | verified |
| F04 | 流程 | 生成代码 | generation | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | Python 文件可加载 | G2/G3 | verified |
| F05 | 流程 | 自动测试与评估 | validation | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | 确定性指标 | G2/G3 | verified |
| F06 | 流程 | 错误修复或优化 | agents/generation | 状态轨迹与对应产物 | 1–4 | Demo B | G2/G3 | planned |
| F07 | 流程 | 结果知识沉淀 | experience/knowledge | 状态轨迹与对应产物；examples/phase2/verification.json（Mock 范围） | 1–4 | 重启后可查询 | G2/G3 | verified |
| A01 | 进阶 | CLI + Streamlit | cli/app | 双入口 | 2/5 | 主路径运行 | G1/G2/G3 | implemented |
| A02 | 进阶 | 多轮代码修复 | agents/generation | 有界修复日志 | 3 | 错误修复与超预算终止 | G1/G2/G3 | planned |
| A03 | 进阶 | 多个候选自动比较 | planning/validation | 候选排名表 | 3 | 至少两候选同划分同预算 | G1/G2/G3 | planned |
| A04 | 进阶 | 知识图谱可视化 | knowledge/app | 图谱视图与 GraphML | 5 | 显示实体及验证关联 | G1/G2/G3 | planned |
| A05 | 进阶 | 自动验证报告 | reporting | JSON/Markdown；examples/phase2/verification.json（Mock 范围） | 2/5 | 字段完整、失败也报告 | G1/G2/G3 | verified |
| A06 | 进阶 | 验证结果回写 | knowledge/experience | SQLite 运行记录；examples/phase2/verification.json（Mock 范围） | 2 | 事务与幂等重试 | G1/G2/G3 | verified |
| A07 | 进阶 | 不同任务类型验证配置 | configs/validation | 二分类及回归配置 | 5 | Demo D 真实运行 | G1/G2/G3 | planned |
| A08 | 进阶 | 模板和指标插件 | plugins | 注册协议及插件样例 | 5 | 新增插件不改编排器 | G1/G2/G3 | planned |
| X01 | 加分 | 图搜索、Beam Search 或 MCTS | planning | 候选预算优先 | — | 候选预算优先 | — | out_of_scope |
| X02 | 加分 | 多智能体协作 | agents | 三角色独立输入输出与决策轨迹 | 3–5 | 三角色独立输入输出与决策轨迹 | G4 | planned |
| X03 | 加分 | 真实仓库抽取 | knowledge | 额外复杂性暂缓 | — | 额外复杂性暂缓 | — | out_of_scope |
| X04 | 加分 | 安全检查与沙箱 | execution | 非 root、禁网、限资源、超时、缺 Docker 拒绝；examples/phase2/verification.json（Mock 范围） | 2–5 | 真实容器正常/接口故障；超时/OOM/清理失败模拟测试 | G4 | verified |
| X05 | 加分 | 失败分析与复用经验 | experience | Demo C 与检索开关对照 | 3–5 | Demo C 与检索开关对照 | G4 | planned |
| X06 | 加分 | 能力版本管理 | experience | 父版本、散列、修改原因、报告关联 | 3–5 | 父版本、散列、修改原因、报告关联 | G4 | planned |
| X07 | 加分 | 设计依据自然语言解释 | reporting | 解释引用真实知识与运行 ID | 3–5 | 解释引用真实知识与运行 ID | G4 | planned |
| X08 | 加分 | 跨场景迁移 | validation | 轻量回归只验证配置机制 | — | 轻量回归只验证配置机制 | — | out_of_scope |
| X09 | 加分 | 自动接口文档或部署配置 | reporting | 当前非交付重点 | — | 当前非交付重点 | — | out_of_scope |
| X10 | 加分 | 性能优化和资源消耗分析 | execution | 仅安全预算与记录，不承诺优化 | — | 仅安全预算与记录，不承诺优化 | — | out_of_scope |
| D01 | 开发 | Git 清晰提交 | Git | 阶段提交历史 | 6 | 提交可追踪 | G5 | planned |
| D02 | 开发 | 完整文档 | docs | README、指南、示例 | 6 | 十项内容齐全 | G5 | planned |
| D03 | 开发 | 模块化及注释 | src | 契约、边界、说明 | 1–6 | 静态检查及代码评审 | G5 | implemented |
| D04 | 开发 | 本地复现 | scripts | 环境与复现记录 | 6 | 冷启动 | G5 | implemented |
| D05 | 开发 | Python 主语言 | src | Python 包 | 0–6 | 包入口运行 | G5 | planned |
| D06 | 开发 | 工具选型说明 | docs | 实施计划及架构 | 0 | 每个核心工具有理由 | G5 | planned |
| D07 | 开发 | Mock/API 演示 | llm | Provider 与 fixtures | 1–2 | 不得静默降级 | G5 | implemented |
| R01 | README | 项目背景和目标 | docs/README | README 第 1 项 | 6 | 内容及链接、命令逐项核对 | G1/G5 | planned |
| R02 | README | 系统架构和模块设计 | docs/README | README 第 2 项 | 6 | 内容及链接、命令逐项核对 | G1/G5 | planned |
| R03 | README | 知识图谱 schema 和示例 | docs/README | README 第 3 项 | 6 | 内容及链接、命令逐项核对 | G1/G5 | planned |
| R04 | README | Agent 工作流设计 | docs/README | README 第 4 项 | 6 | 内容及链接、命令逐项核对 | G1/G5 | planned |
| R05 | README | 环境配置和运行方法 | docs/README | README 第 5 项 | 6 | 内容及链接、命令逐项核对 | G1/G5 | planned |
| R06 | README | 示例数据和测试任务说明 | docs/README | README 第 6 项 | 6 | 内容及链接、命令逐项核对 | G1/G5 | planned |
| R07 | README | 生成算法代码示例 | docs/README | README 第 7 项 | 6 | 内容及链接、命令逐项核对 | G1/G5 | planned |
| R08 | README | 验证结果和报告样例 | docs/README | README 第 8 项 | 6 | 内容及链接、命令逐项核对 | G1/G5 | planned |
| R09 | README | 挑战和解决方案 | docs/README | README 第 9 项 | 6 | 内容及链接、命令逐项核对 | G1/G5 | planned |
| R10 | README | 后续可扩展方向 | docs/README | README 第 10 项 | 6 | 内容及链接、命令逐项核对 | G1/G5 | planned |
| S1 | 评分 | 技术能力 40% | 全模块 | G1/G2/G3：闭环、知识模型、验证、修复与比较 | 6 | 对应 Gate 证据审查 | G1/G2/G3 | planned |
| S2 | 评分 | 代码质量 30% | 全模块 | G5：模块、契约、日志、错误处理、测试、复现 | 6 | 对应 Gate 证据审查 | G5 | planned |
| S3 | 评分 | 创新性 15% | 全模块 | G4：角色协作、图谱增强、反馈决策、经验复用 | 6 | 对应 Gate 证据审查 | G4 | planned |
| S4 | 评分 | 完整性 15% | 全模块 | G1/G5：交付矩阵、文档、示例、报告、UI | 6 | 对应 Gate 证据审查 | G1/G5 | planned |
