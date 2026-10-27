# AlgoFactory

面向客户流失预测的 AI Agent 算法能力工厂原型。目标是能力抽取、代码复刻、独立验证、修复与经验回写。当前已实现 Phase 1 知识层、数据契约和 Mock/API Provider。算法生成与执行闭环从 Phase 2 开始，Streamlit 尚未实现。

## 文档入口

- [题目原文](docs/source/exam-original.txt) 与 [用户方案原始附件](docs/source/discussion-plan-original.txt)
- [总体实施计划与问题定义](docs/implementation-plan.md)
- [需求追踪矩阵](docs/requirements-matrix.md) 与 [CSV](docs/requirements-matrix.csv)
- [架构、图谱及数据契约](docs/architecture.md)
- [验收 Gate 与演示协议](docs/acceptance-gates.md)
- [Phase 1 使用与验收说明](docs/phase1.md) 与 [实际验证证据](examples/phase1/verification.json)

## 安装与运行

已在 macOS ARM64、Python 3.11.16 验证。使用 uv 的项目环境：

```sh
uv sync --frozen --python 3.11
.venv/bin/python -m algofactory.cli status
.venv/bin/python -m algofactory.cli ingest data/customer_churn.txt --mode mock
.venv/bin/python -m algofactory.cli search --entity-type Algorithm --task-type binary_classification
.venv/bin/python -m algofactory.cli export --output-dir runtime/knowledge-export
.venv/bin/python scripts/verify_phase1.py --output-dir runtime/phase1
```

首次安装依赖需要联网；安装后 Mock 演示与测试无需外部网络或 API Key。测试会在 127.0.0.1 临时启动模拟 HTTP 服务。预期知识导入为 6 个实体、7 条关系，检索返回 3 个候选算法及原文证据；重复导入新增数量为 0。

不用 uv 时，可以使用已有的 Python 3.11：

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m pip install --no-deps -e .
```

requirements.txt 是运行依赖，requirements-dev.txt 另含测试与检查工具；两者从 uv.lock 导出，带版本和文件散列。构建工具由 pyproject.toml 声明。

## Phase 1 架构与示例

```text
UTF-8 业务文档 → Mock/API Provider → Pydantic 契约与原文引用校验
                                   ↓
                           SQLite 原子化入库
                                   ↓
                   条件检索与来源证据 / JSON / NetworkX GraphML
```

模块位于 src/algofactory：schemas 定义六类核心契约和九类知识实体；llm 提供有预算的结构化调用；knowledge 负责抽取、持久化、检索及导出；cli 提供上述命令。

示例关系包括 `Task REQUIRES Capability`、`Algorithm IMPLEMENTS Capability` 和 `Algorithm APPLICABLE_TO Task`。文档引用采用原始字符区间，每条知识保存 source_id、source_span 和 schema_version。完整定义见 [架构](docs/architecture.md)，实际结果见 [知识 JSON](examples/phase1/knowledge.json) 和 [GraphML](examples/phase1/knowledge.graphml)。

Mock 使用人工编写、按原文散列匹配的固定 fixture。未知文档会明确失败；API 使用相同抽取及校验流程，可处理新文档。API 端点、模型、密钥与价格需显式配置，详见 [Phase 1 指南](docs/phase1.md)。当前 API 经过本地模拟服务契约测试，尚无真实服务调用证据。

## 测试与产物

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m algofactory.cli schemas --output-dir runtime/schemas
```

验收脚本生成知识 JSON、SQLite、GraphML、检索结果、调用轨迹、测试日志和 verification.json。报告记录命令、环境、代码提交/散列及产物散列。当前证据只覆盖 Phase 1；算法指标、隔离运行、多候选比较和经验复用尚未验收。

## 最终交付进度

1. 背景和目标：见本页及实施计划。
2. 架构和模块：知识基础层已实现，编排器和三角色决策待 Phase 2–4。
3. 图谱 Schema 和示例：已有类型化 Schema、持久知识与可重载导出。
4. Agent 工作流：已有数据接口，算法工作流待 Phase 2。
5. 环境与运行：Phase 1 安装、测试、CLI 和 API 配置已提供。
6. 示例数据和任务：已有模拟业务文档；合成 CSV 与 Demo A–D 待后续阶段。
7. 生成代码示例：待 Phase 2 实际运行产生。
8. 验证结果与报告：已有知识层和 Provider 契约报告，尚无算法成绩。
9. 挑战和解决方案：已处理来源失配、关系非法、重复导入、事务失败和 Provider 异常；后续处理执行隔离与测试泄漏。
10. 扩展方向：按计划逐步加入闭环、修复、经验复用、任务配置和插件。

## 工作区与版本管理

此目录为独立本地 Git 仓库。每阶段验收后形成提交，原始资料保持不变。运行产物放 runtime/，经核验的交付样例纳入 examples/。密钥与私人数据禁止提交。
