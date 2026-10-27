# AlgoFactory

面向客户流失预测的 AI Agent 算法能力工厂原型。目标是能力抽取、代码复刻、独立验证、修复与经验回写。当前为 Phase 0 文档与 Git 骨架，尚未实现算法闭环、LLM Provider、知识库、隔离执行和 Streamlit。

## 文档入口

- [题目原文](docs/source/exam-original.txt) 与 [用户方案原始附件](docs/source/discussion-plan-original.txt)
- [总体实施计划与问题定义](docs/implementation-plan.md)
- [需求追踪矩阵](docs/requirements-matrix.md) 与 [CSV](docs/requirements-matrix.csv)
- [架构、图谱及数据契约](docs/architecture.md)
- [验收 Gate 与演示协议](docs/acceptance-gates.md)

## 当前可复现操作

在项目根目录运行，使用 Python 3.11 或更高版本：

```sh
python3 --version
python3 scripts/check_scaffold.py
PYTHONPATH=src python3 -m algofactory.cli status
```

骨架检查不需要安装第三方包、联网或 API Key。Phase 1 再建立虚拟环境、验证依赖并锁定版本。requirements.txt 当前记录零第三方运行依赖，不能用于安装未来完整应用。

## 最终 README 交付栏目

1. 背景和目标：自然语言需求生成可验证算法并沉淀经验，详见实施计划。
2. 系统架构和模块：Python 编排器、三角色、确定性工具，详见架构文档。
3. 图谱 schema 和示例：当前提供设计，真实实体与抽取样例待 Phase 1。
4. Agent 工作流：当前提供状态流设计，实现及决策轨迹待 Phase 2–4。
5. 环境与运行：以上命令仅检查骨架，完整安装和 Docker/API 指南待验证。
6. 示例数据和测试任务：客户流失主场景与轻量回归扩展，Demo A–D 待实现。
7. 生成代码示例：待 Phase 2 真实运行产生。
8. 验证结果与报告：尚无算法验证结果，不提供虚构指标。
9. 挑战和解决方案：隔离执行、测试泄漏及经验可追踪性已列入架构和 Gate；实际问题随实施补充。
10. 扩展方向：任务配置、模板与指标插件为本轮范围；复杂搜索及生产部署暂不纳入。

## 工作区与版本管理

此目录为独立本地 Git 仓库，不配置远端、不覆盖其他项目。后续每阶段验收后提交，原始资料保持不变。运行产物放 runtime/，经核验的交付样例再纳入 examples/。密钥与私人数据禁止提交。
