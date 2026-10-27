# AlgoFactory 验收 Gate

状态仅允许 planned、implemented、verified、blocked、out_of_scope。每项 verified 必须提供命令、提交号、时间、环境、产物散列和报告路径。骨架检查不能替代算法验收。

| Gate | 通过条件 | 必需证据 | 当前状态 |
| --- | --- | --- | --- |
| G0 规格基线 | 原题与方案归档；基础要求全部映射；架构、范围和演示明确 | 来源散列、需求矩阵、计划和契约 | 文档已建立，待用户评审 |
| G1 功能完整性 | 所有基础交付及选定范围有实际产物 | 矩阵逐项证据、抽取结果、代码及报告 | planned |
| G2 运行正确性 | Mock 可重复；API 至少一次真实闭环；修复与候选比较可运行 | 两模式运行记录、代码、四维验证与回写 | planned |
| G3 验证可信性 | 独立评分、训练拟合、同划分比较、测试集隔离 | 数据指纹、划分、冻结规则、泄漏及稳定性测试 | planned |
| G4 创新有效性 | 角色协作可追踪；历史经验在后续任务实际使用 | Demo B/C、经验来源及相同条件的对照 | planned |
| G5 交付复现性 | 新环境按 README 安装测试运行；全部交付可定位 | 依赖锁、arm64 环境记录、冷启动日志、GitHub 地址 | planned |

## 固定演示与验证协议

A 正常：合成客户流失数据 + 固定业务文档 + 自然语言需求，抽取并检索知识，生成 Python，容器执行，计算四维结果，输出报告，查询回写记录。

B 故障：明确标识的故障注入 fixture（例如缺失 predict_proba 或类别编码失败），必须保留初次失败日志、修复版本和重测报告。注入案例不冒充自然出现的 API 失误。最多两轮修复，覆盖无法修复和预算耗尽。

C 复用：先由 B 得到已验证经验，再提交相似任务；保存检索 ID、决策使用方式。使用相同数据、划分、初始故障、随机种子与预算，比较启用/关闭经验检索的修复次数、成功率和成本。先执行固定 Mock 对照，再记录 API 重复实验及波动，不凭单次结果声称普遍提升。

D 扩展：合成回归任务运行非空验证，使用 MAE/RMSE；新增一个模板和一个指标插件不改编排器，重复注册应失败。

四维检查：功能检查实际 fit/predict、输出长度及有限值；接口检查导出函数和任务方法；指标检查二分类 F1/ROC-AUC/Precision/Recall 与冻结门槛；稳定性检查固定种子重复、超时、异常数据、缺失列和资源超限。空候选、非法 LLM JSON、API 超时、Docker 缺失、回写失败均须输出显式失败状态。

最终无真实 API 或隔离执行证据时，对应 Gate 保持 blocked，不发布“全部通过”。

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
