# Phase 5：本地界面、任务扩展与质量

状态：**verified（本机 Mock 演示范围）**。实现提交 `97d2f47`，231 项测试全部通过，零失败、零错误、零跳过；[统一验收证据](../examples/phase5/verification.json)与[独立复核](../examples/phase5/review.json)已归档。

Phase 5 的范围是 BANKING77 主界面、运行报告和知识图谱、可信模板/指标插件、合成回归扩展及异常恢复。最终验收入口为 [verify_phase5.py](../scripts/verify_phase5.py)，结果归档在 `examples/phase5/`。本阶段不新增付费 API 调用，真实 API 历史证据仍见 Phase 3/4；界面的 API 入口使用同一 Provider，尚未单独执行付费界面实验。

## 启动与使用

在项目根目录执行：

```sh
uv sync --extra web --locked
# 或：.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m streamlit run src/algofactory/web/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

打开 <http://127.0.0.1:8501>。这是本机演示入口，没有面向公网的用户认证或生产部署支持；保持绑定 127.0.0.1。

1. **新建任务**：默认 BANKING77、Mock、两个候选、每候选最多一次修复、只评估验证集。可选择受限的合成回归任务；客户流失仍只作 CLI 兼容检查。Mock 使用固定需求与响应，容器训练和主机评分真实执行。
2. **评估范围**：关闭“仅验证集评估”后，按既有规则对唯一获选版本进行一次最终测试。`validated` 只表示验证集通过，`accepted` 才表示该流程最终测试通过并完成回写。
3. **经验复用**：开启后复制 Phase 4 经验库，冻结并检索适用经验；要求候选比较开启。数据、协议不匹配时不使用经验。没有证据表明当前经验能普遍降低成本或提升指标。
4. **运行与报告**：选择历史档案或本机新任务，查看四维状态、验证/测试指标、候选版本、错误、轨迹、设计依据与生成代码，下载 Markdown/JSON 报告及 Python 文件。读取报告不会执行候选代码。
5. **知识与来源**：选择实体类型和实体，查看至多 40 条一跳关系；切换到相邻实体继续追踪。展示来源 ID、散列及引用，提供完整 JSON 下载。历史 SQLite 用只读连接打开。

真实 API 必须主动切换模式并点击注明费用的提交按钮；密钥只从 `.env` 或环境变量读取，不写入页面设置。界面最多允许 12 次请求，默认 4 次；比较加修复可能需要更多请求，预算不足会明确停止，不自动扩额。金额未知时不声称实际费用。此前“主机运行成功”的证据不能替代本次运行结果。

首次运行 BANKING77 需要已有冻结数据 `runtime/banking77-data`；缺少数据时按 [Phase 2.5](phase25.md) 导入。修改 worker 或基础依赖后，先运行 `scripts/prepare_sandbox.py` 重建批准的隔离镜像。界面依赖是可选 `web` extra，锁定于 `uv.lock` / `requirements-web.txt`，不加入算法容器的基础依赖。

## 共享架构与恢复边界

界面通过 `RunSettings` 校验任务配置，以参数列表启动后台进程；后台仍调用现有 CLI、`run_workflow` / `run_search`、Docker、独立评分和事务回写。每次任务拥有独立数据副本、知识库和输出目录，保存在 `runtime/web-jobs/<任务ID>/`。没有复制独立业务编排器。

- 提交 ID 幂等；页面刷新、状态轮询和“恢复查看”不会再次生成或调用模型。
- 任务锁随进程死亡释放；全局运行锁限制同一工作台只有一个实际执行任务。冲突任务明确失败，不悄悄排队消耗预算。
- 正常结束保存状态与报告。后台退出且无报告时显示 `interrupted`；已有终态报告但状态文件未完成时可恢复展示报告状态。
- 停止按钮发送协作取消请求；后台中断现有流程，由原执行器清理容器。正在进行的外部操作可能需等待；取消不承诺已发出的 API 请求免费。
- “恢复查看”只恢复浏览，不自动重跑测试、追加修复或重试回写。失败或中断后新建任务会创建独立目录；原始证据与测试预约保留。数据库写入失败保持失败状态，不能冒充成功。
- 本阶段不支持恢复一个已预约最终测试的流程继续训练，也不支持任意文件上传、动态导入第三方插件或生产级分布式任务队列。

## 回归与插件扩展

新增 `regression` 任务：600 行公开合成线性数据，三个数值特征 `x1/x2/x3`，连续目标 `value`，随机种子 42；按 60/20/20 独立划分。训练内中位数填补、标准化和 Ridge(alpha=1.0)；独立主机计算 MAE/RMSE。门槛预先固定为 MAE ≤ 1.0、RMSE ≤ 1.5，不依据测试分数校准。模型只需 fit/predict，回归输出保留小数，不包含类别或概率。仍检查缺失列、非法数值、固定种子重复、长度、有限值和行对齐。

```sh
.venv/bin/python -m algofactory.cli prepare-regression --output-dir runtime/regression-data
.venv/bin/python -m algofactory.cli demo --task regression --mode mock --dataset-dir runtime/regression-data --db runtime/regression.sqlite --output-dir runtime/regression-new
.venv/bin/python -m algofactory.cli plugins
```

插件边界见 [plugins.py](../src/algofactory/plugins.py)。`TemplatePlugin` 注册受限工厂源码，先通过 AST 安全检查，再由 Mock 生成 Provider 选择；候选代码仍只在 Docker 运行。`MetricPlugin` 注册可信主机评分函数，声明任务类型与方向，拒绝重复 ID、错误任务、非有限或负数结果。当前指标协议明确支持 MAE/RMSE；新增指标名称需同步审查契约，不能借插件绕过冻结规则。

仓库扩展例：创建 `PluginRegistry` 或 `default_registry()`，调用 `register_template` / `register_metric`；将模板注册表和 `template_overrides={"regression": "新模板ID"}` 传给 `MockWorkflowProvider`，无需修改编排器。`tests/test_phase5.py` 的真实 Docker 测试使用新增模板 ID 完成完整回归流程。Ridge 模板和 MAE/RMSE 注册是本阶段的实际插件样例。插件代码必须由开发者审查，不接受 LLM 生成的主机评分函数。

## 验证与限制

```sh
# 实现源码提交后执行；需要 Docker、已批准镜像、冻结 BANKING77 数据和 web 测试依赖。
.venv/bin/python scripts/verify_phase5.py --output-dir runtime/phase5-verification-new
```

该入口执行全部测试（必需测试零跳过）、三任务 CLI 真实运行、回归危险代码拒绝、数据库重开/图谱往返、真实一秒超时与容器清理；通过 Streamlit AppTest 实际点击表单，启动真实后台进程与容器，覆盖 BANKING77 经验开关入口、回归、刷新不重提、全新页面恢复查看和报告下载控件。预启动取消验证不产生模型调用；其他错误边界包含显式单元模拟，不能称作真实 OOM 压测。浏览器视检补充页面与图谱可读性证据。

界面采用 Streamlit 的 [AppTest](https://docs.streamlit.io/develop/concepts/app-testing/get-started) 和 [定时 fragment](https://docs.streamlit.io/develop/concepts/architecture/fragments) 能力；阶段结论以项目保存的测试与运行证据为准。

Phase 5 退出后进入 Phase 6：干净环境冷启动、交付清单、完整 README、剩余 Gate 总审和 GitHub 提交准备。本阶段通过不等于 G1–G5 全项目交付完成。


报告的设计解释由已接受任务和方案生成，引用算法实体、知识证据与验证运行 ID；缺少可核对方案时不编造说明。三个角色是共享编排器中的知识、构建、确定性审查职责，输入/输出与决策可追踪，不声称三个独立自治进程。


## 本轮结果

| 路径 | 状态 | 实测指标 |
| --- | --- | --- |
| BANKING77 CLI | accepted | 验证 Macro-F1 0.872975；最终测试 Macro-F1 0.878695 |
| 客户流失 CLI | accepted | 最终测试 F1 0.666667、ROC-AUC 0.816260；与历史基线一致 |
| 合成回归 CLI | accepted | 验证 MAE 0.396443、RMSE 0.504133；最终测试 MAE 0.405306、RMSE 0.501081 |
| BANKING77 Web（经验开启） | validated | 验证 Macro-F1 0.872975；未访问最终测试 |
| 合成回归 Web | validated | 验证 MAE 0.396443、RMSE 0.504133；未访问最终测试 |

危险代码被拒绝并保留失败报告；真实一秒超时后容器清理成功。预启动取消没有模型调用。231 项测试包含真实 Docker、插件扩展执行、界面状态、路径边界和既有 API 模拟传输；新增付费 API 请求为零。[界面截图](../examples/phase5/browser-review/workbench.png)与[图谱截图](../examples/phase5/browser-review/graph.png)作为浏览器视检补充，不替代运行证据。
